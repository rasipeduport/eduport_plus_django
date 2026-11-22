"""
What a BDE or the Admin do with a booking's communication (PRD 3.11): see a
message before it goes and ask the parent to confirm. Recording the parent's
answer changes the booking, so it lives with the other booking writes
(bookings.booking_service.record_parent_confirmation). The 15-minute call
before a class is a reminder only (communications.followups): nothing is
recorded on it.

Each action takes the booking's locks in the order every booking write takes
them (booking_service._locked_booking), so it queues behind a cancellation or
a reschedule of the same booking -- or they behind it -- and sees its status.
It does not see its plan change until that change's outbox event is applied
(communications.outbox), so each checks the booking's own status where the
plan could still trail it.
The Admin may act on any booking; a BDE only on their own leads' (``owner_bde``,
checked under the lock and answered as a booking that does not exist). Which
role may call each is the caller's check (the API, a later phase).
"""
from dataclasses import dataclass

from django.db import OperationalError, transaction
from django.utils import timezone

from activity.utils import log_activity
from bookings.booking_service import (
    BUSY_SQLSTATES,
    BookingBusy,
    BookingNotOwned,
    _locked_booking,
    _set_lock_timeout,
    slot_label,
)
from bookings.models import BookingStatus, ParentConfirmation

from . import outbox, planner
from .formatting import whatsapp_message
from .models import MessageTemplate, Step, template_key
from .rendering import booking_values, is_ready, render, requirements


class CommunicationError(Exception):
    code = 'COMMUNICATION_FAILED'
    http_status = 400
    message = 'That could not be done.'


class BookingNotUpcoming(CommunicationError):
    code = 'BOOKING_NOT_UPCOMING'
    http_status = 409
    message = 'This booking is no longer upcoming, so nothing more can be sent for it.'


class ConfirmationNotNeeded(CommunicationError):
    code = 'CONFIRMATION_NOT_NEEDED'
    http_status = 409
    message = 'The parent has already confirmed, so the confirmation request is not needed.'


class MessageBlocked(CommunicationError):
    """The message lacks something it needs (communications.rendering.Requirement)."""
    code = 'MESSAGE_BLOCKED'
    http_status = 409
    message = 'This message cannot be sent yet: some of its details are missing.'

    def __init__(self, missing):
        super().__init__(self.message)
        self.missing = missing


class NotPlanned(CommunicationError):
    """A booking made before communications existed: it has no tasks, so nothing is written for it."""
    code = 'NOT_PLANNED'
    http_status = 409
    message = 'This booking was made before parent communication began, so nothing can be sent for it.'


class CommunicationPlanPending(CommunicationError):
    """Its plan is still to be written: an event of the booking waits in the outbox (communications.outbox)."""
    code = 'COMMUNICATION_PLAN_PENDING'
    http_status = 409
    message = "This booking's parent messages are still being prepared. Try again in a minute."


class CommunicationPlanFailed(CommunicationError):
    """The event that was to write its plan FAILED (communications.outbox): for the technical team to retry."""
    code = 'COMMUNICATION_PLAN_FAILED'
    http_status = 409
    message = 'Parent messages for this booking could not be prepared. Please contact the technical team.'


def not_planned(booking):
    """
    Why ``booking`` has no plan: still on its way (CommunicationPlanPending),
    its event failed (CommunicationPlanFailed), or never to come (NotPlanned).
    """
    status = outbox.plan_status(booking, planned=False)
    if status == outbox.PlanStatus.PENDING:
        return CommunicationPlanPending()
    if status == outbox.PlanStatus.FAILED:
        return CommunicationPlanFailed()
    return NotPlanned()


class RedemoManual(CommunicationError):
    """A Re-Demo (bookings.redemos): the BDE contacts its parent by hand, so nothing is sent for it."""
    code = 'REDEMO_MANUAL'
    http_status = 409
    message = "A Re-Demo's parent is contacted by the BDE directly, so nothing is sent for it."


@dataclass(frozen=True)
class Preview:
    """
    What a booking's message for a step would say now: ``body`` as the
    template writes it, ``text`` exactly as WhatsApp would show it -- both None
    while it lacks something (``requirements``, a list of (Requirement, met)).
    """
    body: str
    requirements: list
    text: str = None


def preview(booking, step, now=None):
    """The message ``booking`` would get for ``step`` (a message step) now, written from the current template."""
    now = now or timezone.now()
    version = MessageTemplate.objects.get(key=template_key(booking.booking_type, step)).current_version()
    checks = requirements(booking, step, version.body, now)
    if not is_ready(checks):
        return Preview(body=None, requirements=checks)
    values = booking_values(booking)
    return Preview(body=render(version.body, values), requirements=checks, text=whatsapp_message(version.body, values))


def request_confirmation(booking, *, actor, owner_bde=None, now=None):
    """
    The BDE (or the Admin) asks to send ``booking``'s confirmation request --
    whenever they choose: it is available from the moment the booking is made,
    its 12-hour target is only a target. Returns (message, created): asking
    again returns the message already written, so it never goes twice.

    Refused once the booking is no longer upcoming (BookingNotUpcoming): no
    longer booked, its scheduled time come, or started by its tutor, however
    early; once the parent has answered (ConfirmationNotNeeded), for a Re-Demo (RedemoManual:
    the BDE contacts its parent by hand), for a booking made before
    communications existed (NotPlanned: it has no tasks) or whose plan is
    still being written (CommunicationPlanPending) or could not be
    (CommunicationPlanFailed), and while the
    message lacks something it needs, such as the BDE's name (MessageBlocked).
    The message is written Pending; the sending engine sends it. Writing it is
    logged once (activity ``booking.confirmation_request``); asking again, or
    being refused, logs nothing.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(booking)
            _check_owner(booking, owner_bde)
            if (booking.status != BookingStatus.BOOKED or booking.started_at is not None
                    or booking.slot.starts_at <= now):
                raise BookingNotUpcoming()
            if booking.parent_confirmation != ParentConfirmation.AWAITING:
                raise ConfirmationNotNeeded()
            existing = booking.communication_messages.filter(template__step=Step.CONFIRMATION_REQUEST).first()
            if existing is not None:
                return existing, False
            if getattr(booking, 'redemo_for_id', None):
                raise RedemoManual()
            if not booking.communication_tasks.filter(step=Step.CONFIRMATION_REQUEST).exists():
                raise not_planned(booking)
            version = MessageTemplate.objects.get(
                key=template_key(booking.booking_type, Step.CONFIRMATION_REQUEST),
            ).current_version()
            checks = requirements(booking, Step.CONFIRMATION_REQUEST, version.body, now)
            missing = [requirement for requirement, met in checks if not met]
            if missing:
                raise MessageBlocked(missing)
            message = planner.add_message(
                booking, Step.CONFIRMATION_REQUEST, now,
                scheduled_for=now, send_before=booking.slot.starts_at, created_by=actor,
            )
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='booking.confirmation_request',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        # Ids only, as for every booking entry: no parent, student, phone or message text.
        context={'booking_type': booking.booking_type, 'lead_id': str(booking.lead_id), 'message_id': str(message.pk)},
        actor=actor,
    )
    return message, True


def _check_owner(booking, owner_bde):
    if owner_bde is not None and booking.lead.owner_bde_id != owner_bde.pk:
        raise BookingNotOwned()
