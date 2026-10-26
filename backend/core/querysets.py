"""
Shared helpers restricting querysets to the rows the requesting user may see.

Each module has a "view all" permission and narrower ones for the students a
caller mentors or tutors (accounts.permission_catalogue). A caller sees the
union of the scopes they hold; holding none gives an empty result, so an
account no role group equips -- a new role, or one this code does not know --
sees nothing rather than everything.

The same scopes answer "may this caller act on this student?" (``reaches``):
an action permission says what a caller may do, the scope says to whom. Pass
the request so the permissions are read once per request.
"""
from django.db.models import Q

# The enrolment statuses under which a tutor still sees a student they tutor.
# An expired student drops off the tutor's list and profile; a mentor keeps
# them (follow-up, renewals).
TUTORED_STATUSES = ('ACTIVE', 'INACTIVE')

# module -> (the "view all" permission, ((narrower permission, the student's
# field naming the caller), ...)). Exams are a mentor <-> student affair: no
# scope reaches them through a tutor.
SCOPES = {
    'students': ('accounts.view_all_students', (
        ('accounts.view_mentored_students', 'mentor'),
        ('accounts.view_tutored_students', 'tutor'),
    )),
    'sessions': ('accounts.view_all_sessions', (
        ('accounts.view_mentored_sessions', 'mentor'),
        ('accounts.view_tutored_sessions', 'tutor'),
    )),
    'exams': ('accounts.view_all_exams', (
        ('accounts.view_mentored_exams', 'mentor'),
    )),
    'homework': ('accounts.view_all_homework', (
        ('accounts.view_mentored_homework', 'mentor'),
        ('accounts.view_tutored_homework', 'tutor'),
    )),
}


def view_permissions(module):
    """Every permission that opens some of ``module``'s rows."""
    view_all, narrower = SCOPES[module]
    return (view_all, *(perm for perm, _ in narrower))


STUDENT_VIEW_PERMISSIONS = view_permissions('students')
SESSION_VIEW_PERMISSIONS = view_permissions('sessions')
EXAM_VIEW_PERMISSIONS = view_permissions('exams')
HOMEWORK_VIEW_PERMISSIONS = view_permissions('homework')
ACTIVITY_VIEW_PERMISSIONS = ('accounts.view_all_activity', 'accounts.view_own_activity')


def _held(user, request):
    from accounts.authz import effective_permissions
    return effective_permissions(user, request)


def _scope(module, qs, user, request, prefix='', tutored=None):
    view_all, narrower = SCOPES[module]
    held = _held(user, request)
    if view_all in held:
        return qs
    condition = Q(pk__in=[])
    for perm, field in narrower:
        if perm in held:
            extra = tutored if field == 'tutor' and tutored else {}
            condition |= Q(**{f'{prefix}{field}': user}, **{f'{prefix}{k}': v for k, v in extra.items()})
    return qs.filter(condition)


def scope_students(qs, user, request=None, current_only=True):
    """
    Restrict a ``Student`` queryset to the students ``user`` may see: all of
    them, the ones they mentor, the ones they tutor. A tutor sees a student
    only while ACTIVE or INACTIVE; ``current_only=False`` drops that rule (the
    dashboard counts every student a tutor has).
    """
    tutored = {'status__in': TUTORED_STATUSES} if current_only else None
    return _scope('students', qs, user, request, tutored=tutored)


def scope_sessions(qs, user, request=None):
    """Restrict a ``Session`` queryset to those of the students ``user`` may see sessions of."""
    return _scope('sessions', qs, user, request, prefix='student__')


def scope_exams(qs, user, request=None):
    """Restrict an ``Exam`` / ``AdditionalExam`` queryset."""
    return _scope('exams', qs, user, request, prefix='student__')


def scope_homework(qs, user, request=None):
    """Restrict a ``Homework`` queryset: the mentor assigns it, the tutor grades it."""
    return _scope('homework', qs, user, request, prefix='student__')


def scope_activity(qs, user, request=None):
    """Restrict an ``ActivityLog`` queryset: the whole log, or the entries ``user`` wrote."""
    held = _held(user, request)
    if 'accounts.view_all_activity' in held:
        return qs
    if 'accounts.view_own_activity' in held:
        return qs.filter(actor_id=user.id)
    return qs.none()


def reaches(module, user, student, request=None):
    """
    Whether ``student`` is within ``user``'s scope for ``module`` (sessions,
    exams, homework): the "to whom" half of every write those modules allow.
    Read from the student row, no query.
    """
    view_all, narrower = SCOPES[module]
    held = _held(user, request)
    if view_all in held:
        return True
    return any(perm in held and getattr(student, f'{field}_id') == user.id for perm, field in narrower)
