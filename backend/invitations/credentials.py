"""Student credential issuance. No email lookup or login-time provisioning."""
import json
import secrets

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException

from activity.utils import log_activity
from .models import Invitation


class CredentialUnavailable(APIException):
    status_code = 503
    default_detail = 'Learn credential delivery is unavailable. Configure LEARN_INVITATION_KEYS before collecting tuition.'
    default_code = 'LEARN_CREDENTIALS_UNAVAILABLE'


def credential_cipher():
    """First key encrypts; remaining keys permit safe, staged key rotation."""
    try:
        return MultiFernet([Fernet(key) for key in settings.LEARN_INVITATION_KEYS])
    except (ValueError, TypeError):
        raise CredentialUnavailable() from None


@sensitive_variables()
def new_account(student_code, full_name, actor=None):
    """Unique index is the final concurrency guard, including collisions with staff."""
    credential_cipher()  # Fail closed before creating an account.
    User = get_user_model()
    base = User.normalize_username(student_code).lower()
    for attempt in range(10):
        username = base if not attempt else f'{base}-{secrets.token_hex(4)}'
        password = secrets.token_urlsafe(24)
        user = User(username=username, email=None, role='STUDENT', full_name=full_name,
                    invited_by=actor, must_change_password=True, is_active=True)
        validate_password(password, user=user)
        user.set_password(password)
        try:
            with transaction.atomic():
                user.save(force_insert=True)
            return user, password
        except IntegrityError:
            if not User.objects.filter(username=username).exists():
                raise
    raise CredentialUnavailable()


@sensitive_variables()
def seal_credentials(invitation, password):
    # Bind ciphertext to its row/account/student; copying a DB blob cannot
    # reveal another account's credentials through an authorized row.
    payload = json.dumps({'invitation': str(invitation.pk), 'student': str(invitation.student_id),
                          'account': str(invitation.account_id), 'password': password})
    return credential_cipher().encrypt(payload.encode()).decode()


@sensitive_variables()
def create_invitation(student, account, password, actor=None, extra_data=None, invitation=None):
    invitation = invitation or Invitation(student=student, role='STUDENT', invited_by=actor)
    invitation.student = student
    invitation.account = account
    invitation.status = 'PENDING'
    invitation.extra_data = {**(invitation.extra_data or {}), **(extra_data or {}),
                             'student_code': student.student_code, 'full_name': student.full_name}
    invitation.credential_ciphertext = seal_credentials(invitation, password)
    invitation.save()
    log_activity('invitation.credentials_created', 'invitation', invitation.pk,
                 student=student, actor=actor, entity_label=student.student_code)
    return invitation


@sensitive_variables()
def reveal_credentials(invitation):
    # An activated account has a temporary password only between an
    # administrator's reset and the student's own change, which erases it.
    if (invitation.status not in ('PENDING', 'ACCEPTED') or not invitation.account_id or not invitation.student_id
            or invitation.student.profile_id != invitation.account_id
            or not invitation.credential_ciphertext or not invitation.account.must_change_password):
        return None
    try:
        payload = json.loads(credential_cipher().decrypt(invitation.credential_ciphertext.encode()))
        if (payload['invitation'], payload['student'], payload['account']) != (
                str(invitation.pk), str(invitation.student_id), str(invitation.account_id)):
            raise ValueError()
        return payload['password']
    except (InvalidToken, ValueError, KeyError):
        raise CredentialUnavailable() from None


def regenerable(invitation):
    """Whether an administrator may replace this account's temporary password.

    Reveal's rule without the stored ciphertext: a pending account still on
    its first password. Replacing it is also how credentials sealed with a key
    since removed from LEARN_INVITATION_KEYS become readable again.
    """
    return bool(invitation.status == 'PENDING' and invitation.account_id and invitation.student_id
                and invitation.student.profile_id == invitation.account_id
                and invitation.account.must_change_password)


def resettable(invitation):
    """Whether an administrator may reset this activated account's password.

    The account stays activated; it gets a temporary password it must replace
    at its next sign-in. Its current password is never read, only replaced.
    """
    return bool(invitation.status == 'ACCEPTED' and invitation.account_id and invitation.student_id
                and invitation.student.profile_id == invitation.account_id)


@sensitive_variables()
def regenerate_credentials(invitation):
    """Give the account a new temporary password; its previous password stops working at once.

    Used for a pending account (regenerable()) and an activated one
    (resettable()); its status is not touched. The caller has checked which
    under the account then invitation row locks (the order password change and
    reveal take them). The account
    must still choose its own password at its next sign-in, any lockout is
    cleared, and every session signed in with the old password ends (the
    session hash Django stores derives from it). Returns whether a lockout
    was cleared. The new password is read through reveal_credentials only.
    """
    credential_cipher()  # Fail closed before the old password is replaced.
    account = invitation.account
    password = secrets.token_urlsafe(24)
    validate_password(password, user=account)
    was_locked = bool(account.locked_until and account.locked_until > timezone.now())
    account.set_password(password)
    account.must_change_password = True
    account.failed_login_count = 0
    account.locked_until = None
    account.save(update_fields=['password', 'must_change_password', 'failed_login_count', 'locked_until', 'updated_at'])
    invitation.credential_ciphertext = seal_credentials(invitation, password)
    invitation.password_reset_at = timezone.now()
    invitation.save(update_fields=['credential_ciphertext', 'password_reset_at', 'updated_at'])
    return was_locked


@transaction.atomic
def issue_existing_student(student_id, actor, request=None):
    """Explicit Admin transition for legacy Google accounts; no academic copies.

    Lock student before inspecting the one-to-one invitation. Repeated issuance
    returns the original credentials and never rotates an activated account.
    The old parent may still own siblings; changing this FK removes its access
    to this student without changing anyone else's academic or payment records.
    """
    from students.models import Student
    student = Student.objects.select_for_update().get(pk=student_id)
    existing = Invitation.objects.filter(student=student).first()
    if existing:
        return existing
    account, password = new_account(student.student_code, student.full_name, actor)
    student.profile = account
    student.save(update_fields=['profile'])
    legacy = Invitation.objects.filter(role='STUDENT', student__isnull=True,
                                       extra_data__student_code=student.student_code).order_by('created_at').first()
    invitation = create_invitation(student, account, password, actor,
                                   extra_data={'source': 'LEGACY_STUDENT_TRANSITION'}, invitation=legacy)
    log_activity('invitation.legacy_transition', 'invitation', invitation.pk, student=student,
                 request=request, actor=actor, entity_label=student.student_code)
    return invitation
