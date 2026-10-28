from rest_framework import serializers

from .models import BookingLink
from .services import link_url


class BookingLinkSerializer(serializers.ModelSerializer):
    # The token travels only inside the URL; the row's id and owner are not
    # part of what the workspace needs.
    url = serializers.SerializerMethodField()

    class Meta:
        model = BookingLink
        fields = ['booking_type', 'url', 'created_at']

    def get_url(self, obj):
        return link_url(obj)


class SlotChangeSerializer(serializers.Serializer):
    """Closing or reopening some of one date's slots (bookings.views.BookingSlotsView)."""
    action = serializers.ChoiceField(choices=['close', 'reopen'])
    # Start times in Indian time; one date holds at most 24 hourly slots.
    times = serializers.ListField(child=serializers.TimeField(input_formats=['%H:%M']), allow_empty=False, max_length=24)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
