from rest_framework import serializers
from students.models import Student
from .models import ActivityLog

class ActivityLogSerializer(serializers.ModelSerializer):
    # Read the raw FK columns, not the related objects: the log's FKs carry no
    # DB constraint (rows must survive actor/student deletion), so resolving
    # them could raise DoesNotExist on a dangling id.
    actor_id = serializers.UUIDField(read_only=True)
    student_id = serializers.UUIDField(read_only=True)
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            'id',
            'created_at',
            'actor_id',
            'actor_email',
            'actor_name',
            'actor_role',
            'action',
            'entity_type',
            'entity_id',
            'entity_label',
            'student_id',
            'student_name',
            'changes',
            'context'
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        try:
            return obj.student.full_name if obj.student_id else None
        except Student.DoesNotExist:
            return None
