"""Additional purchases (sales.additional_purchases): a Mentor's further purchase for their own student."""
from decimal import Decimal

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission
from . import additional_purchases, payments
from .models import ChapterClassMode, PlanType
from .services import SalesError
from .views import _invalid, _refused

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
            return Response(additional_purchases.state(request.user, sale.pk, request), status=201)
        except SalesError as exc:
            return _refused(exc)


class PurchaseView(APIView):
    """GET /api/sales/purchases/<sale id>/ — one additional purchase: plan, totals, payments."""
    permission_classes = MENTOR_PURCHASES

    def get(self, request, pk):
        try:
            return Response(additional_purchases.state(request.user, pk, request))
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
            return Response(additional_purchases.amount(request.user, pk, serializer.validated_data, request))
        except SalesError as exc:
            return _refused(exc)


class LinkSerializer(ClassesSerializer):
    request_id = serializers.UUIDField()


class PurchasePaymentsView(APIView):
    """POST /api/sales/purchases/<sale id>/payments/ — a one-time Stripe Checkout link for this purchase."""
    permission_classes = MENTOR_PURCHASES

    def post(self, request, pk):
        serializer = LinkSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the payment.')
        try:
            payment = additional_purchases.collect(request.user, pk, serializer.validated_data, request)
            return Response({'payment': payments.payment_data(payment),
                             'state': additional_purchases.state(request.user, pk, request)}, status=201)
        except SalesError as exc:
            return _refused(exc)


class PurchaseExpireView(APIView):
    """POST /api/sales/purchases/<sale id>/payments/<payment id>/expire/ — expire an unpaid link."""
    permission_classes = MENTOR_PURCHASES

    def post(self, request, pk, payment_id):
        try:
            additional_purchases.expire(request.user, pk, payment_id, request)
            return Response(additional_purchases.state(request.user, pk, request))
        except SalesError as exc:
            return _refused(exc)
