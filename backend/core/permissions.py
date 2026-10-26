"""
Permission classes for the API views.

Staff endpoints are guarded by catalogue permissions (accounts.authz), never by
role: HasAppPermission / HasAnyAppPermission, or ByMethod when methods differ.
Each view then confines what it returns or changes to the caller's scope
(core.querysets). Learn's endpoints keep their persona rule -- the STUDENT
role, confined to the selected student -- through IsStudentUser and
IsStudentUserFor. core.tests_role_scoping checks that every API view says which
permission guards it.
"""

from rest_framework.permissions import BasePermission


def _is_authenticated(request):
    return bool(request.user and request.user.is_authenticated)


class IsStudentUser(BasePermission):
    """Allows access only to the Student role (Learn's persona endpoints)."""

    def has_permission(self, request, view):
        return _is_authenticated(request) and request.user.role == 'STUDENT'


def HasAppPermission(perm):
    """
    A permission class admitting exactly the accounts that hold catalogue
    permission ``perm`` (accounts.authz: the role's group plus individual
    grants, within the role's ceiling). The way modules guard their views by
    permission rather than by role:

        permission_classes = [IsAuthenticated, HasAppPermission('accounts.create_session')]

    A name missing from the catalogue admits nobody. The answer is cached for
    the request, so a view checking several permissions reads them once.
    """

    class _HasAppPermission(BasePermission):
        def has_permission(self, request, view):
            from accounts.authz import has_app_permission
            return _is_authenticated(request) and has_app_permission(request.user, perm, request)

    _HasAppPermission.__name__ = _HasAppPermission.__qualname__ = f'HasAppPermission({perm!r})'
    return _HasAppPermission


def HasAnyAppPermission(*perms):
    """
    Like HasAppPermission, admitting the accounts that hold at least one of
    ``perms`` -- e.g. a list endpoint open to whoever may view all, mentored or
    tutored students, which then scopes the rows by the one they hold.
    """

    class _HasAnyAppPermission(BasePermission):
        def has_permission(self, request, view):
            from accounts.authz import has_any_app_permission
            return _is_authenticated(request) and has_any_app_permission(request.user, perms, request)

    _HasAnyAppPermission.__name__ = _HasAnyAppPermission.__qualname__ = f'HasAnyAppPermission{perms!r}'
    return _HasAnyAppPermission


def ByMethod(**classes):
    """
    A permission class per HTTP method, for a view whose methods need different
    permissions. A method not named admits nobody; HEAD follows GET, and
    OPTIONS (metadata only) is open to whoever some method admits.

        permission_classes = [IsAuthenticated, ByMethod(
            GET=HasAppPermission('accounts.view_student_notes'),
            POST=HasAppPermission('accounts.add_student_note'),
        )]
    """

    class _ByMethod(BasePermission):
        def has_permission(self, request, view):
            method = 'GET' if request.method == 'HEAD' else request.method
            if method == 'OPTIONS':
                return any(cls().has_permission(request, view) for cls in classes.values())
            cls = classes.get(method)
            return cls is not None and cls().has_permission(request, view)

    _ByMethod.__name__ = _ByMethod.__qualname__ = f'ByMethod({", ".join(classes)})'
    _ByMethod.classes = classes
    return _ByMethod


def IsStudentUserFor(*methods):
    """
    The Learn persona on an endpoint it shares with the Hub: admits the STUDENT
    role for ``methods`` only, and the view then confines it to the selected
    student. Combined with the staff permission by OR:

        permission_classes = [IsAuthenticated, HasAnyAppPermission(...) | IsStudentUserFor('GET')]
    """

    class _IsStudentUserFor(BasePermission):
        def has_permission(self, request, view):
            return IsStudentUser().has_permission(request, view) and request.method in methods

    _IsStudentUserFor.__name__ = _IsStudentUserFor.__qualname__ = f'IsStudentUserFor{methods!r}'
    return _IsStudentUserFor
