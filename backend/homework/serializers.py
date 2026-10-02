from rest_framework import serializers
from sessions.serializers import ProfileBriefSerializer, SessionFileSerializer, StudentBriefSerializer
from .models import Homework, HomeworkFile
from .services import can_view_submission


class HomeworkFileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = HomeworkFile
        fields = ['id', 'kind', 'file_name', 'content_type', 'size_bytes', 'created_at', 'url']

    def get_url(self, obj):
        path = obj.link_path()
        request = self.context.get('request')
        return request.build_absolute_uri(path) if request else path


class HomeworkSerializer(serializers.ModelSerializer):
    """
    The /homework page and the Learn detail. `assignment` is the session's
    homework content exactly as the sessions table shows it (the link column,
    plus the upload's metadata when it is a file); `submission` is the
    student's files, omitted for a mentor until the homework is scored.
    """
    session_id = serializers.PrimaryKeyRelatedField(source='session', read_only=True)
    session = serializers.SerializerMethodField()
    student_id = serializers.PrimaryKeyRelatedField(source='student', read_only=True)
    students = StudentBriefSerializer(source='student', read_only=True)
    tutor_profile = ProfileBriefSerializer(source='student.tutor', read_only=True)
    assigned_by_profile = ProfileBriefSerializer(source='assigned_by', read_only=True)
    scored_by_profile = ProfileBriefSerializer(source='scored_by', read_only=True)
    assignment = serializers.SerializerMethodField()
    submission = serializers.SerializerMethodField()
    submission_visible = serializers.SerializerMethodField()

    class Meta:
        model = Homework
        fields = [
            'id', 'session_id', 'session', 'student_id', 'students', 'tutor_profile', 'status',
            'assigned_by', 'assigned_by_profile', 'assigned_at', 'submitted_at',
            'scored_by', 'scored_by_profile', 'scored_at', 'score', 'max_score', 'feedback',
            'created_at', 'updated_at', 'assignment', 'submission', 'submission_visible',
        ]
        read_only_fields = fields

    def get_session(self, obj):
        s = obj.session
        return {
            'id': str(s.id),
            'title': s.title,
            'start_time': s.start_time.isoformat(),
            'end_time': s.end_time.isoformat(),
            'status': s.status.lower(),
        }

    def get_assignment(self, obj):
        session = obj.session
        link = session.homework_link or None
        upload = None
        for sf in session.files.all():
            if sf.field == 'homework' and sf.matches_link(link):
                upload = SessionFileSerializer(sf).data
                upload['url'] = link
                break
        return {'url': link, 'file': upload}

    def _user(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def get_submission_visible(self, obj):
        user = self._user()
        return bool(user) and can_view_submission(user, obj)

    def get_submission(self, obj):
        if not self.get_submission_visible(obj):
            return []
        return HomeworkFileSerializer(obj.files.all(), many=True, context=self.context).data

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if ret.get('status'):
            ret['status'] = ret['status'].lower()
        return ret
