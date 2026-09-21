"""
Helpers for the multi-profile (one parent account -> many students) model.

A parent account (``User`` with role STUDENT) may own several ``Student`` rows.
Which one the learn frontend is currently acting on is stored in the
``ep-student-id`` cookie. These helpers centralise reading that selection so
every student-facing endpoint scopes to the same child.

Enrollment statuses gate self-access the way the original Learn app does:
only ``EXPIRED`` is the terminal lockout (``BLOCKING_STATUSES``); ``INACTIVE``
is a soft pause with full access. Expired personas are still *returned* by
``get_account_students`` — the frontend needs them to tell "access ended"
apart from "no account yet" — but they are never usable: they cannot be
selected and no student-facing endpoint operates on them.
"""

EP_STUDENT_COOKIE = 'ep-student-id'

# Kept in sync with the Hub's gate: only 'expired' blocks; 'inactive' is a
# soft pause (full access + a banner in the Learn app).
BLOCKING_STATUSES = ('EXPIRED',)


def get_account_students(user):
    """All students owned by this account (any status), oldest admission first."""
    from students.models import Student
    return Student.objects.filter(profile=user).order_by('created_at')


def get_usable_students(user):
    """The account's students that may act in the Learn app (not expired)."""
    return get_account_students(user).exclude(status__in=BLOCKING_STATUSES)


def resolve_selected_student(request):
    """
    Return the ``Student`` the request is acting on, or ``None`` if it cannot
    be resolved unambiguously. Only usable (non-expired) personas are ever
    resolved — a cookie pointing at an expired persona is ignored, and an
    account whose sole usable persona remains is auto-selected onto it
    (mirrors the original Learn layout's ``usable`` handling).

    Resolution order:
      1. The usable student named by the ``ep-student-id`` cookie, if it
         belongs to this account.
      2. The sole usable student, when the account has exactly one.
      3. ``None`` -- several usable students and none selected, so the caller
         should prompt the user to pick one (or no usable students at all).
    """
    students = list(get_usable_students(request.user))
    if not students:
        return None

    selected_id = request.COOKIES.get(EP_STUDENT_COOKIE)
    if selected_id:
        for student in students:
            if str(student.id) == selected_id:
                return student

    if len(students) == 1:
        return students[0]

    return None
