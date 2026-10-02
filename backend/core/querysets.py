"""
Shared helpers for restricting querysets by the requesting user's role.

Mentors and tutors only ever see the students (and the sessions of the students)
allocated to them, and only their own activity-log entries; admins and other
roles see everything passed in.
"""


def scope_students_by_role(qs, user):
    """Restrict a ``Student`` queryset to the rows a mentor/tutor may see."""
    if user.role == 'MENTOR':
        return qs.filter(mentor=user)
    if user.role == 'TUTOR':
        return qs.filter(tutor=user)
    return qs


def scope_sessions_by_role(qs, user):
    """Restrict a ``Session`` queryset to the rows a mentor/tutor may see."""
    if user.role == 'MENTOR':
        return qs.filter(student__mentor=user)
    if user.role == 'TUTOR':
        return qs.filter(student__tutor=user)
    return qs


def scope_activity_by_role(qs, user):
    """
    Restrict an ``ActivityLog`` queryset to the rows a mentor/tutor may see:
    only the entries they wrote themselves. Admins see everything.
    """
    if user.role in ('MENTOR', 'TUTOR'):
        return qs.filter(actor_id=user.id)
    return qs


def scope_exams_by_role(qs, user):
    """
    Restrict an ``Exam`` / ``AdditionalExam`` queryset to the rows a staff
    member may see. Exams are a mentor <-> student affair: mentors see their
    allocated students' exams, admins everything, tutors nothing at all.
    """
    if user.role == 'MENTOR':
        return qs.filter(student__mentor=user)
    if user.role == 'TUTOR':
        return qs.none()
    return qs
