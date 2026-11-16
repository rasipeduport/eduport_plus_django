"""
Sending one Pending WhatsApp message (Phase 2B, step 2): send_message.

It runs in three parts, so no lock is ever held while WhatsApp is being called:

1. The claim, in one transaction. The booking is locked the way every booking
   write locks it -- its slot, then the booking (booking_service.
   _locked_booking) -- and then the message. Under those locks everything is
   checked again: the message is still Pending and nobody is sending it, it is
   due, its booking still wants it (a message left Pending on a cancelled,
   moved or answered booking is cancelled here, so no retry can ever send
   it), it still has all it needs (planner.refresh_message renders it again
   from the booking as it is now, or turns it Waiting), and the safety gate
   lets it through (communications.safety). Only then is it claimed:
   ``claimed_at`` is set and the exact text to send is fixed. A cancellation,
   reschedule or answer committed before the claim has already cancelled the
   message, so it is never sent; one still holding the booking makes the
   claim wait for it, and then see it. A second sender finds the message
   claimed and leaves it.
2. The provider call, outside any transaction, with COMMUNICATIONS_PROVIDER_
   TIMEOUT. While it runs the message stays claimed: the planner neither
   cancels nor re-renders a claimed message.
3. The result, in a second transaction: one MessageAttempt row, and the
   message updated from what the provider said -- Queued or Sent when it
   accepted (and only then the step's task is Done: Accepted for a queued
   message, Sent for a sent one -- even one marked Missed as the session
   started during the call), Failed when it refused.
   An exception -- a timeout, a crash -- means nobody knows whether WhatsApp
   took the message, so it is Failed as "outcome unknown" and never sent
   again by itself. A message whose booking was cancelled, moved or answered
   during the call is closed as the planner would have closed it when the
   provider refused it; one the provider accepted stays the truth: it was sent.
   The planner's cancellations lock a message being sent too (planner.
   _cancel_messages), so this step and a cancellation take turns on it: a
   refused message never ends Failed on a booking that no longer wants it.
   An acknowledgement's outcome is then passed on to the booking a reschedule
   made while it was being sent (planner.acknowledgement_settled).
   This step locks the message and then writes its task -- messages before
   tasks, the order every change takes them in (communications.planner) --
   and writes the task only while it is still open or missed, as the row
   stands then: a step closed after the message was read stays closed. A
   deadlock or lock timeout here can only be a moment's contention, and the
   provider may have taken the message, so recording it is tried again
   (RECORD_TRIES). The statuses the provider reported before the message's id
   was recorded are applied after that, in a transaction of their own
   (status_updates.reconcile_message): they can reach other bookings, and
   trouble there leaves them kept for the periodic pass, never undoing the
   result.

Retries (Step 3). Only a refusal the provider marks retryable is tried
again: after 1, 5 and then 15 minutes, 4 attempts in all, and only while the
next try still falls inside the sending window. Until then the message is
Pending again with ``next_attempt_at`` set (and the last error kept), so the
next try goes through a full claim and every check is made again -- a booking
cancelled, moved or answered meanwhile has its message cancelled, never sent.
A permanent refusal, the last retryable one, or one with no time left before
the window closes is Failed; an unknown outcome is never retried.

Stuck sends (recover_stuck_sends). A message claimed for more than 5 minutes
has a sender that stopped before recording anything -- a worker killed in the
call, a database lost before the result. It is recorded as an unknown attempt
and Failed with OUTCOME_UNKNOWN, for someone to check; never sent again by
itself. If that sender still records its result afterwards, the result is
kept as a further attempt, and an acceptance -- which is never less true --
settles the message as accepted; anything else leaves it unknown. Recovery and
a finishing sender lock the message, so they take turns on it, and recovery
running again finds nothing more to do. The job that calls these every
minute is Step 4.
"""
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Q, TextChoices
from django.db.models.functions import Coalesce
from django.utils import timezone

from bookings.booking_service import BUSY_SQLSTATES, _locked_booking, _set_lock_timeout
from bookings.models import BookingStatus, ParentConfirmation

from . import planner, status_updates
from .formatting import whatsapp_message, whatsapp_number
from .models import (
    OUTCOME_UNKNOWN,
    AttemptOutcome,
    Channel,
    CommunicationTask,
    Message,
    MessageAttempt,
    MessageCancelReason,
    MessageStatus,
    Step,
    TaskResolution,
    TaskStatus,
)
from .providers import get_provider
from .providers.base import OutgoingMessage
from .safety import SendBlock, allowed_recipients, sending_block

