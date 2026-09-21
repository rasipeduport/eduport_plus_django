from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from .models import User

class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'role', 'is_active', 'is_staff', 'created_at')
    list_filter = ('role', 'is_active', 'is_staff', 'created_at')
    search_fields = ('email', 'full_name', 'mobile_number')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'mobile_number', 'avatar_url', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Lifecycle', {'fields': ('deactivated_at', 'deactivated_by', 'deactivation_reason')}),
        ('Metadata', {'fields': ('invited_by', 'created_at', 'updated_at')}),
    )
    readonly_fields = ('created_at', 'updated_at', 'deactivated_at', 'deactivated_by', 'deactivation_reason')

    def save_model(self, request, obj, form, change):
        # Keep the soft-deactivation lifecycle consistent when is_active is
        # toggled here: is_active=False must always carry a deactivated_at,
        # and re-enabling clears the deactivation record — the same invariant
        # the /api/users/<id>/status/ flow maintains. Without this, an admin
        # flipping is_active would leave a user who can't sign in but still
        # reads as active in the staff lists.
        if not obj.is_active and obj.deactivated_at is None:
            obj.deactivated_at = timezone.now()
            obj.deactivated_by = request.user if request.user.pk else None
            obj.deactivation_reason = 'Disabled via Django admin'
        elif obj.is_active and obj.deactivated_at is not None:
            obj.deactivated_at = None
            obj.deactivated_by = None
            obj.deactivation_reason = None
        super().save_model(request, obj, form, change)
        # Auto-create whitelist invitation for users created/saved via Django Admin
        try:
            from invitations.models import Invitation, InvitationStatusChoices
            if not Invitation.objects.filter(email=obj.email).exists():
                Invitation.objects.create(
                    email=obj.email,
                    role=obj.role,
                    status=InvitationStatusChoices.ACCEPTED,
                    invited_by=obj.invited_by or request.user,
                    extra_data={
                        "full_name": obj.full_name or "",
                        "mobile_number": obj.mobile_number or ""
                    }
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to auto-create whitelist invitation in Admin for {obj.email}: {e}")

admin.site.register(User, UserAdmin)
