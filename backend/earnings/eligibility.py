"""
Which classes count towards Tutor Earnings.

A normal session counts when all of these hold:
- someone started it (Start Session: its tutor, the student's mentor or an
  administrator) -- needed for its tutor's notes at all, never enough on its
  own;
- its assigned tutor's own notes completed it after its scheduled end
  (sessions.lifecycle), within NOTES_DEADLINE of that end, or later with
  those late notes approved by an administrator or the student's mentor;
- it was scheduled to end at or after the moment Tutor Earnings was
  activated (TutorEarningsActivation).

A class that ended before the activation never counts, whenever its notes
come in, and nothing writes earnings for classes that already existed: there
is no backfill. Staff attendance, staff notes, recordings, a start alone, late
notes awaiting approval and a class recorded as No-show / Not Conducted never
make a class count. A class counts as booked: Session.duration_hours, its
scheduled end minus its scheduled start.

Earnings reads this module, never ``completed_at`` on its own.
"""
from django.db.models import F, Q

from sessions.models import NOTES_DEADLINE, LateNotesStatus, Session, SessionStatusChoices

from .models import TutorEarningsActivation


def activated_at():
    """When Tutor Earnings was activated, or None if it never was (then nothing counts)."""
    return TutorEarningsActivation.objects.values_list('activated_at', flat=True).first()


def eligible_sessions(queryset=None):
    """The sessions of ``queryset`` (every session by default) that count towards Tutor Earnings."""
    queryset = Session.objects.all() if queryset is None else queryset
    since = activated_at()
    if since is None:
        return queryset.none()
    return queryset.filter(
        Q(completed_at__lte=F('end_time') + NOTES_DEADLINE) | Q(late_notes_status=LateNotesStatus.APPROVED),
        status=SessionStatusChoices.ATTENDED,
        started_at__isnull=False,
        completed_at__isnull=False,
        completed_by=F('tutor'),
        completed_at__gte=F('end_time'),
        end_time__gte=since,
    )


def is_eligible(session):
    """eligible_sessions for one session, read from its row as loaded."""
    since = activated_at()
    return (
        since is not None
        and session.status == SessionStatusChoices.ATTENDED
        and session.started_at is not None
        and session.completed_at is not None
        and session.completed_by_id is not None
        and session.completed_by_id == session.tutor_id
        and session.completed_at >= session.end_time
        and (session.completed_at <= session.notes_due_by or session.late_notes_status == LateNotesStatus.APPROVED)
        and session.end_time >= since
    )