logger = logging.getLogger(__name__)

# Failure codes the sender itself records (and OUTCOME_UNKNOWN, models).
INVALID_RECIPIENT = 'INVALID_RECIPIENT'
# How much of an error text is kept.
ERROR_TEXT_LIMIT = 1000
# A retryable refusal is tried again after these, in turn: 4 attempts in all.
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# Claimed this long with no outcome recorded: the sender stopped (recover_stuck_sends).
STUCK_AFTER = timedelta(minutes=5)
# The error code of an attempt recovered that way.
NO_OUTCOME = 'NO_OUTCOME'
# Recording a result that met a deadlock or a lock timeout is tried again,
# this many times in all, pausing RECORD_RETRY_PAUSE seconds longer each time.
RECORD_TRIES = 3
RECORD_RETRY_PAUSE = 0.2


class SendOutcome(TextChoices):
    """What send_message did with a message."""
    QUEUED = 'QUEUED', 'Accepted: queued by the provider'
    SENT = 'SENT', 'Accepted: sent'
    FAILED = 'FAILED', 'Refused by the provider'
    UNKNOWN = 'UNKNOWN', 'Outcome unknown: not sent again'
    CANCELLED = 'CANCELLED', 'No longer needed: its booking was cancelled, moved or answered'
    RETRYING = 'RETRYING', 'Refused for now: tried again later'
    # A result recorded after the send was recovered as unknown (recover_stuck_sends).
    LATE = 'LATE', 'A result after the send was recovered as unknown'
    INVALID_RECIPIENT = 'INVALID_RECIPIENT', 'Not an international WhatsApp number'
    # Nothing done; the message is as it was.
    BLOCKED = 'BLOCKED', 'Held back by the safety settings'
    WAITING = 'WAITING', 'Something it needs is missing'
    NOT_PENDING = 'NOT_PENDING', 'Not Pending, or already being sent'
    NOT_DUE = 'NOT_DUE', 'Not due'
    BUSY = 'BUSY', 'Its booking is busy; try again later'
    NOT_FOUND = 'NOT_FOUND', 'No such message'


@dataclass(frozen=True)
class SendReport:
    outcome: str
    # Why the safety gate held it back (a SendBlock), for BLOCKED.
    block: str = ''


@dataclass(frozen=True)
class _Claim:
    message_id: object
    provider: object
    outgoing: OutgoingMessage
    # The message's claimed_at as this claim set it: still there when the
    # result comes, unless recovery has taken the message back meanwhile.
    claimed_at: object


def due_message_ids(now=None, limit=100):
    """
    The ids of Pending messages due now that nobody is sending, the longest
    due first -- by when it was scheduled, or written when it has no schedule.
    Unless every number is allowed, only those to a number on the allow-list:
    one the safety gate would hold back is never picked up, so it can never
    keep an allowed one out of a batch.
    """
    now = now or timezone.now()
    messages = (
        Message.objects.filter(status=MessageStatus.PENDING, claimed_at__isnull=True)
        .filter(Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now))
        .filter(Q(send_before__isnull=True) | Q(send_before__gt=now))
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
    )
    recipients = allowed_recipients()
    if recipients is not None:
        messages = messages.filter(recipient_phone__in=recipients)
    return list(
        messages.order_by(Coalesce('scheduled_for', 'created_at'), 'created_at', 'pk')
        .values_list('pk', flat=True)[:limit]
    )


def send_message(message_id, now=None, triggered_by=None):
    """
    Try to send message ``message_id`` now; returns a SendReport. ``triggered_by``
    is the person who asked for it, recorded on the attempt (None: the system).
    ``now`` fixes the moment every part goes by (tests); without it each part
    reads the clock as it runs, so the claim is stamped when it is made and
    the result judged when it comes back.
    """
    claim = _claim(message_id, now or timezone.now())
    if isinstance(claim, SendReport):
        return claim
    started_at = timezone.now()
    try:
        result, error = claim.provider.send(claim.outgoing, timeout=settings.COMMUNICATIONS_PROVIDER_TIMEOUT), None
    except Exception as exc:  # The provider may or may not have taken the message.
        result, error = None, exc
    finished_at = timezone.now()
    return _finish(claim, result, error, started_at, finished_at, now or finished_at, triggered_by)


