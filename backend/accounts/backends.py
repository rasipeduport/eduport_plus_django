"""
Password authentication with a database-backed account lockout.

Every password check -- POST /api/auth/login/, the Django admin login,
``client.login()`` in tests -- goes through django.contrib.auth.authenticate(),
which asks this backend first (settings.AUTHENTICATION_BACKENDS). So the API
and the admin share one lockout policy:

* After LOGIN_MAX_FAILURES consecutive wrong passwords the account is refused
  until ``locked_until`` (LOGIN_LOCKOUT_SECONDS later), right password or not.
  A successful sign-in resets the count and the lock; a lock that has run out
  starts a fresh count. An administrator unlocks an account by clearing both
  fields in the Django admin.
* The check and the counter update run in one transaction holding the account
  row (SELECT ... FOR NO KEY UPDATE), so concurrent attempts are serialised and
  cannot slip extra guesses past the threshold. NO KEY keeps the lock from
  blocking inserts that merely reference the account, such as activity rows.
* Unknown usernames and locked accounts cost the same password hashing as a
  real check and get the same refusal, and an unknown username writes nothing,
  so neither the answer nor its timing tells whether an account exists or is
  locked.
* Every refusal raises PermissionDenied rather than returning None. That stops
  authenticate() at this backend, so the plain ModelBackend listed after it can
  never re-check a password and bypass the lock. ModelBackend stays listed only
  so that sessions it issued before this backend existed remain valid.

Students are NOT refused here: this backend is shared, and ``get_user()`` is
inherited unchanged, so ordinary authenticated requests, deactivation
(``is_active``) and the session hash behave exactly as before. The staff-only
rule lives in the password-login view.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from activity.utils import log_activity

from .models import normalize_username


class LockoutModelBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            # Not a username/password attempt. ModelBackend after us needs
            # both values too, so returning None cannot authenticate anyone.
            return None

        now = timezone.now()
        with transaction.atomic():
            user = (
                UserModel._default_manager.select_for_update(no_key=True)
                .filter(**{UserModel.USERNAME_FIELD: normalize_username(username)})
                .first()
            )
            if user is None:
                # Same hashing cost as a real check; no row is written.
                UserModel().set_password(password)
                raise PermissionDenied

            if user.locked_until and user.locked_until > now:
                # Hash anyway so a locked account answers as slowly as any other.
                UserModel().set_password(password)
                reason = 'locked'
            elif user.check_password(password):
                if self.user_can_authenticate(user):
                    if user.failed_login_count or user.locked_until:
                        user.failed_login_count = 0
                        user.locked_until = None
                        user.save(update_fields=['failed_login_count', 'locked_until'])
                    return user
                # The right password for a deactivated account: refused, but
                # it is not a wrong guess, so it does not count.
                reason = 'inactive'
            else:
                reason = 'invalid_password' if user.has_usable_password() else 'no_password'
                # A lock that has run out starts a fresh count.
                count = 1 if user.locked_until else user.failed_login_count + 1
                user.failed_login_count = count
                user.locked_until = (
                    now + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
                    if count >= settings.LOGIN_MAX_FAILURES else None
                )
                user.save(update_fields=['failed_login_count', 'locked_until'])

        # Outside the transaction: raising inside it would roll the count back.
        # Only existing accounts are audited, so random usernames cannot fill
        # the log. The reason is for administrators; the caller never sees it.
        log_activity(
            action='user.sign_in_failed',
            entity_type='profile',
            entity_id=str(user.id),
            entity_label=user.full_name or user.username,
            actor=user,
            context={
                'reason': reason,
                'failed_login_count': user.failed_login_count,
                'locked_until': user.locked_until.isoformat() if user.locked_until else None,
                'path': getattr(request, 'path', None),
            },
            request=request,
        )
        raise PermissionDenied
