from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authz import has_app_permission
from core.permissions import HasAppPermission
from . import payments, quotes
from .payment_models import CollectionMode, Payment, PaymentMethod, Sale, SaleKind
from .services import SalesError
from .views import _invalid, _refused


class SaleSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SaleKind.choices)
    expected_start_date = serializers.DateField(required=False)


class AllocationSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=['TOKEN', 'TUITION'])
    collection_mode = serializers.ChoiceField(choices=CollectionMode.choices, default='FULL')
    classes = serializers.DecimalField(max_digits=9, decimal_places=1, min_value=0, default=0)

    def validate(self, data):
        if data['purpose'] == 'TOKEN' and (data['classes'] != 0 or data['collection_mode'] != 'FULL'):
            raise serializers.ValidationError('A token is AED 100, covers no classes, and is paid in full.')
        return data


class PaymentSerializer(AllocationSerializer):
    request_id = serializers.UUIDField()
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    amount = serializers.DecimalField(max_digits=15, decimal_places=0, min_value=1, required=False)
    payment_date = serializers.DateField(default=timezone.localdate)
    proof = serializers.FileField(required=False)
    received_confirmed = serializers.BooleanField(default=False)
    transaction_reference = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_payment_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('A received payment cannot be dated in the future.')
        return value


class InitialSalesView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def get(self, request, pk):
        try:
            return Response(payments.sale_data(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)

    def post(self, request, pk):
        serializer = SaleSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the sale details.')
        try:
            payments.start_sale(request.user, pk, serializer.validated_data, request)
            return Response(payments.sale_data(request.user, pk, request), status=201)
        except SalesError as exc:
            return _refused(exc)


class CollectionAmountView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def get(self, request, pk):
        serializer = AllocationSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the class allocation.')
        try:
            return Response(payments.preview_collection(request.user, pk, serializer.validated_data, request))
        except SalesError as exc:
            return _refused(exc)


class CollectPaymentView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, pk):
        serializer = PaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the payment details.')
        try:
            payment = payments.collect(request.user, pk, serializer.validated_data, request)
            return Response({'payment': payments.payment_data(payment), 'state': payments.sale_data(request.user, pk, request)}, status=201)
        except SalesError as exc:
            return _refused(exc)


class CollectionReplacementSerializer(serializers.Serializer):
    quote_id = serializers.UUIDField()
    collection_mode = serializers.ChoiceField(choices=['FULL', 'PARTIAL', 'AUTOPAY'])


class InstallmentQuoteView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE), HasAppPermission(quotes.CREATE_QUOTES)]

    def get(self, request, pk):
        serializer = CollectionReplacementSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _invalid(serializer, 'Choose the quote and replacement collection intention.')
        try:
            return Response(payments.preview_collection_replacement(request.user, pk, serializer.validated_data['quote_id'], serializer.validated_data['collection_mode'], request))
        except SalesError as exc:
            return _refused(exc)

    def post(self, request, pk):
        serializer = CollectionReplacementSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Choose the quote and replacement collection intention.')
        try:
            quote = payments.installment_replacement(request.user, pk, serializer.validated_data['quote_id'],
                                                   serializer.validated_data['collection_mode'], request)
            return Response(quotes.quote_data(quote), status=201)
        except SalesError as exc:
            return _refused(exc)


class PaymentProofView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def get(self, request, pk):
        payment = Payment.objects.select_related('sale').filter(pk=pk).first()
        if payment is None or not payment.proof:
            return Response({'error': 'NOT_FOUND'}, status=404)
        try:
            payments.accessible_lead(request.user, payment.sale.enquiry_id, request)
            if payment.recorded_by_id != request.user.pk and not has_app_permission(request.user, 'accounts.manage_sales_quotes', request):
                return Response({'error': 'NOT_FOUND'}, status=404)
            handle = payment.proof.open('rb')
        except SalesError as exc:
            return _refused(exc)
        except FileNotFoundError:
            return Response({'error': 'NOT_FOUND'}, status=404)
        response = FileResponse(handle, as_attachment=True, filename=payment.proof_name, content_type=payment.proof_content_type)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class ExpirePaymentView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def post(self, request, pk):
        from .stripe_gateway import expire_checkout
        try:
            return Response(payments.payment_data(expire_checkout(request.user, pk, request)))
        except SalesError as exc:
            return _refused(exc)


class InitialStudentSaleView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE), HasAppPermission('accounts.view_all_students')]

    def get(self, request, pk):
        sale = Sale.objects.filter(student_id=pk).first()
        if not sale:
            return Response({'error': 'NOT_FOUND'}, status=404)
        try:
            return Response(payments.sale_data(request.user, sale.enquiry_id, request))
        except SalesError as exc:
            return _refused(exc)


class StripeWebhookView(APIView):
    # External provider endpoint: authenticity comes only from the raw-body signature.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from .stripe_gateway import process_event, verify_payload
        try:
            event = verify_payload(request.body, request.headers.get('Stripe-Signature', ''))
            result = process_event(event)
            return Response({'outcome': result.outcome}, status=400 if result.outcome == 'REJECTED' else 200)
        except SalesError as exc:
            return _refused(exc)
