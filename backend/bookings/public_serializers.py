import unicodedata

from rest_framework import serializers

from .leads import InvalidLeadDetails, normalize_phone
from .models import PUBLIC_FORM_SOURCES, BookingType

# What the public booking pages offer (eduport-plus app/demo and app/exam).
CLASSES = [f'Class {grade}' for grade in range(5, 11)]
SYLLABI = {
    BookingType.DEMO: ['CBSE'],
    BookingType.DIAGNOSTIC: ['CBSE', 'IB', 'IGCSE', 'ICSE', 'Others'],
}
# The lead forms' classes: the landing page's form still offers 1st to 4th
# (the marketing server sends them as "Class 1" ... "Class 10").
LEAD_FORM_CLASSES = [f'Class {grade}' for grade in range(1, 11)]


class PhoneSerializer(serializers.Serializer):
    dial_code = serializers.CharField(max_length=5)
    number = serializers.CharField(max_length=30)


class BookingRequestSerializer(serializers.Serializer):
    """
    A booking as the marketing server sends it. There is no BDE field: the
    view reads only the ``ref`` token for attribution, and unknown fields
    (a forged ``bde_id``, say) are dropped.
    """
    date = serializers.DateField(input_formats=['%Y-%m-%d'])
    time = serializers.TimeField(input_formats=['%H:%M'])
    parent_name = serializers.CharField(max_length=255)
    phone = PhoneSerializer()
    student_name = serializers.CharField(max_length=255)
    school = serializers.CharField(max_length=255)
    student_class = serializers.ChoiceField(choices=CLASSES)
    syllabus = serializers.CharField(max_length=100)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    # The slot as the parent saw it, in their own time zone.
    display_time = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['syllabus'] not in SYLLABI[self.context['booking_type']]:
            raise serializers.ValidationError({'syllabus': ['This syllabus is not offered for this booking.']})
        try:
            normalize_phone(data['phone']['dial_code'], data['phone']['number'])
        except InvalidLeadDetails as exc:
            raise serializers.ValidationError({exc.field: [exc.message]})
        return data


def plain_text(value):
    """Refuse control characters (a typed name or a campaign tag never has one)."""
    if any(unicodedata.category(char) == 'Cc' for char in value):
        raise serializers.ValidationError('Use letters, digits and punctuation only.')


def _text(max_length, **kwargs):
    return serializers.CharField(max_length=max_length, validators=[plain_text], **kwargs)


class UtmSerializer(serializers.Serializer):
    """The utm_* parameters of the page the form was on, each optional (bookings.lead_intake.UTM_FIELDS)."""
    utm_source = _text(200, required=False, allow_blank=True, default='')
    utm_medium = _text(200, required=False, allow_blank=True, default='')
    utm_campaign = _text(200, required=False, allow_blank=True, default='')
    utm_content = _text(200, required=False, allow_blank=True, default='')
    utm_term = _text(200, required=False, allow_blank=True, default='')


class LeadFormSerializer(serializers.Serializer):
    """
    A lead form's submission as the marketing server sends it: the main
    website's demo form (WEBSITE) or the landing page's (LANDING_PAGE), the
    fields both forms require. There is no owner or BDE field -- a form's lead
    is nobody's until an administrator assigns it -- and unknown fields are
    dropped. Text is trimmed (DRF) and may hold no control character.
    """
    source = serializers.ChoiceField(choices=PUBLIC_FORM_SOURCES)
    parent_name = _text(255)
    phone = PhoneSerializer()
    student_name = _text(255)
    school = _text(255)
    grade = serializers.ChoiceField(choices=LEAD_FORM_CLASSES)
    syllabus = serializers.ChoiceField(choices=SYLLABI[BookingType.DIAGNOSTIC])
    country = _text(100, required=False, allow_blank=True, default='')
    utm = UtmSerializer(required=False)

    def validate(self, data):
        try:
            normalize_phone(data['phone']['dial_code'], data['phone']['number'])
        except InvalidLeadDetails as exc:
            raise serializers.ValidationError({exc.field: [exc.message]})
        return data
