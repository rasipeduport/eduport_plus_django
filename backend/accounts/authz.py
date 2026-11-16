"""
The one place an account's application permissions are worked out.

    effective = (permissions of the role's group  -- accounts.RoleGroup
                 + the account's individual grants) -- Team API
                & the catalogue entries its role may hold

Superusers hold every catalogue permission, whatever their role (decision D1);
inactive and anonymous accounts hold none; a role with no catalogue entries
(students, or a role this code does not know) holds none whatever is stored
for it.

``user.groups`` is never read. Django's ModelBackend -- still installed so that
sessions from before the lockout backend keep working -- would honour any group
membership through ``user.has_perm``, so application code asks this module
(``has_app_permission``, or core.permissions.HasAppPermission in a view)
instead. Group membership is also refused outright (accounts.signals).

Pass the request and the answer is cached for that request only, on the
underlying HttpRequest -- never on the user object, which can outlive a request
(tests reuse one across many). Without a request every call reads afresh: two
small queries.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.auth.models import Permission

from activity.utils import log_activity

from .permission_catalogue import CATALOGUE, allowed_for_role, grantable_permissions


def _names(permissions):
    """A Permission queryset as "app_label.codename" strings."""
    return {f'{app_label}.{codename}' for app_label, codename in permissions.values_list('content_type__app_label', 'codename')}


def role_permissions(role):
    """The catalogue permissions the group of ``role`` carries, within the role's ceiling."""
    return _names(Permission.objects.filter(group__role_link__role=role)) & allowed_for_role(role)


def direct_permissions(user):
    """
    The individually grantable permissions granted to ``user`` (the Team API's
    grants). A grant of anything else -- made outside Team, say from a shell --
    counts for nothing; ``manage.py role_permissions check`` reports it.
    """
    return _names(user.user_permissions.all()) & grantable_permissions()


def _resolve(user):
    if not (user and user.is_authenticated and user.is_active):
        return set()
    if user.is_superuser:
        return set(CATALOGUE)
    allowed = allowed_for_role(user.role)
    if not allowed:
        return set()
    return (role_permissions(user.role) | direct_permissions(user)) & allowed


def _request_cache(request):
    # A DRF Request wraps the HttpRequest; the cache lives on the latter, so
    # the view and anything else holding the same request share it.
    http_request = getattr(request, '_request', request)
    cache = getattr(http_request, '_app_permission_cache', None)
    if cache is None:
        cache = http_request._app_permission_cache = {}
    return cache


def effective_permissions(user, request=None):
    """Every catalogue permission ``user`` holds, as a set of "app_label.codename" strings."""
    if request is None:
        return _resolve(user)
    cache = _request_cache(request)
    key = getattr(user, 'pk', None)
    if key not in cache:
        cache[key] = frozenset(_resolve(user))
    return set(cache[key])


def has_app_permission(user, perm, request=None):
    """Whether ``user`` holds catalogue permission ``perm``. Unknown names are held by nobody."""
    return perm in CATALOGUE and perm in effective_permissions(user, request)


def has_any_app_permission(user, perms, request=None):
    """Whether ``user`` holds at least one of the catalogue permissions ``perms``."""
    held = effective_permissions(user, request)
    return any(perm in CATALOGUE and perm in held for perm in perms)


# ------------------------------------------------------------- audit context

# Who is acting while permissions change outside a request -- the Django admin
# and manage.py role_permissions set it -- so accounts.signals can name them.
_acting = ContextVar('accounts_authz_acting', default=None)


@contextmanager
def acting_as(actor, via):
    token = _acting.set((actor, via))
    try:
        yield
    finally:
        _acting.reset(token)


def current_actor():
    """(actor or None, via) for the change in progress; unattributed changes come from 'model'."""
    return _acting.get() or (None, 'model')


# ------------------------------------------------------------- role changes

def clear_individual_permissions(account):
    """
    Remove every individual grant ``account`` holds -- catalogue or not -- and
    return what was removed, sorted. Called whenever the role changes: a grant
    made for one role must not ride along into another.
    """
    cleared = sorted(_names(account.user_permissions.all()))
    if cleared:
        account.user_permissions.clear()
    return cleared


def log_permissions_cleared(account, cleared, via, request=None, actor=None):
    """Audit grants removed by a role change, in the shape the Hub's activity feed reads."""
    log_activity(
        action='user.permissions_update',
        entity_type='profile',
        entity_id=str(account.id),
        entity_label=account.full_name or account.username,
        changes={"permissions": {"old": cleared, "new": []}},
        context={"added": [], "removed": cleared, "reason": "role_change", "via": via},
        request=request,
        actor=actor,
    )
