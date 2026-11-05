"""
Keeping a booking's communication in step with the booking (PRD 3.11).
bookings.booking_service and reports.services call these inside the
transaction that changes the booking, so the booking, its tasks and its
messages commit -- or roll back -- together: a booking that was never made
leaves no task or message behind.

    plan_booking         a new booking: its five tasks, its acknowledgement
                         (unless a booking it replaced had one accepted) and
                         its confirmed message, Waiting
    parent_confirmed     the confirmation request no longer needed; the
                         confirmed message checked again
    refresh_messages     a tutor assigned, changed or removed, or a Meet link
                         changed: the unsent messages checked again at once
    sender_contact_changed  a BDE's name or phone changed: the unsent
                         messages of their leads' upcoming bookings checked again
    refresh_waiting      every minute (communications.tasks): Waiting messages
                         of bookings still to come checked again -- the
                         fallback for a change no hook sees
    acknowledgement_settled  an acknowledgement sent as its booking was moved
                         has its outcome: the booking that replaced it then
                         skips its own (accepted), sends it (refused), or keeps
                         waiting for someone to check (unknown)
    booking_cancelled    open tasks cancelled, unsent messages stopped
    booking_rescheduled  the old booking closed as above, the new one planned
                         from its own slot (the parent confirms again)
    booking_completed    the after-activity message, once
    close_expired        tasks and messages whose time ran out

Checking again makes a message Pending -- re-rendered from the booking as it
is now -- the moment it has everything it needs, and Waiting again if it lost
something; the sending engine checks again before it sends, as a fallback. A
message already handed over is never touched again: it is the history. Nor is
one a sender is handing over right now (claimed_at): the sender records what
the provider did and then closes it as the booking now requires
(communications.sending). A booking made before communications existed has no
plan, and these leave it without one.

Locks: every change here takes a booking's message rows before its task rows,
each in id order -- the order the sender takes them in -- so no two changes,
nor a change and a sender, ever wait on each other in a circle. The jobs and
the sender change messages without the booking's lock, so a message is
always read under its own row lock before it is written.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from bookings.models import BOOKING_MODELS, BookingStatus, DiagnosticBooking, Lead

from .chain import EarlierAcknowledgement, earlier_acknowledgement, later_bookings
from .models import (
    DELIVERY_FAILURES,
    HANDED_OVER_STATUSES,
    OUTCOME_UNKNOWN,
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

logger = logging.getLogger(__name__)

# The acknowledgement and the after-activity message go within 3 hours; the
# confirmation request is meant for 12 hours before the start, and the call
# opens 15 minutes before it.
ACKNOWLEDGEMENT_TARGET = timedelta(hours=3)
CONFIRMATION_REQUEST_LEAD = timedelta(hours=12)
CALL_LEAD = timedelta(minutes=15)
AFTER_ACTIVITY_TARGET = timedelta(hours=3)
# An after-activity message still unsent this long after completion is
# expired, never sent late -- one written while sending was off included.
AFTER_ACTIVITY_WINDOW = timedelta(hours=24)
# Waiting messages refresh_waiting checks again in one transaction.
REFRESH_CHUNK = 50


def booking_field(booking):
    """The column of ``booking``'s table in the communication tables, as a filter."""
    if isinstance(booking, DiagnosticBooking):
        return {'diagnostic_booking': booking}
    return {'demo_booking': booking}


