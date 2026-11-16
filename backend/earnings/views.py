"""
The Tutor Earnings API, under /api/earnings/.

Administrators (accounts.view_tutor_earnings) read every tutor's earnings;
setting the rates (accounts.manage_tutor_rates), recording and voiding
payments (accounts.manage_tutor_payments) and reversing or adjusting the
ledger or keeping an earning in review as earned
(accounts.correct_tutor_earnings) each have their own permission, all the
administrators' alone. A tutor (accounts.view_own_earnings) reads their
own earnings under /me/ -- always the signed-in account's: no tutor is ever
named in the request.

Every GET only reads: earnings are written by the sync (earnings.ledger),
never by a page.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import ByMethod, HasAppPermission

from . import corrections, payments, rates, summaries
from .models import EarningEntry, TutorPayment
from .values import EarningsError, parse_month

User = get_user_model()

VIEW = HasAppPermission('accounts.view_tutor_earnings')
RATES = HasAppPermission('accounts.manage_tutor_rates')
PAYMENTS = HasAppPermission('accounts.manage_tutor_payments')
CORRECT = HasAppPermission('accounts.correct_tutor_earnings')
OWN = HasAppPermission('accounts.view_own_earnings')

TUTOR_NOT_FOUND = 'TUTOR_NOT_FOUND'


def refused(exc):
    return Response(exc.response_data(), status=exc.status)


def _month(request):
    raw = request.query_params.get('month')
    return parse_month(raw) if raw else None


def earnings_account(tutor_id):
    """A tutor -- or a former one with earnings or payments -- else EarningsError(TUTOR_NOT_FOUND, 404)."""
    tutor = User.objects.filter(
        Q(role='TUTOR') | Q(earning_entries__isnull=False) | Q(earnings_payments__isnull=False), pk=tutor_id,
    ).distinct().first()
    if tutor is None:
        raise EarningsError(TUTOR_NOT_FOUND, 'No such tutor.', status=404)
    return tutor


def rates_overview():
    """The rates page: the global rates in effect and their history, and each tutor's own rates in effect."""
    now = timezone.now()
    book = rates.RateBook.load()
    tutors = []
    for tutor in summaries.tutor_accounts():
        own = [{'class_type': class_type, 'amount': summaries.money(version.amount)}
               for class_type in rates.ClassType.values
               for version in [book.own(tutor.pk, class_type, now)] if version is not None]
        tutors.append({'id': str(tutor.pk), 'name': summaries.name_of(tutor), 'email': tutor.email,
                       'active': tutor.is_active and tutor.role == 'TUTOR', 'own_rates': own})
    current = []
    for class_type in rates.ClassType.values:
        version, _source = book.resolve(None, class_type, now)
        current.append({'class_type': class_type, 'unit': rates.unit_of(class_type),
                        'amount': summaries.money(version.amount) if version else None,
                        'effective_from': summaries.iso(version.effective_from) if version else None})
    return {
        **summaries.status_block(),
        'rates': current,
        'history': [summaries.rate_row(version) for version in book.history(None)],
        'tutors': tutors,
    }


class OverviewView(APIView):
    """GET /api/earnings/overview/?month=YYYY-MM&search=&balance=pending|paid|overpaid|none&rate=tutor|global"""
    permission_classes = [IsAuthenticated, VIEW]

    def get(self, request):
        try:
            month = _month(request)
        except EarningsError as exc:
            return refused(exc)
        params = request.query_params
        return Response(summaries.overview(month, params.get('search', ''), params.get('balance', ''),
                                           params.get('rate', '')))


