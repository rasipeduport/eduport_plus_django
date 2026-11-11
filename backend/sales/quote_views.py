"""
The quotes API (sales.quotes):

    GET  /api/sales/quotes/               the caller's quotes -- every one with manage_sales_quotes -- paged
    POST /api/sales/quotes/               a new quote from the catalogue on sale
    GET  /api/sales/quotes/<id>/          one quote, as it was issued
    GET  /api/sales/quotes/<id>/pdf/      its PDF, as it was issued
    POST /api/sales/quotes/<id>/cancel/   withdraw it (administrators)

Quoting needs accounts.create_sales_quotes (the BDE and ADMIN roles'); seeing
another's quote or cancelling one accounts.manage_sales_quotes (the ADMIN
role's alone). A quote the caller may not see is not found, whoever's it is.
Errors answer ``{"error": CODE, "message": ..., "fields"?}``, as the rest of
the Sales API does.
"""
import uuid

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import ByMethod, HasAnyAppPermission, HasAppPermission

from . import quotes
from .downloads import SyllabusPdfView, quote_pdf_response
from .models import MAX_CHAPTERS, ChapterClassMode, PlanType, QuoteStatus
from .services import SalesError
from .views import _error, _invalid, _paged, _refused

SEE_QUOTES = HasAnyAppPermission(quotes.CREATE_QUOTES, quotes.MANAGE_QUOTES)


class QuoteCreateSerializer(serializers.Serializer):
    syllabus = serializers.UUIDField()
    # The revision the syllabus was shown at: a newer one published since is refused (REVISION_CHANGED).
    revision = serializers.IntegerField(min_value=1)
    plan_type = serializers.ChoiceField(choices=PlanType.choices)
    # Omitted by older clients: Chapter Plan defaults to Regular; other plans have no mode.
    class_mode = serializers.ChoiceField(choices=ChapterClassMode.choices, required=False)
    collection_mode = serializers.ChoiceField(choices=['FULL', 'PARTIAL', 'AUTOPAY'])
    # A Chapter Plan's chapters or a Bridge Course's days (none, or every day: the whole course).
    chapter_ids = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_CHAPTERS, required=False, default=list)
    # The enquiry it answers: the caller's own (or any lead, for whoever may read every lead).
    lead = serializers.UUIDField(required=False, allow_null=True)
    replaces = serializers.UUIDField(required=False, allow_null=True)
    # Optional for legacy clients; the enquiry chooser always pins the amount reviewed.
    pricing_version = serializers.IntegerField(min_value=1, required=False)


class QuoteCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


def _no_quote():
    return _error('NOT_FOUND', 'No such quote.', status.HTTP_404_NOT_FOUND)


def _visible(request, pk):
    return quotes.visible_quotes(request.user, request).filter(pk=pk).first()


class QuotesView(APIView):
    """
    GET  /api/sales/quotes/?status=&q=&created_by=&page=&page_size=
         The caller's quotes, newest first -- every quote for whoever holds
         manage_sales_quotes, who may narrow them to one BDE's (``created_by``)
         -- always paged. ``q`` matches a reference (Q-000012, or 12) or the
         syllabus's title; ``status`` is a QuoteStatus.
    POST /api/sales/quotes/ (QuoteCreateSerializer)
         A new quote: 201 with it in full. Refused, nothing is kept.
    """
    permission_classes = [IsAuthenticated, ByMethod(GET=SEE_QUOTES, POST=HasAppPermission(quotes.CREATE_QUOTES))]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        rows = quotes.visible_quotes(request.user, request)
        if lead := (params.get('lead') or '').strip():
            try:
                rows = rows.filter(lead_id=uuid.UUID(lead))
            except ValueError:
                return _error('INVALID_INPUT', 'Unknown enquiry.', status.HTTP_400_BAD_REQUEST, fields=['lead'])
        state = (params.get('status') or '').strip().upper()
        if state:
            if state not in QuoteStatus.values:
                return _error('INVALID_INPUT', 'Unknown status.', status.HTTP_400_BAD_REQUEST, fields=['status'])
            rows = rows.filter(status=state)
        if owner := (params.get('created_by') or '').strip():
            try:
                rows = rows.filter(created_by_id=uuid.UUID(owner))
            except ValueError:
                return _error('INVALID_INPUT', 'Unknown account.', status.HTTP_400_BAD_REQUEST, fields=['created_by'])
        if q := (params.get('q') or '').strip():
            digits = q.upper().removeprefix('Q-')
            # A reference's digits (never past the column's range), else words of the title.
            numbered = digits.isdigit() and len(digits) <= 9
            rows = rows.filter(number=int(digits)) if numbered else rows.filter(revision__title__icontains=q)
        return _paged(request, rows.order_by('-number'), lambda page: [quotes.quote_row(quote) for quote in page])

    def post(self, request, *args, **kwargs):
        serializer = QuoteCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the quote.')
        try:
            quote = quotes.create_quote(request.user, serializer.validated_data, request=request)
        except SalesError as exc:
            return _refused(exc)
        return Response(quotes.quote_data(quote), status=status.HTTP_201_CREATED)


class QuoteDetailView(APIView):
    """GET /api/sales/quotes/<id>/: one quote as it was issued -- the caller's own, or any for a manager; else 404."""
    permission_classes = [IsAuthenticated, SEE_QUOTES]

    def get(self, request, pk, *args, **kwargs):
        quote = _visible(request, pk)
        if quote is None:
            return _no_quote()
        return Response(quotes.quote_data(quote), status=status.HTTP_200_OK)


class EnquiryPlanView(APIView):
    """GET: the current saved choice and immutable quote history of an accessible enquiry."""
    permission_classes = [IsAuthenticated, SEE_QUOTES]

    def get(self, request, pk, *args, **kwargs):
        try:
            return Response(quotes.enquiry_plan(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class QuotePdfView(SyllabusPdfView, APIView):
    """GET /api/sales/quotes/<id>/pdf/[?disposition=inline]: its PDF, drawn from the quote alone, as it was issued."""
    permission_classes = [IsAuthenticated, SEE_QUOTES]

    def get(self, request, pk, *args, **kwargs):
        quote = _visible(request, pk)
        if quote is None:
            return _no_quote()
        return quote_pdf_response(request, quote)


class QuoteCancelView(APIView):
    """POST /api/sales/quotes/<id>/cancel/ {"reason"}: an issued quote withdrawn by an administrator."""
    permission_classes = [IsAuthenticated, HasAppPermission(quotes.MANAGE_QUOTES)]

    def post(self, request, pk, *args, **kwargs):
        serializer = QuoteCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Say why the quote is cancelled.')
        try:
            quote = quotes.cancel_quote(request.user, pk, serializer.validated_data['reason'].strip(), request=request)
        except SalesError as exc:
            return _refused(exc)
        return Response(quotes.quote_data(quote), status=status.HTTP_200_OK)
