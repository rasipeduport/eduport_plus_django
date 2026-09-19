from django.contrib import admin
from .models import ActivityLog

class ActivityLogAdmin(admin.ModelAdmin):
    """
    Read-only view of the audit log. The log is append-only (enforced by a DB
    trigger) and its single write path is activity.utils.log_activity — no
    human, superusers included, creates, edits, or deletes entries here.
    """
    list_display = ('action', 'entity_type', 'entity_label', 'actor_name', 'student_label', 'created_at')
    list_filter = ('entity_type', 'action', 'created_at', 'actor_role')
    search_fields = ('actor_name', 'actor_email', 'action', 'entity_type', 'entity_label')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {'fields': ('action', 'created_at')}),
        ('Actor Info', {'fields': ('actor', 'actor_name', 'actor_email', 'actor_role')}),
        ('Entity Details', {'fields': ('entity_type', 'entity_id', 'entity_label', 'student')}),
        ('Payloads', {'fields': ('changes', 'context')}),
    )

    @admin.display(description='Student')
    def student_label(self, obj):
        # The student FK carries no DB constraint (append-only log survives
        # deletions), so the row may dangle — never assume it resolves.
        try:
            return obj.student
        except Exception:
            return obj.student_id

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(ActivityLog, ActivityLogAdmin)