def _claim(message_id, now):
    try:
        with transaction.atomic():
            _set_lock_timeout()
            message = Message.objects.filter(pk=message_id).first()
            if message is None:
                return SendReport(SendOutcome.NOT_FOUND)
            # The booking's slot, then the booking, then the message: the order every booking write takes.
            booking = _locked_booking(message.booking)
            message = Message.objects.select_for_update(of=('self',)).select_related('template').get(pk=message_id)
            if message.status != MessageStatus.PENDING or message.claimed_at is not None:
                return SendReport(SendOutcome.NOT_PENDING)
            reason = _no_longer_needed(message, booking, now, expired=False)
            if reason:
                _cancel(message, reason, now)
                message.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
                if message.template.step == Step.ACKNOWLEDGEMENT:
                    planner.acknowledgement_settled(message, now)
                return SendReport(SendOutcome.CANCELLED)
            if not _due(message, now):
                return SendReport(SendOutcome.NOT_DUE)
            planner.refresh_message(message, booking, now)
            if message.status != MessageStatus.PENDING:
                return SendReport(SendOutcome.WAITING)
            provider = get_provider()
            block = sending_block(message.recipient_phone, provider)
            if block == SendBlock.INVALID_RECIPIENT:
                _fail(message, INVALID_RECIPIENT, 'The parent\'s number is not an international WhatsApp number.', now)
                message.save(update_fields=['status', 'failed_at', 'failure_code', 'failure_reason', 'updated_at'])
                logger.warning('Message %s not sent: invalid recipient.', message.pk)
                return SendReport(SendOutcome.INVALID_RECIPIENT)
            if block:
                return SendReport(SendOutcome.BLOCKED, block)
            version = message.template_version
            outgoing = OutgoingMessage(
                message_id=str(message.pk),
                to=whatsapp_number(message.recipient_phone),
                text=whatsapp_message(version.body, message.variables),
                template_key=message.template_id,
                variables=dict(message.variables),
                provider_ref=dict(version.provider_refs.get(provider.name, {})),
            )
            message.claimed_at = now
            message.provider = provider.name
            message.save(update_fields=['claimed_at', 'provider', 'updated_at'])
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            return SendReport(SendOutcome.BUSY)
        raise
    return _Claim(message_id=message.pk, provider=provider, outgoing=outgoing, claimed_at=now)


def _finish(claim, result, error, started_at, finished_at, now, triggered_by):
    """
    Part 3: record what the provider did with a claimed message, tried again
    on a deadlock or lock timeout; then, when it accepted the message, apply
    the statuses it reported before the message's id was recorded -- apart, so
    trouble there never undoes the result: they stay kept for the periodic pass.
    """
    for number in range(1, RECORD_TRIES + 1):
        try:
            report = _record_result(claim, result, error, started_at, finished_at, now, triggered_by)
            break
        except OperationalError as exc:
            sqlstate = getattr(exc.__cause__, 'sqlstate', None)
            if sqlstate not in BUSY_SQLSTATES or number == RECORD_TRIES:
                if result is not None and result.accepted:
                    logger.error('Message %s: accepted by %s (...%s) but the result could not be recorded; '
                                 'stuck-send recovery will mark it unknown.', claim.message_id, claim.provider.name,
                                 result.provider_message_id[-8:])
                raise
            logger.warning('Message %s: recording the result met a lock conflict (%s); trying again.',
                           claim.message_id, sqlstate)
            time.sleep(RECORD_RETRY_PAUSE * number)
    if result is not None and result.accepted:
        try:
            status_updates.reconcile_message(claim.message_id, now)
        except Exception:  # The result stands; the kept statuses wait for the periodic pass.
            logger.exception('Message %s: statuses reported before its id was recorded are left for the periodic pass.',
                             claim.message_id)
    return report


