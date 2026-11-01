"""
A booking's history (bookings.models.BookingEvent): one event per change,
written by bookings.booking_service inside the transaction that makes the
change, so the change and its event commit or roll back together -- unlike
the activity log, which is written after commit and best-effort.

``data`` carries ids, statuses and codes only -- never free text: no
student's or parent's name, no phone number, and no reason typed by staff,
which stays on the booking itself (its cancel_reason). The history can never
be edited, so record() refuses any key it does not know rather than let
free text in by accident. A booking's events read oldest first
(``booking.events.all()``, BookingEvent.Meta.ordering).
"""
import uuid

from .models import BookingEvent, DiagnosticBooking

# What an event's data may hold: ids, statuses and codes.
DATA_KEYS = frozenset({
    'slot_id', 'seat', 'referral_status', 'via',  # CREATED
    'old_tutor_id', 'new_tutor_id',  # TUTOR_ASSIGNED / TUTOR_UNASSIGNED
    'from_status', 'to_status',  # a change of status
    'reason_code',  # CANCELLED / RESCHEDULED: a CancelReason or RescheduleReason, never text
    'old_slot_id', 'new_slot_id', 'replacement_id',  # RESCHEDULED: where it moved, and the booking replacing it
    'rescheduled_from_id',  # CREATED by a reschedule: the booking it replaces
})


def record(booking, kind, actor=None, **data):
    """Add a ``kind`` (BookingEventKind) event to ``booking``'s history. Raises ValueError for a key not in DATA_KEYS."""
    unknown = sorted(set(data) - DATA_KEYS)
    if unknown:
        raise ValueError(f'Booking history keeps ids, statuses and codes only, not: {", ".join(unknown)}.')
    target = 'diagnostic_booking' if isinstance(booking, DiagnosticBooking) else 'demo_booking'
    return BookingEvent.objects.create(
        **{target: booking},
        kind=kind,
        actor=actor,
        data={key: _plain(value) for key, value in data.items()},
    )


def _plain(value):
    """A value JSON keeps as it is: ids become strings."""
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
