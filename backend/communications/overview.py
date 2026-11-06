"""
A booking's communication as the Hub shows it (Phase 3.1): the parent's
answer to the confirmation request, the booking's five tasks with their status
and moments, and its WhatsApp messages, each as WhatsApp shows it, with their
attempts and Meta's status reports -- read-only, for whoever
communications.views lets see it.

Every code comes with its label, and every moment is ISO 8601; the Hub shows
them in Indian time. ``actions`` says what the caller could do next -- ask for
confirmation, record the parent's answer -- by the permissions they hold and
the rules the services apply, for the screens that offer those actions; this
module changes nothing.
"""
from django.db.models import Prefetch, TextChoices

from accounts.authz import has_app_permission
from bookings.coordination import slot_brief
from bookings.lifecycle import activity_state
from bookings.models import BookingStatus, NotConfirmedReason, ParentConfirmation
from bookings.scheduling import BOOKING_TIMEZONE_NAME

from .formatting import whatsapp_message
from .models import (
    OUTCOME_UNKNOWN,
    MessageAttempt,
    MessageStatus,
    MessageStatusEvent,
    Step,
    TaskStatus,
)
from .rendering import Requirement, requirements
from .sending import INVALID_RECIPIENT

SEND_COMMUNICATIONS = 'accounts.send_lead_communications'
RECORD_CONFIRMATION = 'accounts.record_parent_confirmation'
# The tasks in the order the PRD's workflow runs them.
STEP_ORDER = {step: index for index, step in enumerate(Step.values)}


class MessageProblem(TextChoices):
    """What went wrong with a message, for the screens to flag; None when nothing did."""
    RETRYING = 'RETRYING', 'Refused for now: trying again'
    REFUSED = 'REFUSED', 'Refused by WhatsApp'
    INVALID_RECIPIENT = 'INVALID_RECIPIENT', 'Not an international WhatsApp number'
    OUTCOME_UNKNOWN = 'OUTCOME_UNKNOWN', 'Outcome unknown: check WhatsApp before sending it again'
    DELIVERY_FAILED = 'DELIVERY_FAILED', 'Accepted, then not delivered'


def booking_communication(booking, now, user=None, request=None):
    """
    ``booking``'s communication in full (read with its slot, lead, lead's BDE,
    tutor and confirming account). A booking made before communications
    existed has no plan: ``planned`` is false and it has no tasks or messages.
    """
    tasks = sorted(
        booking.communication_tasks.select_related('owner', 'resolved_by'),
        key=lambda task: STEP_ORDER[task.step],
    )
    messages = list(
        booking.communication_messages.select_related('template', 'template_version', 'created_by').prefetch_related(
            Prefetch('attempts', queryset=MessageAttempt.objects.select_related('triggered_by').order_by('number')),
            Prefetch('status_events', queryset=MessageStatusEvent.objects.order_by('occurred_at', 'received_at')),
        ).order_by('created_at')
    )
    return {
        'booking': _booking(booking, now),
        'timezone': BOOKING_TIMEZONE_NAME,
        'planned': bool(tasks),
        'parent_confirmation': parent_confirmation(booking),
        'tasks': [_task(task, now) for task in tasks],
        'messages': [_message(message, booking, now) for message in messages],
        'actions': _actions(booking, messages, now, user, request),
    }


def parent_confirmation(booking):
    """What the parent answered when asked to confirm ``booking``: when, recorded by whom, and why not."""
    reason = booking.not_confirmed_reason
    return {
        'status': booking.parent_confirmation,
        'label': ParentConfirmation(booking.parent_confirmation).label,
        'at': _when(booking.parent_confirmation_at),
        'by': _person(booking.parent_confirmation_by),
        'reason': {'code': reason, 'label': NotConfirmedReason(reason).label} if reason else None,
    }


def _booking(booking, now):
    lead = booking.lead
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'status': booking.status,
        'status_label': booking.get_status_display(),
        'slot': slot_brief(booking.slot, now),
        # Whether its tutor has started it (bookings.lifecycle), read-only.
        'activity_state': activity_state(booking, now),
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'student_name': lead.student_name,
        'parent_name': lead.parent_name,
        'phone': f'{lead.phone_dial_code} {lead.phone_number}',
        'owner_bde': _person(lead.owner_bde),
        'tutor': _person(booking.assigned_tutor),
    }


def _task(task, now):
    return {
        'id': str(task.id),
        'step': task.step,
        'step_label': task.get_step_display(),
        'status': task.status,
        'status_label': task.get_status_display(),
        'resolution': task.resolution,
        'resolution_label': task.get_resolution_display(),
        'owner_role': task.owner_role,
        'owner': _person(task.owner),
        'active_from': _when(task.active_from),
        'due_at': _when(task.due_at),
        'expires_at': _when(task.expires_at),
        # Still open past its target (the PRD's deadline); its window, expires_at, is what closes it as Missed.
        # Never the call: a reminder only, done at its due_at (planner.close_expired).
        'overdue': (
            task.status == TaskStatus.OPEN and task.step != Step.PRE_ACTIVITY_CALL
            and task.due_at is not None and task.due_at < now
        ),
        'resolved_at': _when(task.resolved_at),
        'resolved_by': _person(task.resolved_by),
    }


