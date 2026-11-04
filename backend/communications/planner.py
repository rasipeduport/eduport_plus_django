"""
Keeping a booking's communication in step with the booking (PRD 3.11).
bookings.booking_service and reports.services call these inside the
transaction that changes the booking, so the booking, its tasks and its
messages commit -- or roll back -- together: a booking that was never made
leaves no task or message behind.

    plan_booking         a new booking: its five tasks, its acknowledgement
                         (unless a booking it replaced already sent one) and
                         its confirmed message, Waiting
    parent_confirmed     the confirmation request no longer needed; the
                         confirmed message checked again
    refresh_messages     a tutor assigned, changed or removed, or a Meet link
                         changed: the unsent messages checked again at once
    sender_contact_changed  a BDE's name or phone changed: the unsent
                         messages of their leads' upcoming bookings checked again
    booking_cancelled    open tasks cancelled, unsent messages stopped
    booking_rescheduled  the old booking closed as above, the new one planned
                         from its own slot (the parent confirms again)
    booking_completed    the after-activity message, once
    close_expired        tasks and messages whose time ran out

Checking again makes a message Pending -- re-rendered from the booking as it
is now -- the moment it has everything it needs, and Waiting again if it lost
something; the sending engine checks again before it sends, as a fallback. A
message already handed over is never touched again: it is the history. A
booking made before communications existed has no plan, and these leave it
without one.
"""
from datetime import timedelta

from bookings.models import BOOKING_MODELS, BookingStatus, DiagnosticBooking, Lead

from .models import (
    HANDED_OVER_STATUSES,
    UNSENT_STATUSES,
    CommunicationTask,
    Message,
    MessageCancelReason,
    MessageStatus,
    MessageTemplate,
    OwnerRole,
    Step,
    TaskResolution,
    TaskStatus,
    template_key,
)
from .rendering import booking_values, is_ready, placeholders, render, requirements

# The acknowledgement and the after-activity message go within 3 hours; the
# confirmation request is meant for 12 hours before the start, and the call
# opens 15 minutes before it.
ACKNOWLEDGEMENT_TARGET = timedelta(hours=3)
CONFIRMATION_REQUEST_LEAD = timedelta(hours=12)
CALL_LEAD = timedelta(minutes=15)
AFTER_ACTIVITY_TARGET = timedelta(hours=3)


def booking_field(booking):
    """The column of ``booking``'s table in the communication tables, as a filter."""
    if isinstance(booking, DiagnosticBooking):
        return {'diagnostic_booking': booking}
    return {'demo_booking': booking}


def plan_booking(booking, now, replaces=None):
    """
    Give the new ``booking`` its five tasks and first messages. ``replaces``
    is the booking a reschedule moved it from: when that one -- or one it
    replaced -- already handed its acknowledgement over, no second one goes.
    """
    # Read again: a public booking sets the lead's owner with an UPDATE.
    lead = Lead.objects.select_related('owner_bde').get(pk=booking.lead_id)
    booking.lead = lead
    slot = booking.slot
    owner = lead.owner_bde
    # (active from, due, expires): the call is only actionable from 15 minutes
    # before and stays open until the slot ends; the after-activity step's are
    # set on completion. A booking made within 12 hours of its start has its
    # confirmation request due now, never at a moment already past.
    times = {
        Step.ACKNOWLEDGEMENT: (now, now + ACKNOWLEDGEMENT_TARGET, slot.starts_at),
        Step.CONFIRMATION_REQUEST: (now, max(now, slot.starts_at - CONFIRMATION_REQUEST_LEAD), slot.starts_at),
        Step.PARENT_CONFIRMATION: (now, slot.starts_at, slot.starts_at),
        Step.PRE_ACTIVITY_CALL: (slot.starts_at - CALL_LEAD, slot.starts_at, slot.ends_at),
        Step.AFTER_ACTIVITY: (None, None, None),
    }
    tasks = {
        step: CommunicationTask.objects.create(
            **booking_field(booking),
            step=step,
            owner_role=OwnerRole.BDE if owner else OwnerRole.ADMIN,
            owner=owner,
            active_from=active_from,
            due_at=due_at,
            expires_at=expires_at,
        )
        for step, (active_from, due_at, expires_at) in times.items()
    }
    if replaces is not None and _acknowledged(replaces):
        _resolve(tasks[Step.ACKNOWLEDGEMENT], TaskStatus.DONE, TaskResolution.ALREADY_SENT, now)
    else:
        _add_message(booking, tasks[Step.ACKNOWLEDGEMENT], now, scheduled_for=now, send_before=slot.starts_at)
    _add_message(booking, tasks[Step.PARENT_CONFIRMATION], now, send_before=slot.starts_at)
    return tasks


