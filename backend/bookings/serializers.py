from rest_framework import serializers

from .booking_service import REDEMO_REASON_MAX_LENGTH, REDEMO_REMARKS_MAX_LENGTH
from .leads import InvalidLeadDetails, custom_source_error, normalize_phone
from .models import (
    CUSTOM_SOURCE_MAX_LENGTH, MANUAL_CANCEL_REASONS, MANUAL_LEAD_SOURCES, BookingLink, BookingType, CancelReason,
    LeadSource, RedemoCloseReason, RescheduleReason,
)
from .notes import NOTE_MAX_LENGTH
from .public_serializers import CLASSES, SYLLABI
from .services import link_url
from .student_timezones import InvalidStudentTimezone
from .student_timezones import clean as clean_student_timezone


def known_timezone(value):
    """A student time zone staff pick: '' (not known) or an IANA zone the runtime knows."""
    if value and clean_student_timezone(value) != value:
        raise serializers.ValidationError(InvalidStudentTimezone.message)


def custom_source_field(**kwargs):
    """An Other source's own name: trimmed (DRF's default), so a blank or whitespace-only one reads ''."""
    return serializers.CharField(max_length=CUSTOM_SOURCE_MAX_LENGTH, required=False, allow_blank=True, **kwargs)


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


class CancelSerializer(serializers.Serializer):
    """POST /api/bookings/<type>/<id>/cancel/: why, as a code from the list (Q9), never free text (M1)."""
    # Not "Parent did not confirm": only recording the parent's answer cancels with that.
    reason = serializers.ChoiceField(choices=[(value, CancelReason(value).label) for value in MANUAL_CANCEL_REASONS])


class RescheduleSerializer(serializers.Serializer):
    """POST /api/bookings/<type>/<id>/reschedule/: the new slot's Indian date and time, and why (a code)."""
    date = serializers.DateField(input_formats=['%Y-%m-%d'])
    time = serializers.TimeField(input_formats=['%H:%M'])
    reason = serializers.ChoiceField(choices=RescheduleReason.choices)


class TutorAssignmentSerializer(serializers.Serializer):
    """Assigning a booking's tutor (bookings.management_views.BookingTutorView): the tutor's account id, nothing else."""
    tutor_id = serializers.UUIDField()


class LeadCreateSerializer(serializers.Serializer):
    """
    A lead an administrator adds by hand (bookings.lead_admin.add_lead), with
    the parent's email when known. Classes and syllabi are the booking pages'
    own, so every lead reads the same whichever way it arrived. No owner
    field: it is assigned afterwards (bookings.ownership).
    """
    parent_name = serializers.CharField(max_length=255)
    phone_dial_code = serializers.CharField(max_length=5)
    phone_number = serializers.CharField(max_length=30)
    student_name = serializers.CharField(max_length=255)
    grade = serializers.ChoiceField(choices=CLASSES)
    source = serializers.ChoiceField(choices=MANUAL_LEAD_SOURCES)
    # Required with Other ("Newspaper advertisement"), refused with any other source.
    custom_source = custom_source_field(default='')
    school_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    # The Diagnostic page offers every syllabus the Demo page does, and more.
    syllabus = serializers.ChoiceField(choices=SYLLABI[BookingType.DIAGNOSTIC], required=False, allow_blank=True, default='')
    country = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    # The student's time zone when known (bookings.student_timezones): '' or null for not known.
    student_timezone = serializers.CharField(
        max_length=64, required=False, allow_blank=True, allow_null=True, default='', validators=[known_timezone],
    )
    parent_email = serializers.EmailField(max_length=254, required=False, allow_blank=True, default='')

    def validate(self, data):
        errors = {}
        try:
            normalize_phone(data['phone_dial_code'], data['phone_number'])
        except InvalidLeadDetails as exc:
            errors[exc.field] = [exc.message]
        problem = custom_source_error(data['source'], data.get('custom_source', ''))
        if problem:
            errors['custom_source'] = [problem]
        if errors:
            raise serializers.ValidationError(errors)
        return data


