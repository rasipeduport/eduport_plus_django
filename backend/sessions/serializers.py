from rest_framework import serializers
from django.contrib.auth import get_user_model
from students.models import Student
from .models import Session, SessionContentField, SessionFile

User = get_user_model()

class ProfileBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'full_name', 'email']

class StudentBriefSerializer(serializers.ModelSerializer):
    mentor_profile = ProfileBriefSerializer(source='mentor', read_only=True)
    avatar_url = serializers.CharField(source='profile.avatar_url', read_only=True, default=None)

    class Meta:
        model = Student
        # meet_link is the student's Google Meet room (students.meet_link, the
        # same column the Students API and "Edit Demo Link" use). Nesting it
        # here lets the sessions table offer "Join Meet" without a second
        # endpoint; it reaches exactly the callers who can already see the row.
        fields = ['student_code', 'full_name', 'mentor_profile', 'avatar_url', 'meet_link']

class SessionFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionFile
        fields = ['id', 'field', 'file_name', 'content_type', 'size_bytes', 'created_at']


class SessionSerializer(serializers.ModelSerializer):
    student_id = serializers.PrimaryKeyRelatedField(
        source='student',
        queryset=Student.objects.all()
    )
    students = StudentBriefSerializer(source='student', read_only=True)
    tutor_profile = ProfileBriefSerializer(source='tutor', read_only=True)
    status = serializers.CharField()
    # Derived on the model from the three link columns (see Session.REQUIRED_CONTENT):
    # `status` stays the raw attendance fact; `display_status` is what the
    # tables label the row ('pending' = attended but material still missing).
    content_complete = serializers.BooleanField(read_only=True)
    missing_content = serializers.ListField(child=serializers.CharField(), read_only=True)
    display_status = serializers.CharField(read_only=True)
    # The upload (if any) behind each link: {notes|recording|homework: file or
    # null}. `url` is the link column itself, which the upload wrote.
    content_files = serializers.SerializerMethodField()
    # The homework lifecycle row behind the homework link (null until the
    # attended session has homework content): what the Homework badge and
    # the Learn tile read.
    homework = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            'id',
            'student_id',
            'students',
            'start_time',
            'end_time',
            'title',
            'created_at',
            'updated_at',
            'recording_link',
            'notes_link',
            'homework_link',
            'rating',
            'status',
            'cancellation_reason',
            'tutor',
            'tutor_profile',
            'series_id',
            'class_number',
            'content_complete',
            'missing_content',
            'display_status',
            'content_files',
            'homework',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'series_id', 'class_number']

    def get_homework(self, instance):
        hw = getattr(instance, 'homework', None)
        if hw is None:
            return None
        return {
            'id': str(hw.id),
            'status': hw.status.lower(),
            'score': hw.score,
            'max_score': hw.max_score,
            'submitted_at': hw.submitted_at.isoformat() if hw.submitted_at else None,
        }

    def get_content_files(self, instance):
        out = {name: None for name in SessionContentField.values}
        for sf in instance.files.all():
            data = SessionFileSerializer(sf).data
            data['url'] = getattr(instance, sf.link_field)
            out[sf.field] = data
        return out

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Standardise status value to lowercase for the frontend
        if 'status' in ret and ret['status']:
            ret['status'] = ret['status'].lower()
        return ret

    def to_internal_value(self, data):
        # Support case-insensitive status inputs mapping to uppercase DB constants
        if 'status' in data and isinstance(data['status'], str):
            data = data.copy()
            data['status'] = data['status'].upper()
        return super().to_internal_value(data)
