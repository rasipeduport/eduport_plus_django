from rest_framework import serializers

from .leads import InvalidLeadDetails, normalize_phone
from .models import MANUAL_LEAD_SOURCES, BookingLink, BookingType
from .public_serializers import CLASSES, SYLLABI
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


class TutorAssignmentSerializer(serializers.Serializer):
    """Assigning a booking's tutor (bookings.management_views.BookingTutorView): the tutor's account id, nothing else."""
    tutor_id = serializers.UUIDField()


class EnquiryCreateSerializer(serializers.Serializer):
    """
    An enquiry a BDE adds by hand (bookings.enquiries.add_enquiry). Classes and
    syllabi are the booking pages' own, so every lead reads the same whichever
    way it arrived. There is no owner field: the lead is always the caller's.
    """
    parent_name = serializers.CharField(max_length=255)
    phone_dial_code = serializers.CharField(max_length=5)
    phone_number = serializers.CharField(max_length=30)
    student_name = serializers.CharField(max_length=255)
    grade = serializers.ChoiceField(choices=CLASSES)
    source = serializers.ChoiceField(choices=MANUAL_LEAD_SOURCES)
    school_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    # The Diagnostic page offers every syllabus the Demo page does, and more.
    syllabus = serializers.ChoiceField(choices=SYLLABI[BookingType.DIAGNOSTIC], required=False, allow_blank=True, default='')
    country = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')

    def validate(self, data):
        try:
            normalize_phone(data['phone_dial_code'], data['phone_number'])
        except InvalidLeadDetails as exc:
            raise serializers.ValidationError({exc.field: [exc.message]})
        return data