def parent_confirmed(booking, now, actor=None):
    """
    The parent of ``booking`` has confirmed: asking them is no longer needed,
    and the confirmed message goes as soon as it has everything else.
    """
    field = booking_field(booking)
    CommunicationTask.objects.filter(**field, step=Step.CONFIRMATION_REQUEST, status=TaskStatus.OPEN).update(
        status=TaskStatus.DONE, resolution=TaskResolution.NOT_NEEDED,
        resolved_at=now, resolved_by=actor, updated_at=now,
    )
    _cancel_messages(
        Message.objects.filter(**field, template__step=Step.CONFIRMATION_REQUEST),
        MessageCancelReason.NOT_NEEDED, now,
    )
    refresh_messages(booking, now)


def refresh_messages(booking, now):
    """
    Something ``booking``'s unsent messages need changed -- the parent's
    answer, its tutor, its Meet link: check each of them again now. The caller
    holds the booking's lock (booking_service), so nothing else changes it meanwhile.
    """
    for message in Message.objects.filter(
        **booking_field(booking), status__in=(MessageStatus.WAITING, MessageStatus.PENDING),
    ).select_related('template'):
        refresh_message(message, booking, now)


def sender_contact_changed(bde, now):
    """
    ``bde``'s name or mobile number changed (Team): check again the unsent
    messages of their leads' bookings still to come, which sign with them.
    The messages are locked first, so one a booking change is cancelling at
    the same moment is seen cancelled, never written back.
    """
    for model in BOOKING_MODELS:
        field = 'diagnostic_booking' if model is DiagnosticBooking else 'demo_booking'
        messages = Message.objects.select_for_update(of=('self',)).filter(
            **{f'{field}__lead__owner_bde': bde, f'{field}__status': BookingStatus.BOOKED,
               f'{field}__slot__starts_at__gt': now},
            status__in=(MessageStatus.WAITING, MessageStatus.PENDING),
        ).select_related('template', f'{field}__slot', f'{field}__lead__owner_bde', f'{field}__assigned_tutor')
        for message in messages.order_by('pk'):
            refresh_message(message, getattr(message, field), now)


def booking_cancelled(booking, now):
    """``booking`` was cancelled: nothing more is done or sent for it."""
    _close(booking, now, TaskResolution.BOOKING_CANCELLED, MessageCancelReason.BOOKING_CANCELLED)


def booking_rescheduled(old, new, now):
    """``old`` was moved to ``new``: ``old``'s communication stops and ``new`` gets its own."""
    _close(old, now, TaskResolution.BOOKING_RESCHEDULED, MessageCancelReason.BOOKING_RESCHEDULED)
    plan_booking(new, now, replaces=old)


def booking_completed(booking, now):
    """
    ``booking`` was completed: its after-activity message, written once however
    often this runs, and its steps that can no longer be done closed.
    """
    close_expired(now, booking=booking)
    field = booking_field(booking)
    task = CommunicationTask.objects.filter(**field, step=Step.AFTER_ACTIVITY).first()
    if task is None:
        return None
    if task.status == TaskStatus.OPEN and task.active_from is None:
        task.active_from = now
        task.due_at = now + AFTER_ACTIVITY_TARGET
        task.save(update_fields=['active_from', 'due_at', 'updated_at'])
    existing = Message.objects.filter(**field, template__step=Step.AFTER_ACTIVITY).first()
    return existing or _add_message(booking, task, now, scheduled_for=now)