def _message(message, booking, now):
    step = message.template.step
    return {
        'id': str(message.id),
        'step': step,
        'step_label': Step(step).label,
        'status': message.status,
        'status_label': message.get_status_display(),
        'channel': message.channel,
        'channel_label': message.get_channel_display(),
        'provider': message.provider,
        'recipient_phone': message.recipient_phone,
        # The text as it went, or goes, exactly as WhatsApp shows it; empty while the message is Waiting.
        'text': _whatsapp_text(message),
        'waiting_for': _waiting_for(message, booking, now),
        'scheduled_for': _when(message.scheduled_for),
        'send_before': _when(message.send_before),
        'queued_at': _when(message.queued_at),
        'sent_at': _when(message.sent_at),
        'delivered_at': _when(message.delivered_at),
        'read_at': _when(message.read_at),
        'failed_at': _when(message.failed_at),
        'cancelled_at': _when(message.cancelled_at),
        'attempt_count': message.attempt_count,
        'next_attempt_at': _when(message.next_attempt_at),
        'failure_code': message.failure_code,
        'failure_reason': message.failure_reason,
        'problem': _problem(message),
        'cancel_reason': (
            {'code': message.cancel_reason, 'label': message.get_cancel_reason_display()} if message.cancel_reason else None
        ),
        'created_by': _person(message.created_by),
        'created_at': _when(message.created_at),
        'attempts': [
            {
                'number': attempt.number,
                'outcome': attempt.outcome,
                'outcome_label': attempt.get_outcome_display(),
                'channel': attempt.channel,
                'provider': attempt.provider,
                'started_at': _when(attempt.started_at),
                'finished_at': _when(attempt.finished_at),
                'error_code': attempt.error_code,
                'error_message': attempt.error_message,
                'retryable': attempt.retryable,
                'triggered_by': _person(attempt.triggered_by),
            }
            for attempt in message.attempts.all()
        ],
        # What Meta reported about it, in the order it happened.
        'events': [
            {
                'status': event.status,
                'status_label': event.get_status_display(),
                'provider_status': event.provider_status,
                'occurred_at': _when(event.occurred_at),
                'received_at': _when(event.received_at),
                'error_code': event.error_code,
                'error_message': event.error_message,
            }
            for event in message.status_events.all()
        ],
    }


def _whatsapp_text(message):
    """
    ``message`` in WhatsApp's own formatting -- the text the sending engine
    sends (sending.send_message) and the preview shows, never the template's
    **bold** markers -- from the version and values it was rendered with.
    """
    if message.template_version is None or not message.body:
        return ''
    return whatsapp_message(message.template_version.body, message.variables)


def _waiting_for(message, booking, now):
    """What a Waiting message still needs, as the planner checks it (communications.rendering), in order."""
    if message.status != MessageStatus.WAITING:
        return []
    body = message.template.current_version().body
    return [
        {'code': requirement, 'label': Requirement(requirement).label}
        for requirement, met in requirements(booking, message.template.step, body, now)
        if not met
    ]


def _problem(message):
    if message.status == MessageStatus.PENDING and message.next_attempt_at is not None:
        problem = MessageProblem.RETRYING
    elif message.status != MessageStatus.FAILED:
        return None
    elif message.failure_code == OUTCOME_UNKNOWN:
        problem = MessageProblem.OUTCOME_UNKNOWN
    elif message.is_delivery_failure:
        problem = MessageProblem.DELIVERY_FAILED
    elif message.failure_code == INVALID_RECIPIENT:
        problem = MessageProblem.INVALID_RECIPIENT
    else:
        problem = MessageProblem.REFUSED
    return {'code': problem.value, 'label': problem.label}


def _actions(booking, messages, now, user, request):
    """
    What ``user`` could do now, by the permissions they hold and the rules the
    services apply (the caller already sees the booking, so it is theirs to act
    on): ask for confirmation once while the parent has not answered
    (services.request_confirmation), and record the answer until the slot
    starts or its tutor starts it, whichever comes first
    (booking_service.record_parent_confirmation). The 15-minute call is a task
    only: nothing is recorded on it.
    """
    def holds(permission):
        return user is not None and has_app_permission(user, permission, request)

    upcoming = (
        booking.status == BookingStatus.BOOKED and booking.started_at is None and booking.slot.starts_at > now
    )
    asked = any(message.template.step == Step.CONFIRMATION_REQUEST for message in messages)
    return {
        'request_confirmation': (
            upcoming and booking.parent_confirmation == ParentConfirmation.AWAITING and not asked
            and holds(SEND_COMMUNICATIONS)
        ),
        'record_confirmation': upcoming and holds(RECORD_CONFIRMATION),
    }


def _person(user):
    return {'id': str(user.pk), 'full_name': user.full_name or user.email} if user else None


def _when(value):
    return value.isoformat() if value else None
