from rest_framework import serializers

from .models import StudentNote


class StudentNoteSerializer(serializers.ModelSerializer):
    """
    One internal note as the profile's Notes tab renders it. The author is
    read from the snapshot columns, not the FK, so a note written by a staff
    member who has since been deleted still says who wrote it.
    """
    author_id = serializers.UUIDField(read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = StudentNote
        fields = [
            'id', 'body', 'author_id', 'author_name', 'author_role',
            'created_at', 'edited_at', 'can_edit', 'can_delete',
        ]
        read_only_fields = fields

    def _user(self):
        request = self.context.get('request')
        return getattr(request, 'user', None)

    def get_can_edit(self, obj):
        user = self._user()
        return bool(user) and obj.author_id == user.id

    def get_can_delete(self, obj):
        user = self._user()
        if not user:
            return False
        return obj.author_id == user.id or user.role == 'ADMIN' or user.is_superuser
