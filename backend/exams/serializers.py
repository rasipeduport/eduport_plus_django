from rest_framework import serializers
from sessions.serializers import ProfileBriefSerializer, StudentBriefSerializer
from .models import Exam, ExamFile, AdditionalExam, AdditionalExamFile, ExamFileKind


class _FileSerializer(serializers.ModelSerializer):
    """Common shape for both file tables; ``url`` is the authenticated download view."""
    url = serializers.SerializerMethodField()

    def get_url(self, obj):
        path = obj.link_path()
        request = self.context.get('request')
        return request.build_absolute_uri(path) if request else path


class ExamFileSerializer(_FileSerializer):
    class Meta:
        model = ExamFile
        fields = ['id', 'kind', 'file_name', 'content_type', 'size_bytes', 'created_at', 'url']


class AdditionalExamFileSerializer(_FileSerializer):
    class Meta:
        model = AdditionalExamFile
        fields = ['id', 'kind', 'file_name', 'content_type', 'size_bytes', 'created_at', 'url']


class ExamSerializer(serializers.ModelSerializer):
    student_id = serializers.PrimaryKeyRelatedField(source='student', read_only=True)
    students = StudentBriefSerializer(source='student', read_only=True)
    mentor_profile = ProfileBriefSerializer(source='mentor', read_only=True)
    files = ExamFileSerializer(many=True, read_only=True)
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id', 'student_id', 'students', 'mentor', 'mentor_profile', 'type', 'chapter_name',
            'start_time', 'end_time', 'status', 'score', 'max_score', 'recording_link',
            'cancellation_reason', 'created_at', 'updated_at', 'files', 'file_count',
        ]
        read_only_fields = fields

    def get_file_count(self, obj):
        return len(obj.files.all())

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Lowercase on the wire, uppercase in the database (sessions convention).
        for key in ('status', 'type'):
            if ret.get(key):
                ret[key] = ret[key].lower()
        return ret


class AdditionalExamSerializer(serializers.ModelSerializer):
    student_id = serializers.PrimaryKeyRelatedField(source='student', read_only=True)
    students = StudentBriefSerializer(source='student', read_only=True)
    mentor_profile = ProfileBriefSerializer(source='mentor', read_only=True)
    scored_by_profile = ProfileBriefSerializer(source='scored_by', read_only=True)
    question_paper = serializers.SerializerMethodField()
    answer_sheet = serializers.SerializerMethodField()

    class Meta:
        model = AdditionalExam
        fields = [
            'id', 'student_id', 'students', 'mentor', 'mentor_profile', 'title', 'status',
            'submitted_at', 'scored_by', 'scored_by_profile', 'scored_at', 'score', 'max_score',
            'feedback', 'created_at', 'updated_at', 'question_paper', 'answer_sheet',
        ]
        read_only_fields = fields

    def _files(self, obj, kind):
        rows = [f for f in obj.files.all() if f.kind == kind]
        return AdditionalExamFileSerializer(rows, many=True, context=self.context).data

    def get_question_paper(self, obj):
        return self._files(obj, ExamFileKind.QUESTION_PAPER)

    def get_answer_sheet(self, obj):
        return self._files(obj, ExamFileKind.ANSWER_SHEET)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if ret.get('status'):
            ret['status'] = ret['status'].lower()
        return ret
