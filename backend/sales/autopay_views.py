from decimal import Decimal
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission
from . import autopay, payments
from .services import SalesError
from .views import _invalid, _refused


class InstallmentSerializer(serializers.Serializer):
    classes = serializers.DecimalField(max_digits=9, decimal_places=1, min_value=Decimal('0.5'))
    due_at = serializers.CharField(max_length=64)


class ScheduleSerializer(serializers.Serializer):
    quote_id = serializers.UUIDField()
    initial_classes = serializers.DecimalField(max_digits=9, decimal_places=1, min_value=Decimal('0.5'))
    installments = InstallmentSerializer(many=True, allow_empty=False, max_length=100)


class BeginSerializer(ScheduleSerializer):
    request_id = serializers.UUIDField()
    review_token = serializers.CharField(max_length=2048)


class AutopayScheduleView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def post(self, request, pk):
        serializer = ScheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the installment schedule.')
        try:
            return Response(autopay.preview(request.user, pk, serializer.validated_data, request))
        except SalesError as exc:
            return _refused(exc)


class BeginAutopayView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def post(self, request, pk):
        serializer = BeginSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Review the Autopay agreement.')
        try:
            autopay.begin(request.user, pk, serializer.validated_data, request)
            return Response(payments.sale_data(request.user, pk, request), status=201)
        except SalesError as exc:
            return _refused(exc)


class RestartInitialCheckoutView(APIView):
    permission_classes = [IsAuthenticated, HasAppPermission(payments.MANAGE)]

    def post(self, request, pk):
        serializer = serializers.UUIDField()
        try:
            request_id = serializer.run_validation(request.data.get('request_id'))
        except serializers.ValidationError:
            return Response({'error': 'INVALID_INPUT', 'message': 'A request UUID is required.'}, status=400)
        try:
            agreement = autopay.restart_initial(request.user, pk, request_id, request)
            return Response(payments.sale_data(request.user, agreement.purchase.sale.enquiry_id, request))
        except SalesError as exc:
            return _refused(exc)


class ParentAutopayActionView(APIView):
    # A short-lived signed bearer URL authorizes only this installment's parent action.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'autopay_action'

    def get(self, request, token):
        from .autopay_stripe import parent_action
        try:
            response = Response(parent_action(token))
        except SalesError as exc:
            response = _refused(exc)
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
