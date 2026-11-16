from rest_framework import serializers
from django.contrib.auth import get_user_model
from students.models import Student
from .authz import effective_permissions

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    # Effective catalogue permissions (the role's group + individual grants,
    # within the role's ceiling; superusers hold every one -- accounts.authz),
    # as sorted "app_label.codename" strings. The Hub bases its navigation,
    # route guards and in-page actions on these, so they mirror the backend
    # exactly; the API enforces the same permissions on every request. `groups` stays for compatibility and is always empty:
    # membership is refused (accounts.signals).
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
        return sorted(effective_permissions(obj, self.context.get('request')))

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
