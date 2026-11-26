"""Additional hours with deferred payment (sales.additional_hours).

Administrators (accounts.manage_additional_hours) add, change, waive and
withdraw additional hours and void their payments; an administrator or the
student's own mentor (accounts.collect_additional_hours_payments, the mentor
checked by the service) reads them and records payments.
"""
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import ByMethod, HasAppPermission
from . import additional_hours
from .allocation_models import (DIRECT_METHOD_CHOICES, HOUR_STEP, MAX_AMOUNT, MAX_HOURS, NOTES_MAX_LENGTH,
                                REASON_MAX_LENGTH, REFERENCE_MAX_LENGTH, VoidKind)
from .services import SalesError
from .views import _invalid, _paged, _refused

COLLECT = HasAppPermission(additional_hours.COLLECT)
MANAGE = HasAppPermission(additional_hours.MANAGE)


class AllocationSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    purchase = serializers.UUIDField()
    chapter = serializers.UUIDField(required=False, allow_null=True)
    hours = serializers.DecimalField(max_digits=5, decimal_places=1, min_value=HOUR_STEP, max_value=MAX_HOURS)
    amount = serializers.DecimalField(max_digits=15, decimal_places=0, min_value=1, max_value=MAX_AMOUNT)
    due_date = serializers.DateField()
    reason = serializers.CharField(max_length=REASON_MAX_LENGTH)
    confirm_duplicate = serializers.BooleanField(default=False)

    def validate_hours(self, value):
        if value % HOUR_STEP:
            raise serializers.ValidationError('Use whole or half hours.')
        return value


class AllocationChangeSerializer(serializers.Serializer):
    due_date = serializers.DateField(required=False)
    amount = serializers.DecimalField(max_digits=15, decimal_places=0, min_value=1, max_value=MAX_AMOUNT, required=False)
    change_reason = serializers.CharField(max_length=REASON_MAX_LENGTH)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=REASON_MAX_LENGTH)


class VoidSerializer(ReasonSerializer):
    kind = serializers.ChoiceField(choices=VoidKind.choices)


class PaymentSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=0, min_value=1, max_value=MAX_AMOUNT)
    method = serializers.ChoiceField(choices=DIRECT_METHOD_CHOICES)
    payment_date = serializers.DateField(default=timezone.localdate)
    transaction_reference = serializers.CharField(max_length=REFERENCE_MAX_LENGTH, required=False, allow_blank=True)
    received_confirmed = serializers.BooleanField(default=False)
    proof = serializers.FileField(required=False)
    notes = serializers.CharField(max_length=NOTES_MAX_LENGTH, required=False, allow_blank=True)
    confirm_duplicate = serializers.BooleanField(default=False)

    def validate_payment_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('A received payment cannot be dated in the future.')
        return value


class RegisterFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[*additional_hours.STATUSES, 'OPEN'], required=False)
    overdue = serializers.BooleanField(required=False)
    mentor = serializers.UUIDField(required=False)
    student = serializers.UUIDField(required=False)
    due_from = serializers.DateField(required=False)
    due_to = serializers.DateField(required=False)


class StudentAdditionalHoursView(APIView):
    """GET/POST /api/sales/students/<id>/additional-hours/ — the student's additional hours; an administrator adds more."""
    permission_classes = [IsAuthenticated, ByMethod(GET=COLLECT, POST=MANAGE)]

    def get(self, request, pk):
        try:
            return Response(additional_hours.student_overview(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)

    def post(self, request, pk):
        serializer = AllocationSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the additional hours.')
        try:
            allocation, created = additional_hours.create(request.user, pk, serializer.validated_data, request)
            return Response(additional_hours.detail(request.user, allocation.pk, request), status=201 if created else 200)
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursEligibilityView(APIView):
    """GET /api/sales/students/<id>/additional-hours/eligibility/ — whether hours may be added now, and the plans."""
    permission_classes = [IsAuthenticated, MANAGE]

    def get(self, request, pk):
        try:
            return Response(additional_hours.eligibility_data(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursRegisterView(APIView):
    """GET /api/sales/additional-hours/?status=&overdue=&mentor=&student=&due_from=&due_to=&page= — across students."""
    permission_classes = [IsAuthenticated, COLLECT]

    def get(self, request):
        serializer = RegisterFilterSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the filters.')
        try:
            rows, totals = additional_hours.register(request.user, serializer.validated_data, request)
        except SalesError as exc:
            return _refused(exc)
        response = _paged(request, rows, lambda page: [
            additional_hours.allocation_data(row, request.user, request, paid=row.paid, last_paid_on=row.last_paid_on)
            for row in page])
        response.data['summary'] = totals
        return response


class AdditionalHoursView(APIView):
    """GET/PATCH /api/sales/additional-hours/<id>/ — one allocation with its payments; an administrator changes it."""
    permission_classes = [IsAuthenticated, ByMethod(GET=COLLECT, PATCH=MANAGE)]

    def get(self, request, pk):
        try:
            return Response(additional_hours.detail(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)

    def patch(self, request, pk):
        serializer = AllocationChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the change.')
        try:
            additional_hours.update(request.user, pk, serializer.validated_data, request)
            return Response(additional_hours.detail(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursClosingView(APIView):
    """POST /api/sales/additional-hours/<id>/waive/ and /withdraw/ — with the reason."""
    permission_classes = [IsAuthenticated, MANAGE]
    closing = None

    def post(self, request, pk):
        serializer = ReasonSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Say why.')
        try:
            getattr(additional_hours, self.closing)(request.user, pk, serializer.validated_data, request)
            return Response(additional_hours.detail(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursPaymentsView(APIView):
    """POST /api/sales/additional-hours/<id>/payments/ — money received, with its receipt (multipart)."""
    permission_classes = [IsAuthenticated, COLLECT]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, pk):
        serializer = PaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the payment.')
        try:
            payment, created = additional_hours.record_payment(request.user, pk, serializer.validated_data, request)
            return Response({'payment': additional_hours.payment_data(payment),
                             'allocation': additional_hours.detail(request.user, pk, request)},
                            status=201 if created else 200)
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursPaymentVoidView(APIView):
    """POST /api/sales/additional-hours/<id>/payments/<payment id>/void/ — with its kind and reason."""
    permission_classes = [IsAuthenticated, MANAGE]

    def post(self, request, pk, payment_id):
        serializer = VoidSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Say why the payment is voided.')
        try:
            additional_hours.void_payment(request.user, pk, payment_id, serializer.validated_data, request)
            return Response(additional_hours.detail(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class AdditionalHoursProofView(APIView):
    """GET /api/sales/additional-hours/<id>/payments/<payment id>/proof/ — a payment's receipt."""
    permission_classes = [IsAuthenticated, COLLECT]

    def get(self, request, pk, payment_id):
        try:
            payment = additional_hours.proof(request.user, pk, payment_id, request)
            handle = payment.proof.open('rb')
        except SalesError as exc:
            return _refused(exc)
        except FileNotFoundError:
            return Response({'error': 'NOT_FOUND'}, status=404)
        response = FileResponse(handle, as_attachment=True, filename=payment.proof_name, content_type=payment.proof_content_type)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
