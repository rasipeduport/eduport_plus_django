from rest_framework import serializers
from django.contrib.auth import get_user_model
from students.models import Student
from .team import effective_permissions

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    # Effective permissions (group + individual + those the role implies, see
    # accounts.team.holds_permission; superusers hold every one) as
    # "app_label.codename" strings, and the group names -- the SPAs base their
    # route and navigation guards on these, so they must mirror the backend.
    permissions = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'full_name',
            'avatar_url',
            'role',
            'mobile_number',
            'created_at',
            'last_login',
            'is_superuser',
            'must_change_password',
            'permissions',
            'groups',
        ]
        read_only_fields = [
            'id', 'username', 'email', 'role', 'created_at', 'last_login',
            'is_superuser', 'must_change_password',
        ]

    def get_permissions(self, obj):
        return effective_permissions(obj)

    def get_groups(self, obj):
        return list(obj.groups.values_list('name', flat=True))

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            'id',
            'student_code',
            'full_name',
            'mobile_number',
            'country',
            'state',
            'school_name',
            'grade',
            'syllabus',
            'admission_date',
            'total_class_quota',
            'meet_link',
            'status',
            # IANA zone the student's classes are scheduled in; Learn renders
            # every session time in it (null = caller falls back to IST).
            'timezone',
        ]
        read_only_fields = ['student_code', 'status']