def _record_result(claim, result, error, started_at, finished_at, now, triggered_by):
    """The result of a claim, in one transaction: an attempt, the message, its task, the bookings that replaced its."""
    provider = claim.provider
    with transaction.atomic():
        message = Message.objects.select_for_update(of=('self',)).select_related('template').get(
            pk=claim.message_id,
        )
        number = message.attempts.count() + 1
        if message.claimed_at != claim.claimed_at:
            return _late_result(message, claim, result, error, started_at, finished_at, now, triggered_by, number)
        outcome, error_code, error_text = _attempt_result(result, error)
        MessageAttempt.objects.create(
            message=message,
            number=number,
            channel=Channel.WHATSAPP,
            provider=provider.name,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            provider_message_id=result.provider_message_id if result else '',
            error_code=error_code,
            error_message=error_text,
            retryable=bool(result and not result.accepted and result.retryable),
            triggered_by=triggered_by,
        )
        message.claimed_at = None
        message.attempt_count = number
        message.channel = Channel.WHATSAPP
        message.provider = provider.name
        if outcome == AttemptOutcome.ACCEPTED:
            report = _accepted(message, result, finished_at)
        elif outcome == AttemptOutcome.UNKNOWN:
            _fail(message, OUTCOME_UNKNOWN,
                  f'{error_text} -- the provider may have taken it: check WhatsApp before sending it again.', finished_at)
            report = SendReport(SendOutcome.UNKNOWN)
        else:
            booking = type(message.booking).objects.get(pk=message.booking.pk)
            reason = _no_longer_needed(message, booking, now)
            retry_at = _retry_at(message, result, number, now)
            if reason:
                _cancel(message, reason, finished_at)
                report = SendReport(SendOutcome.CANCELLED)
            elif retry_at is not None:
                # Pending again: the next try is a full claim, with every check made again.
                message.status = MessageStatus.PENDING
                message.next_attempt_at = retry_at
                message.failure_code, message.failure_reason = error_code, error_text
                report = SendReport(SendOutcome.RETRYING)
            else:
                _fail(message, error_code, _final_reason(result, error_text, number), finished_at)
                report = SendReport(SendOutcome.FAILED)
        message.save()
        if message.template.step == Step.ACKNOWLEDGEMENT:
            planner.acknowledgement_settled(message, now)
    logger.info('Message %s: %s (attempt %s, %s).', message.pk, report.outcome, number, provider.name)
    return report


def recover_stuck_sends(now=None):
    """
    Take back every message claimed for more than STUCK_AFTER with no outcome
    recorded: one unknown attempt each, the message Failed with
    OUTCOME_UNKNOWN, never sent again by itself. Returns the ids recovered. A
    message whose sender is recording its result right now is skipped (locked)
    and needs nothing: it is no longer claimed once that commits.
    """
    now = now or timezone.now()
    stuck_since = now - STUCK_AFTER
    recovered = []
    for message_id in Message.objects.filter(claimed_at__lt=stuck_since).values_list('pk', flat=True):
        try:
            number = _recover(message_id, stuck_since, now)
        except Exception:  # One message's trouble never stops the others' recovery.
            logger.exception('Message %s: stuck send could not be recovered.', message_id)
            continue
        if number is not None:
            recovered.append(message_id)
            logger.warning('Message %s: send recovered as unknown (attempt %s).', message_id, number)
    return recovered


def _recover(message_id, stuck_since, now):
    """Take back ``message_id`` if it is still claimed since before ``stuck_since``; returns its attempt number, or None."""
    with transaction.atomic():
        message = Message.objects.select_for_update(of=('self',), skip_locked=True).select_related(
            'template',
        ).filter(pk=message_id, claimed_at__lt=stuck_since).first()
        if message is None:
            return None
        number = message.attempts.count() + 1
        MessageAttempt.objects.create(
            message=message,
            number=number,
            channel=Channel.WHATSAPP,
            provider=message.provider or 'unknown',
            started_at=message.claimed_at,
            finished_at=now,
            outcome=AttemptOutcome.UNKNOWN,
            error_code=NO_OUTCOME,
            error_message=f'No outcome was recorded within {int(STUCK_AFTER.total_seconds() // 60)} minutes.',
        )
        message.claimed_at = None
        message.attempt_count = number
        message.channel = Channel.WHATSAPP
        _fail(message, OUTCOME_UNKNOWN,
              'The send stopped before its outcome was known -- the provider may have taken it: '
              'check WhatsApp before sending it again.', now)
        message.save()
        if message.template.step == Step.ACKNOWLEDGEMENT:
            planner.acknowledgement_settled(message, now)
    return number


def _late_result(message, claim, result, error, started_at, finished_at, now, triggered_by, number):
    """
    The result of a claim recovery took back meanwhile: kept as a further
    attempt. An acceptance settles a message still unknown as accepted; any
    other result leaves the message as recovery left it.
    """
    outcome, error_code, error_text = _attempt_result(result, error)
    accepted = outcome == AttemptOutcome.ACCEPTED
    MessageAttempt.objects.create(
        message=message,
        number=number,
        channel=Channel.WHATSAPP,
        provider=claim.provider.name,
        started_at=started_at,
        finished_at=finished_at,
        outcome=outcome,
        provider_message_id=result.provider_message_id if result else '',
        error_code=error_code,
        error_message=f'Late result, after the send was recovered as unknown. {error_text}'.strip()[:ERROR_TEXT_LIMIT],
        retryable=False,
        triggered_by=triggered_by,
    )
    message.attempt_count = number
    still_unknown = (message.claimed_at is None and message.status == MessageStatus.FAILED
                     and message.failure_code == OUTCOME_UNKNOWN)
    if accepted and still_unknown:
        _accepted(message, result, finished_at)
        message.save()
        if message.template.step == Step.ACKNOWLEDGEMENT:
            planner.acknowledgement_settled(message, now)
    else:
        message.save(update_fields=['attempt_count', 'updated_at'])
    logger.warning('Message %s: late result %s (attempt %s).', message.pk, outcome, number)
    return SendReport(SendOutcome.LATE)


