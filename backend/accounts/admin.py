from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.utils import timezone
from activity.utils import log_activity
from .authz import acting_as, clear_individual_permissions, log_permissions_cleared
from .models import HUB_ROLES, RoleChoices, User
from .permission_catalogue import allowed_for_role
from .team import active_student_count, is_last_active_admin, staff_email_conflict, upcoming_booking_refusal

# Maintained by accounts.backends on every password check; editable here so an
# administrator can unlock an account by clearing both.
LOCKOUT_FIELDS = ('failed_login_count', 'locked_until')


def _audit_value(value):
    # ActivityLog.changes is plain JSON: datetimes go in as ISO strings.
    return value.isoformat() if hasattr(value, 'isoformat') else value


class StaffEmailRuleMixin:
    """
    A staff account's email (a Hub role: Admin, Mentor, Tutor, BDE, Sales TL) follows the Team
    API's rule, accounts.team.staff_email_conflict: unique whatever its letter
    case, and never an address that has a student invitation. Student accounts
    keep the plain model uniqueness, as before.
    """

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        if email and cleaned_data.get('role') in HUB_ROLES:
            # Until _post_clean() applies the form, the instance still holds the
            # saved address (a new account has none).
            conflict = staff_email_conflict(email, self.instance if self.instance.pk else None)
            if conflict:
                self.add_error('email', conflict)
        return cleaned_data


class RoleChangeRuleMixin:
    """
    A role changed here follows the Team API's rules (accounts.team): a mentor's
    or tutor's active students are handed over first, and the last active admin
    keeps the role. A tutor assigned upcoming Demo/Diagnostic bookings keeps
    both the role and the account active until those are reassigned.
    """

    def clean(self):
        cleaned_data = super().clean()
        account, new_role = self.instance, cleaned_data.get('role')
        # Until _post_clean() applies the form, the instance holds the saved role.
        role_changing = bool(account.pk and new_role and new_role != account.role)
        deactivating = bool(account.pk and account.is_active and cleaned_data.get('is_active') is False)
        if role_changing or deactivating:
            # The admin's change view runs in one transaction: holding the
            # account row (as Team and bookings.booking_service.assign_tutor
            # do) keeps a booking from being assigned before this saves.
            User.objects.select_for_update(no_key=True).filter(pk=account.pk).first()
        if role_changing:
            assigned = active_student_count(account)
            if assigned:
                self.add_error(
                    'role', f"Reassign this staff member's {assigned} active student(s) before changing their role."
                )
            elif is_last_active_admin(account):
                self.add_error('role', 'This is the last active administrator.')
            else:
                refusal = upcoming_booking_refusal(account, 'changing their role')
                if refusal:
                    self.add_error('role', refusal)
        if deactivating:
            refusal = upcoming_booking_refusal(account, 'deactivating')
            if refusal:
                self.add_error('is_active', refusal)
        return cleaned_data


class UserChangeAdminForm(RoleChangeRuleMixin, StaffEmailRuleMixin, UserChangeForm):
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
    # No group or permission pickers: group membership is never used (the
    # role's group applies through accounts.RoleGroup) and individual grants
    # are made in the Hub's Team page, which applies the catalogue's rules.
    filter_horizontal = ()

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'mobile_number', 'avatar_url', 'role')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'individual_permissions'),
            'description': '"Staff status" only grants access to this Django admin site. '
                           "Application access comes from the role and its role group; individual "
                           "permissions are granted in the Hub's Team page. Changing the role clears them.",
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
        'deactivation_reason', 'password_changed_at', 'individual_permissions',
    )

    @admin.display(description='Individual permissions')
    def individual_permissions(self, obj):
        names = sorted(f'{p.content_type.app_label}.{p.codename}' for p in obj.user_permissions.select_related('content_type'))
        return ', '.join(names) or '-'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Decision D1: a superuser holds every permission whatever the role, so
        # say so wherever the role would suggest otherwise.
        account = self.get_object(request, object_id)
        if request.method == 'GET' and account is not None and account.is_superuser and account.role != RoleChoices.ADMIN:
            messages.warning(
                request,
                f'This superuser has the {account.get_role_display()} role but holds every permission, as a '
                'superuser does. Give them the Admin role, or remove superuser status, so the role tells the truth.',
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        changed_data = getattr(form, 'changed_data', None) or ()
        role_changed = change and 'role' in changed_data
        # Grants made for the old role do not ride along. Cleared before the
        # save, inside the admin's transaction, so the request records it.
        cleared = clear_individual_permissions(obj) if role_changed else []
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
        if role_changed:
            log_activity(
                action='user.role_change',
                entity_type='profile',
                entity_id=str(obj.id),
                entity_label=obj.full_name or obj.username,
                changes={'role': {'old': form.initial.get('role'), 'new': obj.role}},
                context={'via': 'django_admin'},
                request=request,
            )
            if cleared:
                log_permissions_cleared(obj, cleared, via='django_admin', request=request)
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


def catalogue_permissions(role):
    """The Permission rows of the catalogue entries ``role`` may hold (none for no role)."""
    query = Q(pk__in=[])
    for name in allowed_for_role(role):
        app_label, codename = name.split('.', 1)
        query |= Q(content_type__app_label=app_label, codename=codename)
    return Permission.objects.filter(query).select_related('content_type')


# The role groups replace Django's own Group page.
admin.site.unregister(Group)


@admin.register(Group)
class RoleGroupAdmin(GroupAdmin):
    """
    The role groups (accounts.RoleGroup), configured by superusers. They are
    created by migration and linked to their role, so here they can be neither
    added, deleted nor renamed. Each offers only the catalogue permissions its
    role may hold, and every change is audited (accounts.signals).
    """
    list_display = ('name', 'role')
    fields = ('name', 'role', 'permissions')
    readonly_fields = ('name', 'role')

    @admin.display(description='Role')
    def role(self, obj):
        link = getattr(obj, 'role_link', None)
        return link.get_role_display() if link else 'None (grants nothing)'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'permissions' in form.base_fields:
            link = getattr(obj, 'role_link', None)
            form.base_fields['permissions'].queryset = catalogue_permissions(link.role if link else None)
        return form

    def save_related(self, request, form, formsets, change):
        with acting_as(request.user, 'django_admin'):
            super().save_related(request, form, formsets, change)
