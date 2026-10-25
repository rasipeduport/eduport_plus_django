from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.utils import timezone
from activity.utils import log_activity
from core.permissions import STAFF_ROLES
from .models import User
from .team import staff_email_conflict

# Maintained by accounts.backends on every password check; editable here so an
# administrator can unlock an account by clearing both.
LOCKOUT_FIELDS = ('failed_login_count', 'locked_until')


def _audit_value(value):
    # ActivityLog.changes is plain JSON: datetimes go in as ISO strings.
    return value.isoformat() if hasattr(value, 'isoformat') else value


class StaffEmailRuleMixin:
    """
    A staff account's email (role Admin, Mentor or Tutor) follows the Team
    API's rule, accounts.team.staff_email_conflict: unique whatever its letter
    case, and never an address that has a student invitation. Student accounts
    keep the plain model uniqueness, as before.
    """

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        if email and cleaned_data.get('role') in STAFF_ROLES:
            # Until _post_clean() applies the form, the instance still holds the
            # saved address (a new account has none).
            conflict = staff_email_conflict(email, self.instance if self.instance.pk else None)
            if conflict:
                self.add_error('email', conflict)
        return cleaned_data


class UserChangeAdminForm(StaffEmailRuleMixin, UserChangeForm):
    """
    Django's own change form: `password` is the read-only hash summary with a
    link to the set-password page, never a text input. (A plain ModelAdmin
    rendered it as text and saved whatever was typed, unhashed.)
    """

    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'


class UserCreationAdminForm(StaffEmailRuleMixin, AdminUserCreationForm):
    """Django's admin creation form (hashed password, validators) for this model."""

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'full_name', 'role')


class UserAdmin(BaseUserAdmin):
    form = UserChangeAdminForm
    add_form = UserCreationAdminForm

    list_display = ('username', 'email', 'full_name', 'role', 'is_active', 'is_staff', 'created_at')
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'must_change_password', 'created_at')
    search_fields = ('username', 'email', 'full_name', 'mobile_number')
    ordering = ('-created_at',)
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'mobile_number', 'avatar_url', 'role')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'description': '"Staff status" only grants access to this Django admin site. '
                           'Application access comes from the role.',
        }),
        ('Lifecycle', {'fields': ('deactivated_at', 'deactivated_by', 'deactivation_reason',
                                  'must_change_password', 'password_changed_at')}),
        ('Sign-in lockout', {
            'fields': LOCKOUT_FIELDS,
            'description': 'Set automatically after repeated wrong passwords. '
                           'Clear both fields to unlock the account.',
        }),
        ('Metadata', {'fields': ('invited_by', 'last_login', 'created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'full_name', 'role', 'usable_password', 'password1', 'password2'),
        }),
    )
    readonly_fields = (
        'created_at', 'updated_at', 'last_login', 'deactivated_at', 'deactivated_by',
        'deactivation_reason', 'password_changed_at',
    )

    def save_model(self, request, obj, form, change):
        # A password typed by an administrator for a new account is a
        # temporary one: the user must replace it at first sign-in.
        if not change and obj.has_usable_password():
            obj.must_change_password = True
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
        changed_data = getattr(form, 'changed_data', None) or ()
        lockout_changes = {
            field: {'old': _audit_value(form.initial.get(field)), 'new': _audit_value(getattr(obj, field))}
            for field in LOCKOUT_FIELDS
            if change and field in changed_data
        }
        super().save_model(request, obj, form, change)
        if lockout_changes:
            unlocked = not obj.locked_until and not obj.failed_login_count
            log_activity(
                action='user.unlock' if unlocked else 'user.lockout_update',
                entity_type='profile',
                entity_id=str(obj.id),
                entity_label=obj.full_name or obj.username,
                changes=lockout_changes,
                context={'via': 'django_admin'},
                request=request,
            )
        # Auto-create whitelist invitation for student accounts created/saved via
        # Django Admin, so they can sign in to Learn with Google. Staff never sign
        # in with Google and are no longer invited, so they get none.
        try:
            from invitations.models import Invitation, InvitationRoleChoices, InvitationStatusChoices
            if obj.role == InvitationRoleChoices.STUDENT and not Invitation.objects.filter(email=obj.email).exists():
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
