"""
Which classes count towards Tutor Earnings.

A normal session counts when all of these hold:
- someone started it (Start Session: its tutor, the student's mentor or an
  administrator) -- needed for its tutor's notes at all, never enough on its
  own;
- its assigned tutor's own notes completed it after its scheduled end
  (sessions.lifecycle), however long after: there is no deadline;
- it was scheduled to end at or after the moment Tutor Earnings was
  activated (TutorEarningsActivation).

It counts as booked: Session.duration_hours, its scheduled end minus its
scheduled start.

A Diagnostic or Demo booking -- a Re-Demo included, which is a Demo booking of
its own with its own tutor -- counts when all of these hold:
- it was conducted (completed, or completed and then sent for a Re-Demo): a
  status alone is never enough;
- its assigned tutor started it themselves (Start Demo / Start Diagnostic);
- that tutor submitted its report themselves, which completed it;
- its slot ended at or after the activation, and has ended: a report submitted
  before the slot ends counts only once it has.

It counts as one class (every slot lasts an hour).

A class that ended before the activation never counts, whenever it was
completed, and nothing writes earnings for classes that already existed: there
is no backfill. Staff attendance, staff notes, recordings, a start alone, a
class nobody started, and a class recorded as No-show / Not Conducted -- or a
booking cancelled (a no-show included) or moved -- never count.

The ledger (earnings.ledger) reads this module, never ``completed_at`` on its
own.
"""
from django.db.models import F
from django.utils import timezone

from bookings.models import CONDUCTED
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
        and session.end_time >= since
    )


def eligible_bookings(model, queryset=None, now=None):
    """
    The bookings of ``queryset`` (every booking of ``model`` -- DiagnosticBooking
    or DemoBooking -- by default) that count towards Tutor Earnings as of ``now``.
    """
    queryset = model.objects.all() if queryset is None else queryset
    since = activated_at()
    if since is None:
        return queryset.none()
    return queryset.filter(
        status__in=CONDUCTED,
        assigned_tutor__isnull=False,
        started_at__isnull=False,
        started_by=F('assigned_tutor'),
        completed_at__isnull=False,
        completed_by=F('assigned_tutor'),
        report__isnull=False,
        report__submitted_by=F('assigned_tutor'),
        slot__ends_at__gte=since,
        slot__ends_at__lte=now or timezone.now(),
    )
