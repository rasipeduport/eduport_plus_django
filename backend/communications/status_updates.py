"""
What a provider's webhook reports about a message, applied to it (Phase 2B,
step 5): apply_status_update, matched by the provider's message id (a WAMID
for Meta). Under the message's row lock, so two callbacks for one message
take turns.

* Every status reported is kept once (MessageStatusEvent, with its provider
  timestamp): a callback delivered again changes nothing the second time.
* A message only moves forward -- Queued, Sent, Delivered, Read -- whatever
  order the callbacks come in. A report older than the message's status still
  fills in its moment (sent_at, delivered_at, read_at each keep the earliest
  known), never the status. Delivered and Read mean the message was sent, so
  sent_at takes their moment when no Sent report came first.
* Failed applies to a message the provider accepted but has not delivered
  (Queued or Sent): its error code, and its description saying whether the
  failure is temporary or permanent when the provider says. Nothing is
  retried from here. An acknowledgement that failed delivery hands the
  acknowledgement back to the booking a reschedule made, if that one's own
  was closed because this one had been accepted (planner.release_acknowledgement).
* A Sent report moves the step from ACCEPTED to SENT. Delivered and Read
  never change a task, and a cancelled, missed or open step is never touched.
* A message whose outcome is unknown is never changed by a callback; the
  report is kept beside it, for whoever checks it.
* A status for a message id no message holds yet -- a callback that beat the
  sender to recording the id -- is kept (UnmatchedStatusEvent) and applied
  right after the sender records it, in a transaction of its own
  (reconcile_message, from communications.sending), oldest first, by the
  same rules; a periodic pass (reconcile_unmatched) picks up one recorded just
  after the callback looked, or one whose applying failed, and one never
  matched is purged after UNMATCHED_RETENTION.
"""
import hashlib
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import TextChoices
from django.utils import timezone

from bookings.booking_service import _locked_booking, _set_lock_timeout
from bookings.models import BookingStatus

from . import planner
from .chain import later_bookings
from .models import (
    OUTCOME_UNKNOWN,
    CommunicationTask,
    Message,
    MessageStatus,
    MessageStatusEvent,
    Step,
    TaskResolution,
    TaskStatus,
    UnmatchedStatusEvent,
)
from .providers.base import StatusUpdate

logger = logging.getLogger(__name__)

# How far along each accepted state is: a message never goes back down.
RANK = {MessageStatus.QUEUED: 1, MessageStatus.SENT: 2, MessageStatus.DELIVERED: 3, MessageStatus.READ: 4}
# The moment each reported state fills in.
MOMENTS = {MessageStatus.SENT: 'sent_at', MessageStatus.DELIVERED: 'delivered_at', MessageStatus.READ: 'read_at'}
# How long a status for an unknown message id is kept: Meta stops redelivering
# a callback after a week, and a message records its id within seconds.
UNMATCHED_RETENTION = timedelta(days=7)


class StatusResult(TextChoices):
    APPLIED = 'APPLIED', 'Applied'
    # Older than the message's status: its moment kept, the status not lowered.
    EARLIER = 'EARLIER', 'Older than the status already recorded'
    DUPLICATE = 'DUPLICATE', 'Reported before'
    # No message holds the id yet: kept until one does.
    STORED = 'STORED', 'Kept until its message is known'
    # The outcome is unknown, for someone to check: left as it is.
    PROTECTED = 'PROTECTED', 'Outcome unknown: not changed'
    # Does not fit the message's state (a success after a reported failure, a failure after delivery).
    IGNORED = 'IGNORED', 'Does not apply to the message as it is'


def apply_status_update(provider, update, now=None):
    """Apply ``update`` (a StatusUpdate) from ``provider`` (its name) to its message; returns a StatusResult."""
    now = now or timezone.now()
    with transaction.atomic():
        message = Message.objects.select_for_update(of=('self',)).filter(
            provider=provider, provider_message_id=update.provider_message_id,
        ).first()
        if message is None:
            return _keep_unmatched(provider, update)
        return _apply(message, provider, update, now)


def reconcile_message(message_id, now):
    """
    reconcile for message ``message_id``, in a transaction of its own under
    its row lock: what communications.sending calls once the message's
    provider id is recorded. Returns how many statuses were applied.
    """
    with transaction.atomic():
        message = Message.objects.select_for_update(of=('self',)).select_related('template').filter(
            pk=message_id,
        ).first()
        return reconcile(message, now) if message is not None else 0


def reconcile(message, now):
    """
    ``message`` holds its provider id, and the caller its row lock: apply the
    statuses kept for that id, oldest first, and forget them. Returns how many.
    """
    if not message.provider or not message.provider_message_id:
        return 0
    kept = list(UnmatchedStatusEvent.objects.select_for_update().filter(
        provider=message.provider, provider_message_id=message.provider_message_id,
    ).order_by('occurred_at', 'received_at'))
    for row in kept:
        _apply(message, row.provider, _update_of(row), now, dedupe_key=row.dedupe_key)
        row.delete()
    return len(kept)


def reconcile_unmatched(now=None, limit=500):
    """
    Apply kept statuses whose message id a message now holds -- recorded by a
    sender that committed just after the callback looked, or whose own
    applying failed. A message being finished right now is skipped: its
    sender reconciles it. Each message on its own: one that fails is logged
    and left kept for the next pass, never stopping the rest. Returns how many.
    """
    now = now or timezone.now()
    applied = 0
    ids = UnmatchedStatusEvent.objects.order_by().values_list('provider', 'provider_message_id').distinct()[:limit]
    for provider, provider_message_id in ids:
        try:
            with transaction.atomic():
                message = Message.objects.select_for_update(of=('self',), skip_locked=True).filter(
                    provider=provider, provider_message_id=provider_message_id,
                ).first()
                if message is not None:
                    applied += reconcile(message, now)
        except Exception:  # One message's trouble never stops the rest.
            logger.exception('Statuses kept for a message (...%s) could not be applied; tried again next pass.',
                             provider_message_id[-8:])
    return applied