class RatesView(APIView):
    """
    GET  /api/earnings/rates/  the global rates, their history and each tutor's own rates
    POST /api/earnings/rates/  {"rates": {"SESSION": "425.00"}, "reason": "..."}  change global rates, from now
    """
    permission_classes = [IsAuthenticated, ByMethod(GET=VIEW, POST=RATES)]

    def get(self, request):
        return Response(rates_overview())

    def post(self, request):
        try:
            rates.set_global_rates(request.user, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        return Response({'success': True, **rates_overview()})


class InitialPricingView(APIView):
    """
    POST /api/earnings/rates/initial/
         {"global": {"DIAGNOSTIC": "300", "DEMO": "300", "SESSION": "400"},
          "tutors": [{"tutor": <id>, "rates": {"DEMO": "350"}}], "reason": "...", "confirm": true}

    Start pricing, once: the initial rates price every eligible class from the activation.
    """
    permission_classes = [IsAuthenticated, RATES]

    def post(self, request):
        try:
            rates.start_pricing(request.user, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        return Response({'success': True, **rates_overview()}, status=status.HTTP_201_CREATED)


class ReviewView(APIView):
    """GET /api/earnings/review/  earnings whose class changed since they were earned."""
    permission_classes = [IsAuthenticated, VIEW]

    def get(self, request):
        return Response({'items': summaries.review_items()})


class TutorEarningsView(APIView):
    """GET /api/earnings/tutors/<tutor_id>/?month=YYYY-MM  one tutor's earnings, rates and payments."""
    permission_classes = [IsAuthenticated, VIEW]

    def get(self, request, tutor_id):
        try:
            month = _month(request)
            tutor = earnings_account(tutor_id)
        except EarningsError as exc:
            return refused(exc)
        return Response(summaries.tutor_earnings(tutor, month, admin=True))


def _entries_response(request, tutor, admin):
    try:
        month = _month(request)
    except EarningsError as exc:
        return refused(exc)
    entries = summaries.entries_page(tutor, month, request.query_params.get('class_type'))
    page, page_size = page_params(request)
    total = entries.count()
    start = (page - 1) * page_size
    # A page past the last is empty -- without asking Postgres for an OFFSET it cannot hold.
    rows = entries[start:start + page_size] if start < total else []
    return Response({'count': total, 'page': page, 'page_size': page_size,
                     'results': [summaries.entry_row(entry, admin) for entry in rows]})


class TutorEntriesView(APIView):
    """GET /api/earnings/tutors/<tutor_id>/entries/?month=&class_type=&page=  one tutor's ledger, newest first."""
    permission_classes = [IsAuthenticated, VIEW]

    def get(self, request, tutor_id):
        try:
            tutor = earnings_account(tutor_id)
        except EarningsError as exc:
            return refused(exc)
        return _entries_response(request, tutor, admin=True)


class TutorRatesView(APIView):
    """POST /api/earnings/tutors/<tutor_id>/rates/  {"rates": {"DEMO": "350", "SESSION": null}, "reason": "..."}"""
    permission_classes = [IsAuthenticated, RATES]

    def post(self, request, tutor_id):
        try:
            tutor = rates.tutor_account(tutor_id)
            rates.set_tutor_rates(request.user, tutor, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        return Response({'success': True, **summaries.tutor_earnings(tutor, admin=True)})


class TutorPaymentsView(APIView):
    """
    POST /api/earnings/tutors/<tutor_id>/payments/
         {"request_id", "amount", "paid_on", "method", "reference", "notes", "confirm_duplicate"}

    Record a payment already made to the tutor outside Eduport Plus. 201 when
    recorded, 200 when this request was recorded before.
    """
    permission_classes = [IsAuthenticated, PAYMENTS]

    def post(self, request, tutor_id):
        try:
            tutor = earnings_account(tutor_id)
            payment, created = payments.record_payment(request.user, tutor, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        payment = TutorPayment.objects.select_related('recorded_by', 'voided_by').get(pk=payment.pk)
        return Response(
            {'success': True, 'created': created, 'payment': summaries.payment_row(payment, admin=True),
             'outstanding': summaries.money(payments.outstanding(tutor.pk))},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TutorAdjustmentsView(APIView):
    """POST /api/earnings/tutors/<tutor_id>/adjustments/  {"amount": "-450.00", "month": "YYYY-MM", "reason", "entry"}"""
    permission_classes = [IsAuthenticated, CORRECT]

    def post(self, request, tutor_id):
        try:
            tutor = earnings_account(tutor_id)
            entry = corrections.add_adjustment(request.user, tutor, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        entry = EarningEntry.objects.select_related('created_by').get(pk=entry.pk)
        return Response({'success': True, 'entry': summaries.entry_row(entry, admin=True)},
                        status=status.HTTP_201_CREATED)


class PaymentVoidView(APIView):
    """POST /api/earnings/payments/<payment_id>/void/  {"reason": "..."}"""
    permission_classes = [IsAuthenticated, PAYMENTS]

    def post(self, request, payment_id):
        try:
            payment = payments.void_payment(request.user, payment_id, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        payment = TutorPayment.objects.select_related('recorded_by', 'voided_by').get(pk=payment.pk)
        return Response({'success': True, 'payment': summaries.payment_row(payment, admin=True),
                         'outstanding': summaries.money(payments.outstanding(payment.tutor_id))})


class EntryReverseView(APIView):
    """POST /api/earnings/entries/<entry_id>/reverse/  {"reason": "..."}"""
    permission_classes = [IsAuthenticated, CORRECT]

    def post(self, request, entry_id):
        try:
            reversal = corrections.reverse_entry(request.user, entry_id, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        reversal = EarningEntry.objects.select_related('created_by').get(pk=reversal.pk)
        return Response({'success': True, 'entry': summaries.entry_row(reversal, admin=True)},
                        status=status.HTTP_201_CREATED)


class EntryKeepView(APIView):
    """POST /api/earnings/entries/<entry_id>/keep/  {"reason": "..."}  keep an earning in review as earned."""
    permission_classes = [IsAuthenticated, CORRECT]

    def post(self, request, entry_id):
        try:
            review = corrections.keep_entry(request.user, entry_id, request.data, request=request)
        except EarningsError as exc:
            return refused(exc)
        return Response({'success': True, 'review': summaries.review_row(review)}, status=status.HTTP_201_CREATED)


class MyEarningsView(APIView):
    """GET /api/earnings/me/?month=YYYY-MM  the signed-in tutor's own earnings, rates and payments."""
    permission_classes = [IsAuthenticated, OWN]

    def get(self, request):
        try:
            month = _month(request)
        except EarningsError as exc:
            return refused(exc)
        return Response(summaries.tutor_earnings(request.user, month, admin=False))


class MyEntriesView(APIView):
    """GET /api/earnings/me/entries/?month=&class_type=&page=  the signed-in tutor's own ledger."""
    permission_classes = [IsAuthenticated, OWN]

    def get(self, request):
        return _entries_response(request, request.user, admin=False)