def plan_booking(booking, now):
    """
    Give the new ``booking`` its five tasks and first messages. A booking a
    reschedule made gets no acknowledgement of its own when one for a booking
    it replaced was accepted; while that one is being sent, or its outcome is
    unknown, its own waits (rendering.Requirement.EARLIER_ACKNOWLEDGEMENT).
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
    if earlier_acknowledgement(booking) == EarlierAcknowledgement.ACCEPTED:
        _resolve(tasks[Step.ACKNOWLEDGEMENT], TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED, now)
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
    _lock_unsent(booking)
    _cancel_messages(
        Message.objects.filter(**field, template__step=Step.CONFIRMATION_REQUEST),
        MessageCancelReason.NOT_NEEDED, now,
    )
    _update_tasks(
        CommunicationTask.objects.filter(**field, step=Step.CONFIRMATION_REQUEST, status=TaskStatus.OPEN),
        status=TaskStatus.DONE, resolution=TaskResolution.NOT_NEEDED,
        resolved_at=now, resolved_by=actor, updated_at=now,
    )
    refresh_messages(booking, now)


def refresh_messages(booking, now):
    """
    Something ``booking``'s unsent messages need changed -- the parent's
    answer, its tutor, its Meet link: check each of them again now. The caller
    holds the booking's lock (booking_service), but the jobs and the sender
    change messages without it: each is locked first, in id order, and
    checked as it is then -- one cancelled meanwhile is left cancelled.
    """
    with transaction.atomic():
        messages = Message.objects.select_for_update(of=('self',)).filter(
            **booking_field(booking), status__in=(MessageStatus.WAITING, MessageStatus.PENDING),
        ).select_related('template').order_by('pk')
        for message in messages:
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
    plan_booking(new, now)


def refresh_waiting(now, limit=1000):
    """
    Check again the Waiting messages of bookings still to come -- booked
    ones before their window closes, completed ones' after-activity message:
    the fallback for a change no hook sees, such as a mobile number edited in
    the Django admin or a row changed by hand. The soonest due come first,
    ``limit`` of them per type, in short transactions of REFRESH_CHUNK, so a
    booking change never waits long behind this. Each is locked first,
    skipping one a booking change holds (that change refreshes it itself), so
    nothing a change is closing is written back; only a message that changed
    is saved, and one that cannot be checked is logged and skipped, never
    stopping the rest. Returns how many became Pending.
    """
    ready = 0
    for model in BOOKING_MODELS:
        field = 'diagnostic_booking' if model is DiagnosticBooking else 'demo_booking'
        waiting = Message.objects.filter(
            Q(send_before__isnull=True) | Q(send_before__gt=now),
            status=MessageStatus.WAITING, claimed_at__isnull=True,
            **{f'{field}__status__in': (BookingStatus.BOOKED, BookingStatus.COMPLETED)},
        )
        ids = list(waiting.order_by('send_before', 'pk').values_list('pk', flat=True)[:limit])
        for start in range(0, len(ids), REFRESH_CHUNK):
            ready += _refresh_chunk(waiting, field, ids[start:start + REFRESH_CHUNK], now)
    return ready


def acknowledgement_settled(message, now):
    """
    ``message``, an acknowledgement, has just had its outcome recorded
    (communications.sending). The bookings that replaced its booking -- moved
    while it was being sent -- act on it now: when it was accepted, their own
    acknowledgement is not needed; otherwise theirs is checked again, and goes
    once the earlier one is known not accepted, or keeps waiting while its
    outcome is unknown. Their messages are locked first, so one their own
    booking's change is closing at the same moment is seen closed.

    Known limitation: the chain is read, not locked as a whole, so a booking a
    reschedule makes at the very moment this runs is not among them -- its
    acknowledgement then waits until its step is Missed.
    """
    for booking in later_bookings(message.booking):
        acks = Message.objects.select_for_update(of=('self',)).filter(
            **booking_field(booking), template__step=Step.ACKNOWLEDGEMENT, claimed_at__isnull=True,
            status__in=(MessageStatus.WAITING, MessageStatus.PENDING),
        ).select_related('template')
        for ack in acks:
            if message.status in HANDED_OVER_STATUSES:
                _cancel_messages(Message.objects.filter(pk=ack.pk), MessageCancelReason.NOT_NEEDED, now)
                CommunicationTask.objects.filter(pk=ack.task_id, status=TaskStatus.OPEN).update(
                    status=TaskStatus.DONE, resolution=TaskResolution.ALREADY_ACKNOWLEDGED,
                    resolved_at=now, updated_at=now,
                )
            else:
                refresh_message(ack, booking, now)


def release_acknowledgement(booking, now):
    """
    ``booking``'s acknowledgement step was closed because one for a booking it
    replaced had been accepted -- and that one has since failed delivery: the
    parent may never have had it. Reopen the step and give it its message
    back (a new one, or the one cancelled as not needed), which goes as soon
    as nothing earlier in the chain is still being sent or of unknown outcome
    (rendering.Requirement.EARLIER_ACKNOWLEDGEMENT) -- an unknown one keeps it
    Waiting, for someone to check. Only for a booking still to come; the
    caller holds its lock (communications.status_updates). Returns whether it
    released anything.
    """
    if booking.status != BookingStatus.BOOKED or booking.slot.starts_at <= now:
        return False
    field = booking_field(booking)
    message = Message.objects.select_for_update(of=('self',)).select_related('template').filter(
        **field, template__step=Step.ACKNOWLEDGEMENT,
    ).first()
    task = CommunicationTask.objects.select_for_update().filter(**field, step=Step.ACKNOWLEDGEMENT).first()
    if task is None or (task.status, task.resolution) != (TaskStatus.DONE, TaskResolution.ALREADY_ACKNOWLEDGED):
        return False
    task.status, task.resolution, task.resolved_at, task.resolved_by = TaskStatus.OPEN, '', None, None
    task.save(update_fields=['status', 'resolution', 'resolved_at', 'resolved_by', 'updated_at'])
    if message is None:
        _add_message(booking, task, now, scheduled_for=now, send_before=booking.slot.starts_at)
    elif (message.status == MessageStatus.CANCELLED and message.cancel_reason == MessageCancelReason.NOT_NEEDED
          and not message.provider_message_id):
        # Never handed over -- it was closed waiting -- so it can simply wait again.
        message.status, message.cancel_reason, message.cancelled_at = MessageStatus.WAITING, '', None
        message.scheduled_for = now
        refresh_message(message, booking, now, save=False)
        message.save()
    return True


def booking_completed(booking, now):
    """
    ``booking`` was completed: its after-activity message, written once however
    often this runs, and its steps that can no longer be done closed. The
    message goes within AFTER_ACTIVITY_WINDOW of completion or not at all.
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
    return existing or _add_message(booking, task, now, scheduled_for=now, send_before=now + AFTER_ACTIVITY_WINDOW)