class LeadDetailsUpdateSerializer(serializers.Serializer):
    """Admin corrections only: no defaults, ownership, status or workflow fields."""
    parent_name = serializers.CharField(max_length=255, required=False)
    phone_dial_code = serializers.CharField(max_length=5, required=False)
    phone_number = serializers.CharField(max_length=30, required=False)
    parent_email = serializers.EmailField(max_length=254, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    student_name = serializers.CharField(max_length=255, required=False)
    grade = serializers.ChoiceField(choices=CLASSES, required=False)
    school_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    syllabus = serializers.ChoiceField(choices=SYLLABI[BookingType.DIAGNOSTIC], required=False, allow_blank=True)
    source = serializers.ChoiceField(choices=LeadSource.choices, required=False)
    # An Other source's own name. With ``source`` it is checked here; alone it
    # renames the lead's current Other source (bookings.lead_admin.update_lead_details).
    custom_source = custom_source_field()

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: ['This field cannot be edited here.'] for field in sorted(unknown)})
        return values

    def validate(self, data):
        if 'source' in data:
            problem = custom_source_error(data['source'], data.get('custom_source', ''))
            if problem:
                raise serializers.ValidationError({'custom_source': [problem]})
        return data


class StudentTimezoneSerializer(serializers.Serializer):
    """
    Correcting a lead's student time zone (bookings.student_timezones.correct):
    an IANA zone the runtime knows, or null / '' to clear it.
    """
    student_timezone = serializers.CharField(
        max_length=64, allow_blank=True, allow_null=True, validators=[known_timezone],
    )


class LeadOwnerSerializer(serializers.Serializer):
    """Giving a lead to a BDE (bookings.lead_views.LeadOwnerView): who, and who the caller saw owning it (null: nobody)."""
    bde_id = serializers.UUIDField()
    current_owner_id = serializers.UUIDField(allow_null=True)


class RedemoRequestSerializer(serializers.Serializer):
    """
    Asking for a Re-Demo (bookings.booking_service.request_redemo): why, in
    staff's own words -- required, kept on the request only, never in a
    booking's history or the activity log.
    """
    reason = serializers.CharField(max_length=REDEMO_REASON_MAX_LENGTH)


class LeadNoteSerializer(serializers.Serializer):
    """A note on a lead (bookings.notes), in its writer's own words -- required."""
    body = serializers.CharField(max_length=NOTE_MAX_LENGTH)


class RedemoRemarksSerializer(serializers.Serializer):
    """The administrators' remarks for a Re-Demo's tutor (bookings.redemos.set_remarks); '' clears them."""
    remarks = serializers.CharField(max_length=REDEMO_REMARKS_MAX_LENGTH, allow_blank=True)


class RedemoScheduleSerializer(serializers.Serializer):
    """
    Scheduling a Re-Demo (booking_service.schedule_redemo): the tutor, the
    Demo slot's Indian date and time, and -- optionally -- the remarks for
    the tutor ('' clears them; left out, they stay as they are).
    """
    tutor_id = serializers.UUIDField()
    date = serializers.DateField(input_formats=['%Y-%m-%d'])
    time = serializers.TimeField(input_formats=['%H:%M'])
    remarks = serializers.CharField(max_length=REDEMO_REMARKS_MAX_LENGTH, allow_blank=True, required=False)
    # The slot's start as the picker showed it -- on the student's clock, an
    # instant all the same -- which must be the slot at ``date`` / ``time``.
    starts_at = serializers.DateTimeField(required=False)


class RedemoCloseSerializer(serializers.Serializer):
    """Closing a Re-Demo request (booking_service.close_redemo): why, a code from the list."""
    reason = serializers.ChoiceField(choices=RedemoCloseReason.choices)
