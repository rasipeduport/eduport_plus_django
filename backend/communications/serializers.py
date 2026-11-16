from rest_framework import serializers


class ParentAnswerSerializer(serializers.Serializer):
    """
    POST /api/communications/bookings/<type>/<id>/parent-confirmation/: the
    parent's answer as sent. Only its shape is read here; what may be recorded
    -- an outcome from the list, a reason for Not Confirmed, the cancellation
    agreed to -- is booking_service.record_parent_confirmation's to decide.
    """
    outcome = serializers.CharField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    confirm_cancellation = serializers.BooleanField(required=False, default=False)
