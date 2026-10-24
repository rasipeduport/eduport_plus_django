"""
Team Management API: the staff accounts (Admin, Mentor, Tutor) that
administrators create and look after. Mounted at /api/team/ (team_urls.py).

The rules, enforced here whatever the client sends:

* Team managers are active users with the ADMIN role, and superusers -- the
  people core.permissions.IsAdminUser admits. Staff holding the approved
  ``accounts.view_team`` permission may read the directory, nothing more.
* Only staff accounts are targets. A student's id is not found, and no endpoint
  creates a student or gives anyone the STUDENT role.
* Nobody changes their own account here; a password is changed through
  /api/auth/change-password/.
* Admin-role, superuser and Django-admin (is_staff) accounts are managed by
  superusers only, and only a superuser gives anyone the ADMIN role.
* The last active admin cannot be deactivated or demoted.
* Each endpoint accepts a fixed set of fields, so is_superuser, is_staff,
  groups and arbitrary permissions can never be set through it. Unknown fields
  are refused rather than ignored.
* Permissions come only from ASSIGNABLE_PERMISSIONS, and only someone who holds
  a permission may grant or revoke it.
* Temporary passwords are typed by the administrator, checked against
  AUTH_PASSWORD_VALIDATORS, and never returned, logged or audited. The account
  must replace the password before using the app (accounts.middleware).
* Team writes run one at a time (lock_team_changes), so the uniqueness and
  last-admin checks cannot race each other.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from activity.utils import log_activity
from core.pagination import paginate_queryset
from core.permissions import STAFF_ROLES
from invitations.models import Invitation, InvitationRoleChoices
from students.models import Student

from .models import USERNAME_MAX_LENGTH, RoleChoices, normalize_username

User = get_user_model()

VIEW_TEAM = 'accounts.view_team'

# The approved, assignable permissions, keyed "app_label.codename". One is
# added here only together with the code that enforces it. Every admin holds
# the ``admin_grantable`` ones through the role, and so may grant them; the
# others are held only by superusers and by explicit grants.
ASSIGNABLE_PERMISSIONS = {
    VIEW_TEAM: {
        'label': 'View the team directory',
        'module': 'Team',
        'admin_grantable': True,
    },
}

# Advisory-lock class for Team writes (sessions.services uses 1 and 2).
_LOCK_CLASS_TEAM = 3


class TeamError(Exception):
    """A refusal, answered in the project's {"error", "message"} shape."""

    def __init__(self, code, message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra

    def response(self):
        return Response({"error": self.code, "message": self.message, **self.extra}, status=self.http_status)


def _forbidden(code, message):
    return TeamError(code, message, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------- who may act

def is_team_manager(user):
    return bool(
        user and user.is_authenticated and user.is_active
        and (user.role == RoleChoices.ADMIN or user.is_superuser)
    )


def holds_permission(user, perm):
    """
    Whether ``user`` holds approved permission ``perm`` -- and so may grant or
    revoke it. Superusers hold every one, admins every admin-grantable one,
    anyone else only what was granted to them.
    """
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    entry = ASSIGNABLE_PERMISSIONS.get(perm)
    if entry and entry['admin_grantable'] and user.role == RoleChoices.ADMIN:
        return True
    return user.has_perm(perm)


def effective_permissions(user):
    """
    Everything ``user`` holds, as "app_label.codename" strings: Django's own
    grants plus the approved permissions the role implies. /api/auth/me
    reports this, so the SPAs' guards mirror holds_permission().
    """
    held = set(user.get_all_permissions())
    held.update(perm for perm in ASSIGNABLE_PERMISSIONS if holds_permission(user, perm))
    return sorted(held)


class IsTeamManager(BasePermission):
    def has_permission(self, request, view):
        return is_team_manager(request.user)


class TeamAccess(BasePermission):
    """Team managers may do everything; staff holding view_team may read."""

    def has_permission(self, request, view):
        user = request.user
        if is_team_manager(user):
            return True
        return (
            request.method in SAFE_METHODS
            and user.is_authenticated
            and user.role in STAFF_ROLES
            and user.has_perm(VIEW_TEAM)
        )


def check_may_change(actor, account):
    """Refuse changes to oneself, and to accounts beyond a plain admin's reach."""
    if account.pk == actor.pk:
        raise _forbidden('SELF_CHANGE_FORBIDDEN', 'You cannot change your own account here.')
    if not actor.is_superuser and (
        account.role == RoleChoices.ADMIN or account.is_superuser or account.is_staff
    ):
        raise _forbidden('SUPERUSER_REQUIRED', 'Only a superuser can change an administrator account.')


def check_may_assign_role(actor, role):
    if role == RoleChoices.ADMIN and not actor.is_superuser:
        raise _forbidden('SUPERUSER_REQUIRED', 'Only a superuser can give someone the Admin role.')


def check_not_last_admin(account):
    """Refuse to deactivate or demote the last active admin."""
    if account.role != RoleChoices.ADMIN or not account.is_active:
        return
    others = User.objects.filter(
        role=RoleChoices.ADMIN, is_active=True, deactivated_at__isnull=True
    ).exclude(pk=account.pk)
    if not others.exists():
        raise TeamError('LAST_ADMIN', 'This is the last active administrator.', status.HTTP_409_CONFLICT)


# ------------------------------------------------------------- shared helpers

def lock_team_changes():
    """
    Serialise Team API writes for the rest of the current transaction, so a
    uniqueness or last-admin check cannot race another write. Must be called
    inside transaction.atomic(); a no-op off PostgreSQL.
    """
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [_LOCK_CLASS_TEAM, 'team'])


def staff_accounts():
    return User.objects.filter(role__in=STAFF_ROLES)


def locked_staff_account(pk):
    """Staff account ``pk`` with its row locked for the transaction, else 404."""
    account = staff_accounts().select_for_update(no_key=True).filter(pk=pk).first()
    if account is None:
        raise TeamError('NOT_FOUND', 'Staff account not found.', status.HTTP_404_NOT_FOUND)
    return account


def active_student_count(account):
    """ACTIVE students still assigned to ``account`` as mentor or tutor."""
    return Student.objects.filter(status='ACTIVE').filter(Q(mentor=account) | Q(tutor=account)).count()


def set_account_active(account, active, actor=None, reason=None):
    """
    Deactivate or reactivate ``account``; the caller holds its row lock and has
    applied its own guards. ``is_active`` mirrors ``deactivated_at``, so a
    deactivated account's existing sessions stop working on their next request.
    Shared with StaffStatusView.
    """
    account.deactivated_at = None if active else timezone.now()
    account.deactivated_by = None if active else actor
    account.deactivation_reason = None if active else reason
    account.is_active = active
    account.save(update_fields=['deactivated_at', 'deactivated_by', 'deactivation_reason', 'is_active', 'updated_at'])


def log_status_change(request, account, active, was_deactivated, reason):
    log_activity(
        action='user.reactivate' if active else 'user.deactivate',
        entity_type='profile',
        entity_id=str(account.id),
        entity_label=account.full_name or account.email,
        changes={
            "status": {
                "old": "deactivated" if was_deactivated else "active",
                "new": "active" if active else "deactivated",
            }
        },
        context={"reason": reason},
        request=request,
    )


def granted_permissions(account):
    """Approved permissions granted to ``account`` directly (not via the role)."""
    names = {f'{perm.content_type.app_label}.{perm.codename}' for perm in account.user_permissions.all()}
    return sorted(names & ASSIGNABLE_PERMISSIONS.keys())


def _iso(value):
    return value.isoformat() if value else None


def member_payload(account, full=True):
    """
    A staff account as the Team API returns it. Never carries the password
    hash; ``full`` adds the fields only team managers see.
    """
    data = {
        "id": str(account.id),
        "username": account.username,
        "email": account.email,
        "full_name": account.full_name or "",
        "mobile_number": account.mobile_number or "",
        "role": account.role,
        "is_active": account.is_active,
        "deactivated_at": _iso(account.deactivated_at),
        "created_at": _iso(account.created_at),
    }
    if full:
        locked = account.locked_until if account.locked_until and account.locked_until > timezone.now() else None
        data.update({
            "is_superuser": account.is_superuser,
            "deactivation_reason": account.deactivation_reason,
            "must_change_password": account.must_change_password,
            "has_password": account.has_usable_password(),
            "locked_until": _iso(locked),
            "last_login": _iso(account.last_login),
            "invited_by": {
                "id": str(account.invited_by.id),
                "full_name": account.invited_by.full_name or "",
                "email": account.invited_by.email,
            } if account.invited_by_id else None,
            "permissions": granted_permissions(account),
        })
    return data


# ------------------------------------------------------------- input checking

def request_fields(request, allowed, required=()):
    """The JSON body, refusing fields this endpoint does not accept."""
    data = request.data
    if not isinstance(data, dict):
        raise TeamError('INVALID_INPUT', 'Expected a JSON object.')
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise TeamError('UNKNOWN_FIELDS', f"These fields cannot be set here: {', '.join(unknown)}.", fields=unknown)
    missing = [name for name in required if data.get(name) in (None, '')]
    if missing:
        raise TeamError('INVALID_INPUT', f"Required: {', '.join(missing)}.", fields=missing)
    return data


def clean_username(value, account=None):
    if not isinstance(value, str) or not normalize_username(value):
        raise TeamError('INVALID_INPUT', 'username is required.')
    username = normalize_username(value)
    if len(username) > USERNAME_MAX_LENGTH:
        raise TeamError('INVALID_INPUT', f'username must be {USERNAME_MAX_LENGTH} characters or fewer.')
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError:
        raise TeamError('INVALID_INPUT', 'username may contain only letters, digits and @/./+/-/_.')
    taken = User.objects.filter(username=username)
    if account is not None:
        taken = taken.exclude(pk=account.pk)
    if taken.exists():
        raise TeamError('USERNAME_TAKEN', 'That username is already in use.')
    return username


def staff_email_conflict(email, account=None):
    """
    Why ``email`` may not become a staff account's address, or None when it
    may. The one rule for a staff email, shared by this API (clean_email) and
    the Django admin's user forms. ``account`` is the account being edited.

    Sign-in, sessions and permissions never use a staff email (staff sign in by
    username), so it may change as long as it stays unique whatever its letter
    case, and clear of student invitations.
    """
    # The account's own address, perhaps in other letter case, is no conflict.
    if account is not None and email.lower() == (account.email or '').lower():
        return None
    if User.objects.filter(email__iexact=email).exists():
        return 'That email already belongs to an account.'
    # A student invitation is redeemed by Google sign-in, which finds the
    # account by its email and refuses staff accounts. A staff account holding
    # an email with a student invitation -- a parent's, whatever its status --
    # would block that invitation for good, so it must never be created. Staff
    # invitations are retired and never redeemed, so one left over from before
    # does not block: it is left as it is, and Team creates the account.
    if Invitation.objects.filter(email__iexact=email, role=InvitationRoleChoices.STUDENT).exists():
        return 'That email has a student invitation. Withdraw the invitation first.'
    return None


def clean_email(value, account=None):
    """A new or changed staff email, checked by staff_email_conflict."""
    if not isinstance(value, str) or not value.strip():
        raise TeamError('INVALID_INPUT', 'email is required.', fields=['email'])
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise TeamError('INVALID_INPUT', 'Enter a valid email address.', fields=['email'])
    if len(email) > 254:
        raise TeamError('INVALID_INPUT', 'email must be 254 characters or fewer.', fields=['email'])
    conflict = staff_email_conflict(email, account)
    if conflict:
        raise TeamError('EMAIL_IN_USE', conflict)
    return email


def clean_full_name(value):
    if not isinstance(value, str) or not value.strip():
        raise TeamError('INVALID_INPUT', 'full_name is required.')
    if len(value.strip()) > 255:
        raise TeamError('INVALID_INPUT', 'full_name must be 255 characters or fewer.')
    return value.strip()


def clean_mobile_number(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise TeamError('INVALID_INPUT', 'mobile_number must be text.')
    if len(value.strip()) > 20:
        raise TeamError('INVALID_INPUT', 'mobile_number must be 20 characters or fewer.')
    return value.strip() or None


def clean_role(value):
    role = value.strip().upper() if isinstance(value, str) else None
    if role not in STAFF_ROLES:
        raise TeamError('INVALID_ROLE', 'role must be Admin, Mentor or Tutor.')
    return role


def clean_reason(value):
    if value is not None and not isinstance(value, str):
        raise TeamError('INVALID_INPUT', 'reason must be text.')
    reason = (value or '').strip() or None
    if reason and len(reason) > 500:
        raise TeamError('INVALID_INPUT', 'reason must be 500 characters or fewer.')
    return reason


@sensitive_variables('password')
def check_temporary_password(password, account):
    """Apply AUTH_PASSWORD_VALIDATORS to a password an administrator typed."""
    if not isinstance(password, str) or not password:
        raise TeamError('INVALID_INPUT', 'temporary_password is required.')
    try:
        validate_password(password, user=account)
    except ValidationError as exc:
        raise TeamError(
            'PASSWORD_POLICY',
            'The temporary password does not meet the password policy.',
            details=list(exc.messages),
        )


def permission_objects(names):
    objects = []
    for name in names:
        app_label, codename = name.split('.', 1)
        objects.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return objects


# ---------------------------------------------------------------------- views

class TeamView(APIView):
    """Answers a TeamError raised anywhere in a handler with its response."""

    def handle_exception(self, exc):
        if isinstance(exc, TeamError):
            return exc.response()
        return super().handle_exception(exc)


class TeamListView(TeamView):
    """
    GET  /api/team/ -- staff accounts, newest first. Filters: ?role=,
         ?status=active|deactivated, ?q= (username, email or name). Opt-in
         paging with ?page= (core.pagination).
    POST /api/team/ -- create a staff account holding a temporary password.
    """
    permission_classes = [IsAuthenticated, TeamAccess]
    create_fields = ('username', 'email', 'full_name', 'role', 'mobile_number', 'temporary_password')

    def get(self, request, *args, **kwargs):
        accounts = staff_accounts().select_related('invited_by').prefetch_related('user_permissions__content_type')
        if request.query_params.get('role'):
            accounts = accounts.filter(role=clean_role(request.query_params['role']))
        state = request.query_params.get('status')
        if state == 'active':
            accounts = accounts.filter(is_active=True, deactivated_at__isnull=True)
        elif state == 'deactivated':
            accounts = accounts.filter(Q(is_active=False) | Q(deactivated_at__isnull=False))
        elif state:
            raise TeamError('INVALID_INPUT', "status must be 'active' or 'deactivated'.")
        search = (request.query_params.get('q') or '').strip()
        if search:
            accounts = accounts.filter(
                Q(username__icontains=search) | Q(email__icontains=search) | Q(full_name__icontains=search)
            )
        accounts = accounts.order_by('-created_at', 'id')

        full = is_team_manager(request.user)
        page, meta = paginate_queryset(request, accounts)
        rows = [member_payload(account, full=full) for account in (accounts if page is None else page)]
        return Response(rows if meta is None else {"results": rows, **meta}, status=status.HTTP_200_OK)

    @sensitive_variables('data', 'temporary_password')
    def post(self, request, *args, **kwargs):
        data = request_fields(
            request, self.create_fields,
            required=('username', 'email', 'full_name', 'role', 'temporary_password'),
        )
        role = clean_role(data['role'])
        check_may_assign_role(request.user, role)
        temporary_password = data['temporary_password']

        with transaction.atomic():
            lock_team_changes()
            account = User(
                username=clean_username(data['username']),
                email=clean_email(data['email']),
                full_name=clean_full_name(data['full_name']),
                mobile_number=clean_mobile_number(data.get('mobile_number')),
                role=role,
                invited_by=request.user,
                is_staff=False,
                must_change_password=True,
            )
            check_temporary_password(temporary_password, account)
            account.set_password(temporary_password)
            try:
                account.save()
            except IntegrityError:
                raise TeamError('CONFLICT', 'That username or email was just taken.', status.HTTP_409_CONFLICT)

        log_activity(
            action='staff.create',
            entity_type='profile',
            entity_id=str(account.id),
            entity_label=account.full_name or account.username,
            context={"role": account.role, "username": account.username},
            request=request,
        )
        return Response(member_payload(account), status=status.HTTP_201_CREATED)


class TeamMemberView(TeamView):
    """
    GET   /api/team/<id>/ -- one staff account.
    PATCH /api/team/<id>/ -- full_name, mobile_number, username, email, role.
          A changed email passes the same checks as a new account's
          (clean_email); the username and password stay as they are.
    """
    permission_classes = [IsAuthenticated, TeamAccess]
    update_fields = ('username', 'full_name', 'mobile_number', 'email', 'role')

    def get(self, request, pk, *args, **kwargs):
        account = staff_accounts().select_related('invited_by').filter(pk=pk).first()
        if account is None:
            raise TeamError('NOT_FOUND', 'Staff account not found.', status.HTTP_404_NOT_FOUND)
        return Response(member_payload(account, full=is_team_manager(request.user)), status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        data = request_fields(request, self.update_fields)
        if not data:
            raise TeamError('INVALID_INPUT', 'Nothing to change.')

        with transaction.atomic():
            lock_team_changes()
            account = locked_staff_account(pk)
            check_may_change(request.user, account)
            before = {field: getattr(account, field) for field in self.update_fields}

            if 'username' in data:
                account.username = clean_username(data['username'], account=account)
            if 'full_name' in data:
                account.full_name = clean_full_name(data['full_name'])
            if 'mobile_number' in data:
                account.mobile_number = clean_mobile_number(data['mobile_number'])
            if 'email' in data:
                account.email = clean_email(data['email'], account=account)
            if 'role' in data:
                role = clean_role(data['role'])
                if role != account.role:
                    check_may_assign_role(request.user, role)
                    check_not_last_admin(account)
                    # Students point at their mentor and tutor by account, so
                    # a role change waits for the same handover as deactivation.
                    assigned = active_student_count(account)
                    if assigned:
                        raise TeamError(
                            'HANDOVER_REQUIRED',
                            f"Reassign this staff member's {assigned} active student(s) before changing their role.",
                            status.HTTP_409_CONFLICT,
                        )
                    account.role = role

            changed = [field for field in self.update_fields if getattr(account, field) != before[field]]
            if changed:
                try:
                    account.save(update_fields=changed + ['updated_at'])
                except IntegrityError:
                    raise TeamError('CONFLICT', 'That username or email was just taken.', status.HTTP_409_CONFLICT)

        details = {
            field: {"old": before[field], "new": getattr(account, field)}
            for field in changed if field != 'role'
        }
        if details:
            log_activity(
                action='user.update_details',
                entity_type='profile',
                entity_id=str(account.id),
                entity_label=account.full_name or account.username,
                changes=details,
                request=request,
            )
        if 'role' in changed:
            log_activity(
                action='user.role_change',
                entity_type='profile',
                entity_id=str(account.id),
                entity_label=account.full_name or account.username,
                changes={"role": {"old": before['role'], "new": account.role}},
                request=request,
            )
        return Response(member_payload(account), status=status.HTTP_200_OK)


class TeamMemberStatusView(TeamView):
    """
    POST /api/team/<id>/deactivate/ {reason?} and /api/team/<id>/reactivate/.

    The same lifecycle as /api/users/<id>/status/: deactivation waits until the
    account's ACTIVE students are handed over (/api/users/<id>/reassign/), and
    ends its existing sessions. ``activate`` is set in team_urls.py.
    """
    permission_classes = [IsAuthenticated, IsTeamManager]
    activate = None

    def post(self, request, pk, *args, **kwargs):
        data = request_fields(request, () if self.activate else ('reason',))
        reason = None if self.activate else clean_reason(data.get('reason'))

        with transaction.atomic():
            lock_team_changes()
            account = locked_staff_account(pk)
            check_may_change(request.user, account)
            was_deactivated = account.deactivated_at is not None or not account.is_active
            if self.activate:
                if not was_deactivated:
                    raise TeamError('ALREADY_ACTIVE', 'This account is already active.', status.HTTP_409_CONFLICT)
            else:
                if was_deactivated:
                    raise TeamError('ALREADY_DEACTIVATED', 'This account is already deactivated.', status.HTTP_409_CONFLICT)
                check_not_last_admin(account)
                assigned = active_student_count(account)
                if assigned:
                    raise TeamError(
                        'HANDOVER_REQUIRED',
                        f"Reassign this staff member's {assigned} active student(s) before deactivating.",
                        status.HTTP_409_CONFLICT,
                    )
            set_account_active(account, self.activate, actor=request.user, reason=reason)

        log_status_change(request, account, self.activate, was_deactivated, reason)
        return Response(member_payload(account), status=status.HTTP_200_OK)


class TeamPasswordResetView(TeamView):
    """
    POST /api/team/<id>/reset-password/ {temporary_password}

    The account must replace the password at its next sign-in, any lockout is
    cleared, and every existing session of the account ends (the session hash
    Django stores is derived from the old password).
    """
    permission_classes = [IsAuthenticated, IsTeamManager]

    @sensitive_variables('data', 'temporary_password')
    def post(self, request, pk, *args, **kwargs):
        data = request_fields(request, ('temporary_password',), required=('temporary_password',))
        temporary_password = data['temporary_password']

        with transaction.atomic():
            lock_team_changes()
            account = locked_staff_account(pk)
            check_may_change(request.user, account)
            check_temporary_password(temporary_password, account)
            was_locked = bool(account.locked_until and account.locked_until > timezone.now())
            account.set_password(temporary_password)
            account.must_change_password = True
            account.failed_login_count = 0
            account.locked_until = None
            account.save(update_fields=[
                'password', 'must_change_password', 'failed_login_count', 'locked_until', 'updated_at',
            ])

        log_activity(
            action='user.password_reset',
            entity_type='profile',
            entity_id=str(account.id),
            entity_label=account.full_name or account.username,
            context={"must_change_password": True, "unlocked": was_locked},
            request=request,
        )
        return Response(member_payload(account), status=status.HTTP_200_OK)


class TeamMemberPermissionsView(TeamView):
    """
    PUT /api/team/<id>/permissions/ {permissions: ["app_label.codename", ...]}

    Replaces the account's directly granted approved permissions.
    """
    permission_classes = [IsAuthenticated, IsTeamManager]

    def put(self, request, pk, *args, **kwargs):
        data = request_fields(request, ('permissions',), required=('permissions',))
        requested = data['permissions']
        if not isinstance(requested, list) or not all(isinstance(name, str) for name in requested):
            raise TeamError('INVALID_INPUT', 'permissions must be a list of permission names.')
        requested = set(requested)
        unknown = sorted(requested - ASSIGNABLE_PERMISSIONS.keys())
        if unknown:
            raise TeamError(
                'UNKNOWN_PERMISSION',
                f"Only approved permissions can be assigned: {', '.join(unknown)} is not one.",
                permissions=unknown,
            )

        with transaction.atomic():
            lock_team_changes()
            account = locked_staff_account(pk)
            check_may_change(request.user, account)
            current = set(granted_permissions(account))
            added, removed = requested - current, current - requested
            not_held = sorted(name for name in added | removed if not holds_permission(request.user, name))
            if not_held:
                raise TeamError(
                    'PERMISSION_NOT_GRANTABLE',
                    'You can only grant or revoke permissions you hold yourself.',
                    status.HTTP_403_FORBIDDEN,
                    permissions=not_held,
                )
            if added:
                account.user_permissions.add(*permission_objects(added))
            if removed:
                account.user_permissions.remove(*permission_objects(removed))

        if added or removed:
            log_activity(
                action='user.permissions_update',
                entity_type='profile',
                entity_id=str(account.id),
                entity_label=account.full_name or account.username,
                changes={"permissions": {"old": sorted(current), "new": sorted(requested)}},
                context={"added": sorted(added), "removed": sorted(removed)},
                request=request,
            )
        return Response(member_payload(account), status=status.HTTP_200_OK)


class TeamPermissionCatalogueView(TeamView):
    """GET /api/team/permissions/ -- the approved catalogue, and what the caller may grant."""
    permission_classes = [IsAuthenticated, IsTeamManager]

    def get(self, request, *args, **kwargs):
        return Response(
            [
                {
                    "permission": name,
                    "label": entry['label'],
                    "module": entry['module'],
                    "can_grant": holds_permission(request.user, name),
                }
                for name, entry in sorted(ASSIGNABLE_PERMISSIONS.items())
            ],
            status=status.HTTP_200_OK,
        )
