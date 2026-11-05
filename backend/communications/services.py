"""
What a BDE or the Admin do with a booking's communication (PRD 3.11): see a
message before it goes, ask the parent to confirm, and record how the
15-minute call went. Recording the parent's answer changes the booking, so it
lives with the other booking writes (bookings.booking_service.
record_parent_confirmation).

Each action takes the booking's locks in the order every booking write takes
them (booking_service._locked_booking), so it queues behind a cancellation or
a reschedule of the same booking -- or they behind it -- and sees its result.
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

from . import planner
from .formatting import whatsapp_message
from .models import CALL_OUTCOMES, CallOutcome, CommunicationTask, MessageTemplate, Step, TaskStatus, template_key
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


class NotACall(CommunicationError):
    code = 'NOT_A_CALL'
    message = 'Only the 15-minute call takes a call outcome.'


class InvalidCallOutcome(CommunicationError):
    code = 'INVALID_OUTCOME'
    message = 'Choose Called, Messaged or No Answer.'


class CallNotOpenYet(CommunicationError):
    code = 'CALL_NOT_OPEN_YET'
    http_status = 409
    message = 'This call opens 15 minutes before the start.'


class TaskClosed(CommunicationError):
    code = 'TASK_CLOSED'
    http_status = 409
    message = 'This task is closed, so nothing more can be recorded on it.'


class NotPlanned(CommunicationError):
    """A booking made before communications existed: it has no tasks, so nothing is written for it."""
    code = 'NOT_PLANNED'
    http_status = 409
    message = 'This booking was made before parent communication began, so nothing can be sent for it.'


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

    Refused once the booking is no longer upcoming (BookingNotUpcoming), once
    the parent has answered (ConfirmationNotNeeded), for a booking made before
    communications existed (NotPlanned: it has no tasks), and while the
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
            if booking.status != BookingStatus.BOOKED or booking.slot.starts_at <= now:
                raise BookingNotUpcoming()
            if booking.parent_confirmation != ParentConfirmation.AWAITING:
                raise ConfirmationNotNeeded()
            existing = booking.communication_messages.filter(template__step=Step.CONFIRMATION_REQUEST).first()
            if existing is not None:
                return existing, False
            if not booking.communication_tasks.filter(step=Step.CONFIRMATION_REQUEST).exists():
                raise NotPlanned()
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


def record_call_outcome(task, outcome, *, actor, owner_bde=None, now=None):
    """
    Record how the BDE's 15-minute call of ``task``'s booking went: Called,
    Messaged or No Answer. Every outcome is kept (CallOutcome); the task is
    Done and shows the latest, so a later Called after a No Answer erases
    nothing. Only from 15 minutes before the start (CallNotOpenYet) until the
    slot ends -- after that the call is Missed -- and never on a cancelled
    booking's call (TaskClosed). Nothing ever records one by itself.
    """
    if outcome not in CALL_OUTCOMES:
        raise InvalidCallOutcome()
    if task.step != Step.PRE_ACTIVITY_CALL:
        raise NotACall()
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            booking = _locked_booking(task.booking)
            _check_owner(booking, owner_bde)
            task = CommunicationTask.objects.select_for_update().get(pk=task.pk)
            if task.status not in (TaskStatus.OPEN, TaskStatus.DONE) or task.expires_at <= now:
                raise TaskClosed()
            if task.active_from > now:
                raise CallNotOpenYet()
            entry = CallOutcome.objects.create(task=task, outcome=outcome, recorded_by=actor, recorded_at=now)
            task.status = TaskStatus.DONE
            task.resolution = outcome
            task.resolved_at = now
            task.resolved_by = actor
            task.save(update_fields=['status', 'resolution', 'resolved_at', 'resolved_by', 'updated_at'])
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    return entry


def _check_owner(booking, owner_bde):
    if owner_bde is not None and booking.lead.owner_bde_id != owner_bde.pk:
        raise BookingNotOwned()
