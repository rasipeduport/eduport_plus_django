from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from students.models import Student
from .lifecycle import class_state, start_opens_at
from .models import Session, SessionContentField, SessionFile, SessionOutcomeReason
from .services import consumes_credit

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
        # Never the student's own meet_link: a class is joined in its tutor's
        # room (SessionSerializer.tutor_meet_link) and a chapter exam in its
        # mentor's (exams.serializers.ExamSerializer.mentor_meet_link).
        fields = ['student_code', 'full_name', 'mentor_profile', 'avatar_url']

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
    # Who started the class and when (its tutor, the student's mentor or an
    # administrator), and the tutor's completion their own notes made
    # (sessions.lifecycle), read only. A class marked attended by staff has no completion.
    started_by_profile = ProfileBriefSerializer(source='started_by', read_only=True)
    completed_by_profile = ProfileBriefSerializer(source='completed_by', read_only=True)
    # The class as booked, in hours (end_time - start_time): what it counts as, whenever it was completed.
    duration_hours = serializers.FloatField(read_only=True)
    # The first moment its tutor may start it (5 minutes before its scheduled start).
    start_opens_at = serializers.SerializerMethodField()
    # Where the class stands now (sessions.lifecycle.class_state), lowercase:
    # upcoming, in_progress, notes_due, not_started, completed, not_conducted, cancelled.
    class_state = serializers.SerializerMethodField()
    # The last moment its tutor's notes complete it without an approval (48 hours after its scheduled end).
    notes_due_by = serializers.SerializerMethodField()
    # The tutor's notes that came in after notes_due_by, and their review.
    late_notes_reviewed_by_profile = ProfileBriefSerializer(source='late_notes_reviewed_by', read_only=True)
    # No-show / Not Conducted as recorded, and an administrator's latest correction.
    outcome_recorded_by_profile = ProfileBriefSerializer(source='outcome_recorded_by', read_only=True)
    outcome_corrected_by_profile = ProfileBriefSerializer(source='outcome_corrected_by', read_only=True)
    # What a student is told about a class not conducted: no_show for their
    # own no-show, not_conducted for any other reason, null otherwise.
    outcome_kind = serializers.SerializerMethodField()
    # Whether its hours count against the student's quota (sessions.services.CREDIT_RETURNED).
    consumes_credit = serializers.SerializerMethodField()
    # Where the class is joined: the permanent Google Meet link of the tutor it
    # is assigned to (accounts.meet_links), as it is now, or null when that
    # tutor has none or no tutor is assigned. Never the student's link or
    # anyone else's. A change of tutor hands over the classes still to come,
    # and with them this link; started and past classes keep their tutor.
    tutor_meet_link = serializers.CharField(source='tutor.tutor_meet_link', read_only=True, default=None)

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
            'started_at',
            'started_by_profile',
            'completed_at',
            'completed_by_profile',
            'duration_hours',
            'start_opens_at',
            'tutor_meet_link',
            'class_state',
            'notes_due_by',
            'late_notes_status',
            'late_notes_submitted_at',
            'late_notes_reviewed_at',
            'late_notes_reviewed_by_profile',
            'outcome_kind',
            'outcome_reason',
            'outcome_note',
            'outcome_recorded_at',
            'outcome_recorded_by_profile',
            'outcome_corrected_at',
            'outcome_corrected_by_profile',
            'consumes_credit',
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'series_id', 'class_number', 'started_at', 'completed_at',
            'late_notes_status', 'late_notes_submitted_at', 'late_notes_reviewed_at',
            'outcome_reason', 'outcome_note', 'outcome_recorded_at', 'outcome_corrected_at',
        ]

    def get_start_opens_at(self, instance):
        return start_opens_at(instance).isoformat()

    def get_notes_due_by(self, instance):
        return instance.notes_due_by.isoformat()

    def get_class_state(self, instance):
        return class_state(instance, timezone.now()).lower()

    def get_outcome_kind(self, instance):
        if instance.outcome_reason is None:
            return None
        return 'no_show' if instance.outcome_reason == SessionOutcomeReason.STUDENT_NO_SHOW else 'not_conducted'

    def get_consumes_credit(self, instance):
        return consumes_credit(instance)

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


# What only staff read about a class: the outcome's reason, note and who
# recorded or corrected it, and the review of the tutor's late notes. A
# student is told only outcome_kind.
STAFF_ONLY_FIELDS = (
    'outcome_reason', 'outcome_note', 'outcome_recorded_by_profile', 'outcome_corrected_at',
    'outcome_corrected_by_profile', 'late_notes_status', 'late_notes_submitted_at', 'late_notes_reviewed_at',
    'late_notes_reviewed_by_profile',
)


def for_student(row):
    """A serialized session as a student may read it: without STAFF_ONLY_FIELDS."""
    return {key: value for key, value in row.items() if key not in STAFF_ONLY_FIELDS}
