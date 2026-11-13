from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission
from . import payments, review, student_accounts
from .account_models import GuardianRelationship
from .services import SalesError
from .views import _invalid, _refused

ADMIN_ONLY = [IsAuthenticated, HasAppPermission(payments.MANAGE), HasAppPermission(student_accounts.OVERSIGHT)]


class BillingContactSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    relationship = serializers.ChoiceField(choices=GuardianRelationship.choices, required=False)


class BillingContactView(APIView):
    """PUT /api/sales/enquiries/<id>/sale/billing-contact/ — the parent details Django sends to Stripe."""
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def put(self, request, pk):
        serializer = BillingContactSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the billing contact.')
        try:
            student_accounts.update_billing_contact(request.user, pk, serializer.validated_data, request)
            return Response(payments.sale_data(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)


class IdentityCorrectionSerializer(serializers.Serializer):
    student_name = serializers.CharField(max_length=255)
    reason = serializers.CharField(max_length=2000)


class IdentityCorrectionView(APIView):
    """POST /api/sales/accounts/<id>/identity-correction/ — Admin, with a reason, audited."""
    permission_classes = ADMIN_ONLY

    def post(self, request, pk):
        serializer = IdentityCorrectionSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Enter the corrected name and the reason.')
        try:
            account = student_accounts.correct_identity(request.user, pk, serializer.validated_data, request)
            return Response(student_accounts.account_data(account, request.user, request))
        except SalesError as exc:
            return _refused(exc)


class CancelAutopaySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)
    source = serializers.ChoiceField(choices=['ADMIN', 'PARENT_REQUEST'], default='ADMIN')


class CancelAutopayView(APIView):
    """POST /api/sales/autopay/<id>/cancel/ — stops future collections; history is kept."""
    permission_classes = ADMIN_ONLY

    def post(self, request, pk):
        serializer = CancelAutopaySerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Explain why Autopay is being cancelled.')
        from .billing import cancel_agreement
        try:
            agreement = cancel_agreement(request.user, pk, serializer.validated_data, request)
            return Response(payments.sale_data(request.user, agreement.purchase.sale.enquiry_id, request))
        except SalesError as exc:
            return _refused(exc)


class StripeReviewView(APIView):
    """GET /api/sales/stripe-review/?status=OPEN — Stripe activity Django could not attribute."""
    permission_classes = ADMIN_ONLY

    def get(self, request):
        status = request.query_params.get('status') or None
        if status and status not in ('OPEN', 'LINKED', 'DISMISSED'):
            return Response({'error': 'VALIDATION_ERROR', 'message': 'Unknown review status.'}, status=400)
        try:
            return Response({'items': review.items(request.user, status, request)})
        except SalesError as exc:
            return _refused(exc)


class ResolveReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['DISMISS', 'LINK'])
    note = serializers.CharField(max_length=2000)
    account_reference = serializers.CharField(max_length=20, required=False, allow_blank=True)


class ResolveReviewView(APIView):
    """POST /api/sales/stripe-review/<id>/resolve/ — dismiss, or link to a student as history only."""
    permission_classes = ADMIN_ONLY

    def post(self, request, pk):
        serializer = ResolveReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Choose how to resolve this item and explain why.')
        try:
            return Response(review.item_data(review.resolve(request.user, pk, serializer.validated_data, request)))
        except SalesError as exc:
            return _refused(exc)
