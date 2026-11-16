"""A student's purchases and payments after enrollment, for their mentor or an administrator.

Creating an additional purchase is sales.additional_purchases'; reading and
collecting any of the student's purchases (the initial sale too) is
sales.student_finance's.
"""
from decimal import Decimal

from django.http import FileResponse
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission
from . import additional_purchases, payments, student_finance
from .models import ChapterClassMode, PlanType
from .payment_models import PaymentMethod, PaymentStatus
from .payment_views import ReceiptSerializer
from .services import SalesError
from .views import _invalid, _paged, _refused

MENTOR_PURCHASES = [IsAuthenticated, HasAppPermission(additional_purchases.PERMISSION)]


class PurchaseSerializer(serializers.Serializer):
    syllabus = serializers.UUIDField()
    revision = serializers.IntegerField(min_value=1)
    plan_type = serializers.ChoiceField(choices=PlanType.choices)
    chapter_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True, max_length=500)
    class_mode = serializers.ChoiceField(choices=ChapterClassMode.choices, required=False, allow_null=True)
    collection_mode = serializers.ChoiceField(choices=['FULL', 'PARTIAL', 'AUTOPAY'])
    preview = serializers.BooleanField(default=False)
    request_id = serializers.UUIDField(required=False)
    # The pricing the mentor reviewed (the preview's): a purchase is refused if it changed meanwhile.
    pricing_version = serializers.IntegerField(min_value=1, required=False)

    def validate(self, data):
        if not data['preview'] and not data.get('request_id'):
            raise serializers.ValidationError({'request_id': 'A request UUID is required to create the purchase.'})
        return data


class StudentPurchasesView(APIView):
    """GET/POST /api/sales/students/<id>/purchases/ — the student's sales, and a new additional purchase."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        syllabus = request.query_params.get('syllabus')
        if syllabus:
            field = serializers.UUIDField()
            try:
                syllabus = field.run_validation(syllabus)
            except serializers.ValidationError:
                return Response({'error': 'VALIDATION_ERROR', 'message': 'Choose a syllabus on sale.'}, status=400)
        try:
            return Response(additional_purchases.overview(request.user, pk, request, syllabus_id=syllabus))
        except SalesError as exc:
            return _refused(exc)

    def post(self, request, pk):
        serializer = PurchaseSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the purchase.')
        data = serializer.validated_data
        try:
            if data['preview']:
                return Response({'preview': additional_purchases.preview(request.user, pk, data, request)})
            sale = additional_purchases.create(request.user, pk, data, request)
            return Response(student_finance.state(request.user, sale.pk, request), status=201)
        except SalesError as exc:
            return _refused(exc)


class StudentFinanceView(APIView):
    """GET /api/sales/students/<id>/finance/ — every purchase, its balance, the totals and Autopay at a glance."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        try:
            return Response(student_finance.finance(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class HistoryFilterSerializer(serializers.Serializer):
    sale = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False)
    method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False)


class StudentPaymentsView(APIView):
    """GET /api/sales/students/<id>/payments/?sale=&status=&method=&page=&page_size= — the student's payments, newest first, paged."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        serializer = HistoryFilterSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the filters.')
        filters = serializer.validated_data
        try:
            rows = student_finance.payment_history(request.user, pk, request, sale_id=filters.get('sale'),
                                                   status=filters.get('status'), method=filters.get('method'))
        except SalesError as exc:
            return _refused(exc)
        return _paged(request, rows, lambda page: student_finance.history_rows(list(page)))


class PurchaseView(APIView):
    """GET /api/sales/purchases/<sale id>/ — one of the student's purchases: plan, totals, payments."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        try:
            return Response(student_finance.state(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class ClassesSerializer(serializers.Serializer):
    classes = serializers.DecimalField(max_digits=9, decimal_places=1, min_value=Decimal('0.5'))


class PurchaseAmountView(APIView):
    """GET /api/sales/purchases/<sale id>/amount/?classes= — the server-calculated amount for those classes."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        serializer = ClassesSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the classes.')
        try:
            return Response(student_finance.amount(request.user, pk, serializer.validated_data, request))
        except SalesError as exc:
            return _refused(exc)


class CollectionSerializer(ClassesSerializer, ReceiptSerializer):
    method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.STRIPE)


class PurchasePaymentsView(APIView):
    """POST /api/sales/purchases/<sale id>/payments/ — a one-time Stripe link, or a direct receipt with its proof."""
    permission_classes = MENTOR_PURCHASES
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, pk):
        serializer = CollectionSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the payment.')
        try:
            payment = student_finance.collect(request.user, pk, serializer.validated_data, request)
            return Response({'payment': payments.payment_data(payment),
                             'state': student_finance.state(request.user, pk, request)}, status=201)
        except SalesError as exc:
            return _refused(exc)


class PurchaseExpireView(APIView):
    """POST /api/sales/purchases/<sale id>/payments/<payment id>/expire/ — expire an unpaid link."""
    permission_classes = MENTOR_PURCHASES

    def post(self, request, pk, payment_id):
        try:
            student_finance.expire(request.user, pk, payment_id, request)
            return Response(student_finance.state(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class PurchaseProofView(APIView):
    """GET /api/sales/purchases/<sale id>/payments/<payment id>/proof/ — a direct payment's receipt."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk, payment_id):
        try:
            payment = student_finance.proof(request.user, pk, payment_id, request)
            handle = payment.proof.open('rb')
        except SalesError as exc:
            return _refused(exc)
        except FileNotFoundError:
            return Response({'error': 'NOT_FOUND'}, status=404)
        response = FileResponse(handle, as_attachment=True, filename=payment.proof_name, content_type=payment.proof_content_type)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
