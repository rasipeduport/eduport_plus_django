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
