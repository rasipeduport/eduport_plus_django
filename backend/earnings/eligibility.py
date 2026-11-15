"""
Which classes count towards Tutor Earnings.

A normal session counts when both hold:
- its assigned tutor's own notes completed it after its originally scheduled
  end (sessions.lifecycle), whoever started it, if anyone did;
- it was scheduled to end at or after the moment Tutor Earnings was activated
  (TutorEarningsActivation).

A class that ended before the activation never counts, whenever its notes
come in, and nothing writes earnings for classes that already existed: there
is no backfill. Staff attendance, staff notes, recordings and a start never
make a class count. A class counts as booked: Session.duration_hours, its
scheduled end minus its scheduled start.

Earnings reads this module, never ``completed_at`` on its own.
"""
from django.db.models import F

from sessions.models import Session, SessionStatusChoices

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
        status=SessionStatusChoices.ATTENDED,
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
        and session.completed_at is not None
        and session.completed_by_id is not None
        and session.completed_by_id == session.tutor_id
        and session.completed_at >= session.end_time
        and session.end_time >= since
    )
