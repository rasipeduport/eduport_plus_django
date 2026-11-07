"""
Where a Re-Demo request stands (bookings.redemos), read from its rows every
time and never stored, so it cannot disagree with them:

    AWAITING_SCHEDULING  no Demo of its own booked or taught: an
                         administrator's step (never scheduled yet, or the
                         Demo they scheduled was cancelled)
    SCHEDULED            the Demo they scheduled -- as last moved -- is still
                         booked, whatever its slot's clock says, until staff
                         cancel it or its tutor completes it
    COMPLETED            that Demo has been taught: it may now have a
                         Re-Demo of its own

Read-only; every write is bookings.booking_service's or bookings.redemos'.
"""
from dataclasses import dataclass

from .models import CONDUCTED, BookingStatus, ReDemoRequest, ReDemoStatus


@dataclass(frozen=True)
class RedemoState:
    """
    One request as it stands: ``status`` (a ReDemoStatus) and the Demos
    scheduled for it (``bookings``, oldest first, each as last moved: the
    bookings a reschedule replaced are left out).
    """
    redemo: object
    status: str
    bookings: list

    @property
    def booking(self):
        """The Demo scheduled last -- the one booked or taught, if any -- or None."""
        return self.bookings[-1] if self.bookings else None


def state(redemo, now):
    """``redemo`` as it stands ``now``. Reads ``redemo.bookings`` (prefetch them, with their slots, for a list)."""
    bookings = sorted(
        (booking for booking in redemo.bookings.all() if booking.status != BookingStatus.RESCHEDULED),
        key=lambda booking: booking.created_at,
    )
    latest = bookings[-1] if bookings else None
    if latest is not None and latest.status in CONDUCTED:
        status = ReDemoStatus.COMPLETED
    elif latest is not None and latest.status == BookingStatus.BOOKED:
        status = ReDemoStatus.SCHEDULED
    else:
        status = ReDemoStatus.AWAITING_SCHEDULING
    return RedemoState(redemo=redemo, status=status, bookings=bookings)


def request_of(booking):
    """The Re-Demo request ``booking`` was sent for (it is RE-DEMO REQUIRED), or None."""
    if booking.status != BookingStatus.REDEMO_REQUIRED:
        return None
    try:
        return booking.redemo_request
    except ReDemoRequest.DoesNotExist:
        return None


def redemo_number(redemo):
    """Which Re-Demo of its lead's chain ``redemo`` schedules: 1 for a Demo's first, 2 when that was a Re-Demo, and so on."""
    number, booking = 1, redemo.demo_booking
    while booking.redemo_for_id is not None and number < 50:
        number += 1
        booking = booking.redemo_for.demo_booking
    return number
