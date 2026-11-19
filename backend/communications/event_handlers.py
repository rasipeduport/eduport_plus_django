"""
What each CommunicationEvent does to the communication plan
(communications.outbox applies them): the planner operation the business code
used to call inside its own transaction, now called as of the event's
``occurred_at`` with the booking, lead or account read as it is now.

Every operation is idempotent, so an event applied again changes nothing
more: a booking is planned once (planner.plan_booking leaves a planned booking
as it is), tasks are closed only while open and messages cancelled only while
unsent, and a refresh renders the unsent messages from the current details.
"""
from accounts.models import User
from bookings.models import Lead, booking_model

from . import planner
from .models import EventKind


def apply_event(event):
    """Apply ``event`` to the plan; raises whatever the planner raises."""
    HANDLERS[event.kind](event)


def _booking(booking_type, pk):
    return booking_model(booking_type).objects.select_related(
        'slot', 'lead__owner_bde', 'assigned_tutor',
    ).get(pk=pk)


def _lead(pk):
    return Lead.objects.select_related('owner_bde').get(pk=pk)


def _created(event):
    planner.plan_booking(_booking(event.subject_type, event.subject_id), event.occurred_at)


def _parent_confirmed(event):
    actor_id = event.payload.get('actor_id')
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    planner.parent_confirmed(_booking(event.subject_type, event.subject_id), event.occurred_at, actor=actor)


def _cancelled(event):
    planner.booking_cancelled(_booking(event.subject_type, event.subject_id), event.occurred_at)


def _rescheduled(event):
    old = _booking(event.subject_type, event.subject_id)
    new = _booking(event.subject_type, event.payload['new_booking_id'])
    planner.booking_rescheduled(old, new, event.occurred_at)


def _refresh(event):
    """A tutor assigned, changed or removed, or a Meet link changed: the unsent messages checked again."""
    planner.refresh_messages(_booking(event.subject_type, event.subject_id), event.occurred_at)


def _completed(event):
    planner.booking_completed(_booking(event.subject_type, event.subject_id), event.occurred_at)


def _owner_changed(event):
    planner.lead_owner_changed(_lead(event.subject_id), event.occurred_at)


def _timezone_changed(event):
    planner.lead_timezone_changed(_lead(event.subject_id), event.occurred_at)


def _details_changed(event):
    planner.lead_details_changed(_lead(event.subject_id), event.occurred_at)


def _sender_changed(event):
    planner.sender_contact_changed(User.objects.get(pk=event.subject_id), event.occurred_at)


HANDLERS = {
    EventKind.BOOKING_CREATED: _created,
    EventKind.PARENT_CONFIRMED: _parent_confirmed,
    EventKind.BOOKING_CANCELLED: _cancelled,
    EventKind.BOOKING_RESCHEDULED: _rescheduled,
    EventKind.TUTOR_CHANGED: _refresh,
    EventKind.MEET_LINK_CHANGED: _refresh,
    EventKind.BOOKING_COMPLETED: _completed,
    EventKind.LEAD_OWNER_CHANGED: _owner_changed,
    EventKind.LEAD_TIMEZONE_CHANGED: _timezone_changed,
    EventKind.LEAD_DETAILS_CHANGED: _details_changed,
    EventKind.SENDER_CONTACT_CHANGED: _sender_changed,
}
