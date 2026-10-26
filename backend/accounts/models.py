import re
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .permission_catalogue import hub_permission_meta


class RoleChoices(models.TextChoices):
    ADMIN = 'ADMIN', 'Admin'
    MENTOR = 'MENTOR', 'Mentor'
    TUTOR = 'TUTOR', 'Tutor'
    BDE = 'BDE', 'BDE'
    SALES_TL = 'SALES_TL', 'Sales TL'
    STUDENT = 'STUDENT', 'Student'


# The staff roles: they sign in to the Hub with a username and password, Team
# manages their accounts, and each has a role group. What a role may do is
# never read from this list -- only from its group's permissions, within the
# catalogue's ceiling (accounts.authz) -- so BDE and Sales TL, whose group is
# empty and whose ceiling is empty, reach no data until permissions for their
# own modules are added to the catalogue.
HUB_ROLES = (RoleChoices.ADMIN, RoleChoices.MENTOR, RoleChoices.TUTOR, RoleChoices.BDE, RoleChoices.SALES_TL)


USERNAME_MAX_LENGTH = 150
USERNAME_HELP_TEXT = (
    'Sign-in name. Letters, digits and @/./+/-/_ only; stored lower-case so '
    'sign-in is case-insensitive.'
)

# A derived username keeps the ASCII subset of what UnicodeUsernameValidator
# accepts (letters, digits and . _ + -), so it can never contain an '@' and
# read like an email address.
_USERNAME_CLEAN_RE = re.compile(r'[^a-z0-9._+-]')


def derive_username_base(email):
    """
    The username an email naturally maps to: its local part, lower-cased and
    reduced to the characters usernames may contain. ``jane.doe@x.com`` gives
    ``jane.doe``; a local part with nothing usable falls back to ``user``.
    """
    local_part = (email or '').split('@', 1)[0].strip().lower()
    base = _USERNAME_CLEAN_RE.sub('_', local_part).strip('._+-')
    return (base or 'user')[:USERNAME_MAX_LENGTH]


def normalize_username(username):
    """
    Usernames are stored lower-case (after Django's NFKC normalisation) so that
    sign-in is case-insensitive while the database constraint stays a plain
    unique index.
    """
    return AbstractBaseUser.normalize_username(username or '').strip().lower()


class UserManager(BaseUserManager):
    def get_by_natural_key(self, username):
        # ModelBackend looks users up through here; normalising makes
        # `Jane.Doe` and `jane.doe` the same account everywhere.
        return self.get(username=normalize_username(username))

    def derive_username(self, email):
        """
        A unique username from an email's local part: ``jane.doe``, then
        ``jane.doe2``, ``jane.doe3``... Used wherever an account is created
        without an explicit username (Google provisioning for Learn, legacy
        fixtures that only know an email).
        """
        base = derive_username_base(email)
        candidate = base
        suffix = 2
        while self.filter(username=candidate).exists():
            tail = str(suffix)
            candidate = f"{base[:USERNAME_MAX_LENGTH - len(tail)]}{tail}"
            suffix += 1
        return candidate

    def create_user(self, email=None, password=None, username=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        username = normalize_username(username) if username else self.derive_username(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        # `createsuperuser` calls this with USERNAME_FIELD and every
        # REQUIRED_FIELDS entry as keyword arguments. A superuser is the one
        # account kind that legitimately carries is_staff (Django admin site).
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', RoleChoices.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email=email, password=password, username=username, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The sign-in identifier (USERNAME_FIELD). Email stays unique and required:
    # invitations, the enrolment sheet and the activity snapshots key on it.
    username = models.CharField(
        max_length=USERNAME_MAX_LENGTH,
        unique=True,
        validators=[UnicodeUsernameValidator()],
        help_text=USERNAME_HELP_TEXT,
    )
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    avatar_url = models.URLField(max_length=1024, blank=True, null=True)
    role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.STUDENT,
        db_index=True
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    invited_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invited_users'
    )

    # Soft-deactivation lifecycle (staff exit). NULL deactivated_at = active.
    # `deactivated_at` is the source of truth; `is_active` is kept mirrored to
    # it so Django's session machinery (ModelBackend.get_user) locks a
    # deactivated user out of an existing session on their next request.
    # `role` stays untouched so historical rows keep correct attribution.
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deactivated_users'
    )
    deactivation_reason = models.TextField(blank=True, null=True)

    # Password lifecycle. `must_change_password` is set when an administrator
    # creates an account or resets its password (a temporary password); while
    # it is True, accounts.middleware blocks every API except the ones needed
    # to change it. `password_changed_at` records the last user-driven change.
    must_change_password = models.BooleanField(
        default=False,
        help_text='The user signed in with a temporary password and must set their own before using the app.',
    )
    password_changed_at = models.DateTimeField(null=True, blank=True)

    # Password sign-in lockout, maintained by accounts.backends for every
    # password check (API login and Django admin alike). An administrator
    # unlocks an account by clearing both fields.
    failed_login_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Consecutive wrong passwords since the last successful sign-in.',
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Password sign-in is refused until this time. Clear it (and the count) to unlock.',
    )

    # Django-required fields. `is_staff` means "may use the Django admin site"
    # and nothing else; application access comes from `role` (and, from
    # Phase 3, groups and permissions). It is never set by provisioning.
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'full_name']

    class Meta:
        db_table = 'profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        ordering = ['-created_at']
        # Application permissions, listed with their per-role ceiling in
        # accounts.permission_catalogue and resolved by accounts.authz.
        permissions = [
            ('view_team', 'Can view the team directory'),
        ]

    def clean(self):
        # Normalise before validate_unique() runs (full_clean order: fields,
        # clean, unique), so a form entering "Rasi" while "rasi" exists gets a
        # validation error instead of an IntegrityError from save().
        super().clean()
        if self.username:
            self.username = normalize_username(self.username)

    def save(self, *args, **kwargs):
        if self.username:
            self.username = normalize_username(self.username)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.email} ({self.role})"


# The staff roles that carry a role group. Students never do: Learn has no
# permissions to give them.
ROLE_GROUP_ROLES = HUB_ROLES


class RoleGroup(models.Model):
    """
    The one Django group whose permissions a staff role carries.

    ``User.role`` stays the only record of who holds a role: nobody is ever a
    member of a role group (accounts.signals refuses group membership
    outright), and accounts.authz looks the group up through this row instead.
    The group's permissions are configured by superusers -- Django admin or
    ``manage.py role_permissions`` -- within the catalogue's per-role ceiling
    (accounts.permission_catalogue). Seeded by migrations 0008 (Admin, Mentor,
    Tutor) and 0009 (BDE, Sales TL, empty).
    """
    role = models.CharField(max_length=20, choices=RoleChoices.choices, primary_key=True)
    group = models.OneToOneField('auth.Group', on_delete=models.PROTECT, related_name='role_link')

    class Meta:
        db_table = 'role_groups'
        verbose_name = 'Role group'
        verbose_name_plural = 'Role groups'
        ordering = ['role']
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=[role.value for role in ROLE_GROUP_ROLES]),
                name='role_groups_staff_roles_only',
            ),
        ]

    def __str__(self):
        return f"{self.get_role_display()} -> {self.group.name}"


class HubPermission(models.Model):
    """
    The holder of the application permissions in accounts.permission_catalogue
    (all but accounts.view_team, which predates the catalogue and stays on
    User). It has no table and is never queried: Django only needs a model to
    hang permission rows on, and this keeps every application permission under
    the one "accounts" label.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = hub_permission_meta()
        verbose_name = 'Hub permission'
        verbose_name_plural = 'Hub permissions'
