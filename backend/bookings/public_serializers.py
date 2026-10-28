from rest_framework import serializers

from .leads import InvalidLeadDetails, normalize_phone
from .models import BookingType

# What the public booking pages offer (eduport-plus app/demo and app/exam).
CLASSES = [f'Class {grade}' for grade in range(5, 11)]
SYLLABI = {
    BookingType.DEMO: ['CBSE'],
    BookingType.DIAGNOSTIC: ['CBSE', 'IB', 'IGCSE', 'ICSE', 'Others'],
}


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