def _retry_at(message, result, number, now):
    """When a refusal is tried again, or None: only a retryable one, within MAX_ATTEMPTS and the sending window."""
    if not result.retryable or number >= MAX_ATTEMPTS:
        return None
    retry_at = now + RETRY_DELAYS[number - 1]
    if message.send_before is not None and retry_at >= message.send_before:
        return None
    return retry_at


def _attempt_result(result, error):
    """(AttemptOutcome, error code, error text) of a provider call that returned ``result`` or raised ``error``."""
    if error is not None:
        code = 'TIMEOUT' if isinstance(error, TimeoutError) else 'PROVIDER_ERROR'
        return AttemptOutcome.UNKNOWN, code, (str(error) or type(error).__name__)[:ERROR_TEXT_LIMIT]
    if result.accepted:
        return AttemptOutcome.ACCEPTED, '', ''
    return AttemptOutcome.FAILED, result.error_code, result.error_message[:ERROR_TEXT_LIMIT]


def _final_reason(result, error_text, number):
    """A last refusal's reason, saying why it is not tried again when it could have been."""
    if not result.retryable:
        return error_text
    if number >= MAX_ATTEMPTS:
        return f'{error_text} (refused {number} times; not tried again)'.strip()
    return f'{error_text} (no time left to try again before the sending window closes)'.strip()


def _accepted(message, result, at):
    message.status = result.status
    message.provider_message_id = result.provider_message_id
    message.next_attempt_at = None
    if result.status == MessageStatus.QUEUED:
        message.queued_at = at
    else:
        message.sent_at = at
    message.failed_at, message.failure_code, message.failure_reason = None, '', ''
    # The step is done once the provider has the message -- Accepted when it
    # only queued it, Sent when it sent it -- unless the booking closed it
    # meanwhile (cancelled, moved, answered): it stays as it closed. One whose
    # time ran out while the message was being sent (Missed: the session
    # started meanwhile) is done after all, since the message went. Decided
    # on the row as it stands when written, never on a copy read earlier.
    CommunicationTask.objects.filter(pk=message.task_id, status__in=(TaskStatus.OPEN, TaskStatus.MISSED)).update(
        status=TaskStatus.DONE,
        resolution=TaskResolution.ACCEPTED if result.status == MessageStatus.QUEUED else TaskResolution.SENT,
        resolved_at=at, resolved_by=None, updated_at=at,
    )
    return SendReport(SendOutcome.QUEUED if result.status == MessageStatus.QUEUED else SendOutcome.SENT)


def _cancel(message, reason, at):
    message.status = MessageStatus.CANCELLED
    message.cancel_reason = reason
    message.cancelled_at = at


def _fail(message, code, reason, at):
    message.status = MessageStatus.FAILED
    message.next_attempt_at = None
    message.failed_at = at
    message.failure_code = code
    message.failure_reason = reason


def _due(message, now):
    return (
        (message.scheduled_for is None or message.scheduled_for <= now)
        and (message.send_before is None or message.send_before > now)
        and (message.next_attempt_at is None or message.next_attempt_at <= now)
    )


def _no_longer_needed(message, booking, now, expired=True):
    """
    Why the planner would have cancelled ``message`` of ``booking`` by now -- a
    MessageCancelReason -- or ''. Its sending window closing counts only when
    ``expired``: before a claim that is "not due", which the expiry sweep closes.
    """
    if booking.status == BookingStatus.CANCELLED:
        return MessageCancelReason.BOOKING_CANCELLED
    if booking.status == BookingStatus.RESCHEDULED:
        return MessageCancelReason.BOOKING_RESCHEDULED
    if (message.template.step == Step.CONFIRMATION_REQUEST
            and booking.parent_confirmation != ParentConfirmation.AWAITING):
        return MessageCancelReason.NOT_NEEDED
    if expired and message.send_before is not None and message.send_before <= now:
        return MessageCancelReason.EXPIRED
    return ''