def purge_unmatched(now=None):
    """Forget kept statuses no message took within UNMATCHED_RETENTION; returns how many."""
    now = now or timezone.now()
    deleted, _per_model = UnmatchedStatusEvent.objects.filter(received_at__lt=now - UNMATCHED_RETENTION).delete()
    return deleted


def _apply(message, provider, update, now, dedupe_key=None):
    """
    ``update`` applied to ``message``, whose row the caller holds; returns a
    StatusResult. ``dedupe_key`` is a kept status's own, so a callback that
    comes again later is still recognised.
    """
    try:
        with transaction.atomic():
            MessageStatusEvent.objects.create(
                message=message,
                provider=provider,
                status=update.status,
                provider_status=update.provider_status,
                occurred_at=update.occurred_at,
                error_code=update.error_code,
                error_message=update.error_message,
                dedupe_key=dedupe_key or _dedupe_key(provider, update),
            )
    except IntegrityError:
        return StatusResult.DUPLICATE
    if message.status == MessageStatus.FAILED and message.failure_code == OUTCOME_UNKNOWN:
        return StatusResult.PROTECTED
    at = update.occurred_at or now
    if update.status == MessageStatus.FAILED:
        return _failed(message, update, at, now)
    if message.status not in RANK:
        return StatusResult.IGNORED
    return _progressed(message, update, at, now)


def _keep_unmatched(provider, update):
    """A status for an id no message holds yet, kept for reconcile -- once, as for an applied one."""
    key = _dedupe_key(provider, update)
    if MessageStatusEvent.objects.filter(dedupe_key=key).exists():
        return StatusResult.DUPLICATE
    try:
        with transaction.atomic():
            UnmatchedStatusEvent.objects.create(
                provider=provider,
                provider_message_id=update.provider_message_id,
                status=update.status,
                provider_status=update.provider_status,
                occurred_at=update.occurred_at,
                error_code=update.error_code,
                error_message=update.error_message,
                error_temporary=update.error_temporary,
                dedupe_key=key,
            )
    except IntegrityError:
        return StatusResult.DUPLICATE
    return StatusResult.STORED


def _update_of(row):
    """The StatusUpdate a kept status was made from."""
    return StatusUpdate(
        provider_message_id=row.provider_message_id,
        status=row.status,
        provider_status=row.provider_status,
        occurred_at=row.occurred_at,
        error_code=row.error_code,
        error_message=row.error_message,
        error_temporary=row.error_temporary,
    )


def _progressed(message, update, at, now):
    """A Sent, Delivered or Read report for an accepted message."""
    message.sent_at = _earliest(message.sent_at, at)
    field = MOMENTS[update.status]
    if field != 'sent_at':
        setattr(message, field, _earliest(getattr(message, field), at))
    moved = RANK[update.status] > RANK[message.status]
    if moved:
        message.status = update.status
    message.save(update_fields=['status', 'sent_at', 'delivered_at', 'read_at', 'updated_at'])
    if update.status == MessageStatus.SENT:
        # The provider has now sent what it had only accepted: the step says so too.
        CommunicationTask.objects.filter(
            pk=message.task_id, status=TaskStatus.DONE, resolution=TaskResolution.ACCEPTED,
        ).update(resolution=TaskResolution.SENT, updated_at=now)
    return StatusResult.APPLIED if moved else StatusResult.EARLIER


def _failed(message, update, at, now):
    """
    A Failed report: only for a message accepted but not yet delivered. An
    acknowledgement that failed delivery gives the booking that replaced its
    booking -- whose own was closed on the strength of it -- its own back.

    Known limitation: the bookings that replaced it are read before each is
    locked, so one a reschedule makes at the very moment this runs keeps its
    acknowledgement closed, and that parent gets none.
    """
    if message.status not in (MessageStatus.QUEUED, MessageStatus.SENT):
        return StatusResult.IGNORED
    message.status = MessageStatus.FAILED
    message.failed_at = at
    message.failure_code = update.error_code
    message.failure_reason = _failure_reason(update)
    message.save(update_fields=['status', 'failed_at', 'failure_code', 'failure_reason', 'updated_at'])
    if message.template.step == Step.ACKNOWLEDGEMENT:
        for booking in later_bookings(message.booking):
            if booking.status == BookingStatus.BOOKED:
                # The booking's slot, then the booking: the order every booking write takes.
                _set_lock_timeout()
                planner.release_acknowledgement(_locked_booking(booking), now)
    return StatusResult.APPLIED


def _failure_reason(update):
    if update.error_temporary is None:
        return update.error_message or 'The provider could not deliver the message.'
    kind = 'Temporary' if update.error_temporary else 'Permanent'
    return f'{kind} delivery failure: {update.error_message or "no description given"}'


def _earliest(current, moment):
    return moment if current is None or moment < current else current


def _dedupe_key(provider, update):
    """One key per reported status: the provider, and a digest of what makes the report itself."""
    key = update.event_key or f'{update.provider_message_id}:{update.status}:{update.occurred_at}'
    return f'{provider}:{hashlib.sha256(key.encode()).hexdigest()}'