def close_expired(now, booking=None):
    """Tasks whose time ran out are Missed, and unsent messages past their window cancelled; for ``booking``, or all."""
    tasks = CommunicationTask.objects.filter(status=TaskStatus.OPEN, expires_at__lte=now)
    messages = Message.objects.filter(send_before__lte=now)
    if booking is not None:
        tasks = tasks.filter(**booking_field(booking))
        messages = messages.filter(**booking_field(booking))
    tasks.update(status=TaskStatus.MISSED, resolved_at=now, updated_at=now)
    _cancel_messages(messages, MessageCancelReason.EXPIRED, now)


def refresh_message(message, booking, now, save=True):
    """
    Bring an unsent ``message`` up to date with ``booking``: Pending, with its
    text rendered from the template's current version, when it has everything
    it needs; Waiting, with no text, while it does not. Messages past those two
    states are left as they are.
    """
    if message.status not in (MessageStatus.WAITING, MessageStatus.PENDING):
        return message
    version = message.template.current_version()
    message.recipient_phone = booking.lead.phone_key
    if is_ready(requirements(booking, message.template.step, version.body, now)):
        values = booking_values(booking)
        message.status = MessageStatus.PENDING
        message.template_version = version
        message.body = render(version.body, values)
        message.variables = {name: values[name] for name in placeholders(version.body)}
    else:
        message.status = MessageStatus.WAITING
        message.template_version = None
        message.body = ''
        message.variables = {}
    if save:
        message.save(update_fields=['status', 'template_version', 'body', 'variables', 'recipient_phone', 'updated_at'])
    return message


def add_message(booking, step, now, **fields):
    """
    ``booking``'s message for ``step``, written now (its task must exist): see
    _add_message. For a step the planner does not write itself -- the
    confirmation request the BDE asks for (communications.services).
    """
    task = CommunicationTask.objects.get(**booking_field(booking), step=step)
    return _add_message(booking, task, now, **fields)


# ---------------------------------------------------------------- helpers

def _add_message(booking, task, now, *, scheduled_for=None, send_before=None, created_by=None):
    template = MessageTemplate.objects.get(key=template_key(booking.booking_type, task.step))
    message = Message(
        **booking_field(booking),
        task=task,
        template=template,
        recipient_phone=booking.lead.phone_key,
        scheduled_for=scheduled_for,
        send_before=send_before,
        created_by=created_by,
    )
    refresh_message(message, booking, now, save=False)
    message.save()
    return message


def _close(booking, now, resolution, cancel_reason):
    field = booking_field(booking)
    CommunicationTask.objects.filter(**field, status=TaskStatus.OPEN).update(
        status=TaskStatus.CANCELLED, resolution=resolution, resolved_at=now, updated_at=now,
    )
    _cancel_messages(Message.objects.filter(**field), cancel_reason, now)


def _cancel_messages(messages, reason, now):
    """Cancel those of ``messages`` not yet handed over; the rest are history."""
    messages.filter(status__in=UNSENT_STATUSES).update(
        status=MessageStatus.CANCELLED, cancel_reason=reason, cancelled_at=now, updated_at=now,
    )


def _resolve(task, status, resolution, now, actor=None):
    task.status = status
    task.resolution = resolution
    task.resolved_at = now
    task.resolved_by = actor
    task.save(update_fields=['status', 'resolution', 'resolved_at', 'resolved_by', 'updated_at'])


def _acknowledged(booking):
    """Whether ``booking``, or a booking it replaced, handed its acknowledgement over."""
    field = 'diagnostic_booking' if isinstance(booking, DiagnosticBooking) else 'demo_booking'
    return Message.objects.filter(
        **{f'{field}__in': _chain(booking)},
        template__step=Step.ACKNOWLEDGEMENT,
        status__in=HANDED_OVER_STATUSES,
    ).exists()


def _chain(booking):
    """The ids of ``booking`` and of every booking it replaced, newest first."""
    model = type(booking)
    ids, pk = [], booking.pk
    while pk is not None and pk not in ids:
        ids.append(pk)
        pk = model.objects.filter(pk=pk).values_list('rescheduled_from_id', flat=True).first()
    return ids