def close_expired(now, booking=None):
    """
    Tasks whose time ran out are Missed, and unsent messages past their window
    -- a retry left Pending included -- cancelled as expired; for ``booking``,
    or all. A message being sent, or one whose outcome is unknown, is left as
    it is (_cancel_messages). Returns (tasks missed, messages expired).
    """
    tasks = CommunicationTask.objects.filter(status=TaskStatus.OPEN, expires_at__lte=now)
    messages = Message.objects.filter(send_before__lte=now)
    if booking is not None:
        tasks = tasks.filter(**booking_field(booking))
        messages = messages.filter(**booking_field(booking))
    # Its own transaction when the scheduled job calls it; part of the booking's when completion does.
    with transaction.atomic():
        expired = _cancel_messages(messages, MessageCancelReason.EXPIRED, now)
        return _update_tasks(tasks, status=TaskStatus.MISSED, resolved_at=now, updated_at=now), expired


def refresh_message(message, booking, now, save=True):
    """
    Bring an unsent ``message`` up to date with ``booking``: Pending, with its
    text rendered from the template's current version, when it has everything
    it needs; Waiting, with no text, while it does not. Messages past those two
    states, and one a sender is handing over, are left as they are.
    """
    if message.status not in (MessageStatus.WAITING, MessageStatus.PENDING) or message.claimed_at is not None:
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


def _refresh_chunk(waiting, field, ids, now):
    """refresh_waiting for the messages ``ids`` among ``waiting``, in one transaction; returns how many became Pending."""
    ready = 0
    with transaction.atomic():
        messages = waiting.select_for_update(of=('self',), skip_locked=True).filter(pk__in=ids).select_related(
            'template', f'{field}__slot', f'{field}__lead__owner_bde', f'{field}__assigned_tutor',
        ).order_by('send_before', 'pk')
        for message in messages:
            try:
                with transaction.atomic():
                    before = (message.status, message.body, message.variables, message.template_version_id,
                              message.recipient_phone)
                    refresh_message(message, getattr(message, field), now, save=False)
                    after = (message.status, message.body, message.variables, message.template_version_id,
                             message.recipient_phone)
                    if after != before:
                        message.save(update_fields=[
                            'status', 'template_version', 'body', 'variables', 'recipient_phone', 'updated_at',
                        ])
                        ready += message.status == MessageStatus.PENDING
            except Exception:  # One message's trouble never stops the rest.
                logger.exception('Waiting message %s could not be checked again.', message.pk)
    return ready


def _lock_unsent(booking):
    """Lock ``booking``'s messages not yet handed over, in id order, before a change writes any of them or a task."""
    list(Message.objects.select_for_update(of=('self',)).filter(
        **booking_field(booking), status__in=UNSENT_STATUSES,
    ).order_by('pk').values_list('pk', flat=True))


def _update_tasks(tasks, **fields):
    """Write ``fields`` to ``tasks`` (a queryset), locked first in id order; returns how many were written."""
    locked = list(tasks.select_for_update(of=('self',)).order_by('pk').values_list('pk', flat=True))
    return tasks.filter(pk__in=locked).update(**fields)


def _close(booking, now, resolution, cancel_reason):
    field = booking_field(booking)
    _cancel_messages(Message.objects.filter(**field), cancel_reason, now)
    _update_tasks(
        CommunicationTask.objects.filter(**field, status=TaskStatus.OPEN),
        status=TaskStatus.CANCELLED, resolution=resolution, resolved_at=now, updated_at=now,
    )


def _cancel_messages(messages, reason, now):
    """
    Cancel those of ``messages`` not yet handed over; the rest are history. One
    a sender is handing over is left to it (communications.sending) -- but
    locked first, with the rest: a sender recording its outcome at this moment
    holds it, so this waits for that and then cancels it if it failed, and a
    sender that records its outcome after this waits for this to commit, and
    then sees why it is no longer needed. Either way a refused message never
    ends Failed -- retryable -- on a booking that no longer wants it.

    A message whose outcome is unknown is not cancelled either: the provider
    may have taken it, so it stays as it is, for someone to check -- and a
    booking that replaced its booking never sends a second acknowledgement
    on the strength of a cancellation that would hide that. Nor is a delivery
    failure (DELIVERY_FAILURES): the provider took it and could not deliver
    it, which stays on record for the BDE to follow up.
    """
    unsent = messages.filter(status__in=UNSENT_STATUSES).exclude(
        status=MessageStatus.FAILED, failure_code=OUTCOME_UNKNOWN,
    ).exclude(DELIVERY_FAILURES)
    locked = list(unsent.select_for_update(of=('self',)).order_by('pk').values_list('pk', flat=True))
    return unsent.filter(pk__in=locked, claimed_at__isnull=True).update(
        status=MessageStatus.CANCELLED, cancel_reason=reason, cancelled_at=now, updated_at=now,
    )


def _resolve(task, status, resolution, now, actor=None):
    task.status = status
    task.resolution = resolution
    task.resolved_at = now
    task.resolved_by = actor
    task.save(update_fields=['status', 'resolution', 'resolved_at', 'resolved_by', 'updated_at'])
