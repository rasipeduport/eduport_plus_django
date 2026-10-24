"""
Forced password change for accounts holding a temporary password.

Sits right after AuthenticationMiddleware, so ``request.user`` is the
session's user. DRF's ``force_authenticate`` (used by the test suite) sets the
user later, inside the view, which is why this rule applies to real sessions
only -- exactly the surface it is meant to protect.
"""
from django.http import HttpResponseForbidden, JsonResponse

# API paths a user who must change their password may still call: the ones
# needed to learn about, perform, or abandon the change. Compared without a
# trailing slash.
PASSWORD_CHANGE_EXEMPT_PATHS = frozenset({
    '/api/auth/csrf',
    '/api/auth/login',
    '/api/auth/google',
    '/api/auth/logout',
    '/api/auth/me',
    '/api/auth/change-password',
})

# Django admin pages a flagged user may still reach: signing in (as someone
# else) and signing out. Everything else in the admin, including its own
# password-change page (which would not clear the flag), is refused.
ADMIN_EXEMPT_PATHS = frozenset({
    '/admin/login',
    '/admin/logout',
})


class PasswordChangeRequiredMiddleware:
    """
    While ``user.must_change_password`` is set (temporary password from an
    administrator), every API call other than the password-change flow is
    refused with a dedicated error code the SPA turns into a redirect, and the
    Django admin is refused outright -- otherwise a flagged account with admin
    access could keep working there and never change the password.

    Enforced here rather than as a DRF permission because most views set
    ``permission_classes`` explicitly and would silently bypass a default.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and getattr(user, 'must_change_password', False):
            path = request.path.rstrip('/')
            if request.path.startswith('/api/') and path not in PASSWORD_CHANGE_EXEMPT_PATHS:
                return JsonResponse(
                    {
                        "error": "PASSWORD_CHANGE_REQUIRED",
                        "message": "You must set a new password before continuing.",
                    },
                    status=403,
                )
            if request.path.startswith('/admin/') and path not in ADMIN_EXEMPT_PATHS:
                return HttpResponseForbidden(
                    "This account must set a new password in Eduport Plus before "
                    "using the admin site."
                )
        return self.get_response(request)
