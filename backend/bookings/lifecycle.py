"""
Where a booking stands as an activity -- the Demo or Diagnostic its tutor
teaches -- worked out in one place for the Admin's, the tutor's and the BDE's
views alike, so no screen derives it from the clock on its own.

A booking starts only when its tutor says so: Start Demo or Start Diagnostic
(booking_service.start_booking), from START_EARLY before its slot until the
slot ends, recorded as ``started_at`` by the server's clock. Its scheduled
time alone never starts it, and never makes it done: a slot that ends with no
start leaves the booking booked but NOT_STARTED -- no report can follow --
until the Admin cancels or moves it.

    UPCOMING     booked, Start not open yet
    READY        booked, Start open: from START_EARLY before the slot starts
    LATE         booked, the scheduled time passed, not started, the slot not over
    IN_PROGRESS  started by its tutor, its report not in yet
    NOT_STARTED  booked, the slot over with no start
    COMPLETED, CANCELLED, RESCHEDULED   by its status (a Demo sent for a
                 Re-Demo is COMPLETED: it was taught)

A cancelled booking keeps the start it had (a no-show after the tutor
started, say); a completed one may have none -- one completed before Start
existed, whose start was never recorded.
"""
from datetime import timedelta

from django.db.models import TextChoices

from .models import BookingStatus

# Start opens this long before the slot and stays open until the slot ends.
START_EARLY = timedelta(minutes=5)


class ActivityState(TextChoices):
    UPCOMING = 'UPCOMING', 'Upcoming'
    READY = 'READY', 'Ready to start'
    LATE = 'LATE', 'Not started yet'
    IN_PROGRESS = 'IN_PROGRESS', 'In progress'
    NOT_STARTED = 'NOT_STARTED', 'Not started'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    RESCHEDULED = 'RESCHEDULED', 'Rescheduled'


_BY_STATUS = {
    BookingStatus.COMPLETED: ActivityState.COMPLETED,
    BookingStatus.REDEMO_REQUIRED: ActivityState.COMPLETED,
    BookingStatus.CANCELLED: ActivityState.CANCELLED,
    BookingStatus.RESCHEDULED: ActivityState.RESCHEDULED,
}


def start_opens_at(slot):
    """The first moment a booking of ``slot`` may be started."""
    return slot.starts_at - START_EARLY


def activity_state(booking, now):
    """Where ``booking`` stands as of ``now`` (an ActivityState value)."""
    if booking.status in _BY_STATUS:
        return _BY_STATUS[booking.status]
    if booking.started_at is not None:
        return ActivityState.IN_PROGRESS
    slot = booking.slot
    if slot.ends_at <= now:
        return ActivityState.NOT_STARTED
    if slot.starts_at <= now:
        return ActivityState.LATE
    if start_opens_at(slot) <= now:
        return ActivityState.READY
    return ActivityState.UPCOMING
