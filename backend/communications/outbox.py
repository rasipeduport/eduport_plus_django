"""
The communication outbox: how a business change reaches the parent
communication plan without the plan ever being able to undo the change.

Recording (the business side). The code that changes a booking, a lead or a
BDE's contact details -- bookings.booking_service, reports.services,
bookings.ownership, bookings.student_timezones, bookings.lead_admin,
sales.student_accounts, accounts.team -- calls one of the functions below
inside its own transaction. Each writes one CommunicationEvent row and
nothing else: no planner code runs there, so nothing about communication can
fail, lock or roll back the business write. The row commits with the change
or not at all, so a change that rolled back leaves no event, and a committed
one always leaves its event, whether or not Celery is running.

Applying (the communication side). communications.tasks.
process_communication_events runs every 15 seconds (settings.
CELERY_BEAT_SCHEDULE) and calls run(): each event is claimed (PROCESSING,
one more attempt) in a short transaction of its own, then applied in a
second transaction that first locks its row again -- the planner's writes and
the event's DONE commit together, so an event is either applied once or not
at all. Events sharing a stream (a booking, a lead, a staff account) are
applied in the order they were written: an event is ready only when no
earlier event of its streams is PENDING or PROCESSING. The events that write
a plan (a booking made or moved) carry their lead's stream too, so they and
the lead's owner, time-zone and details changes are applied one after the
other, never side by side: a plan never keeps an owner changed while it was
being written. The other booking events do not wait for their lead's: they
only make the unsent messages follow the details as they are when applied.
A BDE's contact change likewise only re-renders unsent messages. A failed attempt --
a planner that raised, or a transaction that could not COMMIT, its deferred
foreign-key check having waited out the lock timeout for a booking row a
business write holds -- is rolled back, recorded (last_error) in a
transaction of its own and tried again after RETRY_DELAYS; after
MAX_ATTEMPTS it is FAILED, for someone to look at (manage.py
communication_events), and no longer holds its streams back. A claim whose
processor stopped -- a worker killed between the claim and the commit -- is
taken back after STUCK_AFTER (recover_stuck). Rows being applied are locked,
and claims skip locked rows, so no two processors ever apply the same event.

Each event is applied as of its own ``occurred_at`` (the moment the business
change happened), exactly as the planner was called before the outbox, and
reads the booking, lead or account as it is when it is applied: an event
carries ids only, so it can never write back stale details. The planner's
operations are idempotent -- a booking's tasks are unique per step and its
messages per template, and plan_booking leaves a planned booking as it is --
so an event applied twice changes nothing more. What finally goes to a parent
is still decided by the sender (communications.sending), which checks the
booking again under its lock just before every send: a message of a booking
cancelled, moved, answered or started is never sent, however late its events
are applied.

The communication views that show a booking's plan straight after changing
the booking (the parent's answer) or that need its plan (a confirmation
request, a call outcome) first apply that booking's ready events themselves,
best-effort, after the business transaction has committed (apply_ready_for):
the same claim and apply as the job, so nothing there can undo the business
change either, and whatever fails is left to the job.

COMMUNICATIONS_OUTBOX_INLINE (tests only, off by default) applies an event as
soon as it is written, in a savepoint inside the business transaction, so a
test can look at the plan straight after the business call; a planner failure
there is caught and the event left for a retry, as in the real path.
"""
import logging
import time
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Count, Exists, Min, OuterRef
from django.utils import timezone

from .models import (
    PLAN_EVENT_KINDS,
    UNFINISHED_EVENT_STATUSES,
    CommunicationEvent,
    EventKind,
    EventStatus,
    EventSubject,
)

logger = logging.getLogger(__name__)

# A failed attempt is tried again after these, in turn: MAX_ATTEMPTS in all,
# about four and a half hours, before the event is FAILED.
RETRY_DELAYS = (
    timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=3),
)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# Claimed this long without being applied or failed: its processor stopped.
STUCK_AFTER = timedelta(minutes=5)
# Applied events are kept this long, then purged (purge_done).
DONE_RETENTION = timedelta(days=30)
# How long applying an event waits for a row lock before it fails and is retried.
LOCK_TIMEOUT = '5s'
# Events one run applies at most, and the seconds it keeps doing so.
RUN_BATCH = 500
RUN_TIME_BUDGET = 40
ERROR_TEXT_LIMIT = 500


class Outcome:
    DONE = 'done'
    RETRYING = 'retrying'
    FAILED = 'failed'
    # Taken back by recover_stuck meanwhile, or applied elsewhere: nothing done.
    SKIPPED = 'skipped'
    HELD = 'held'


# ---------------------------------------------------------------- recording

def stream_of(subject_type, subject_id):
    """The stream key of one subject: ``DEMO:<uuid>``, ``LEAD:<uuid>``..."""
    return f'{subject_type}:{subject_id}'


def booking_stream(booking):
    return stream_of(booking.booking_type, booking.pk)


def booking_created(booking, at):
    """``booking`` was made (a public booking, a Demo invitation): its plan is to be written, in order with its lead's events."""
    return _record(
        EventKind.BOOKING_CREATED, booking.booking_type, booking.pk, at,
        streams=[booking_stream(booking), stream_of(EventSubject.LEAD, booking.lead_id)],
    )


def parent_confirmed(booking, at, actor=None):
    """The parent of ``booking`` confirmed (recorded by ``actor``)."""
    return _record_booking(EventKind.PARENT_CONFIRMED, booking, at, actor_id=_id(actor))


def booking_cancelled(booking, at):
    return _record_booking(EventKind.BOOKING_CANCELLED, booking, at)


def booking_rescheduled(old, new, at):
    """``old`` was moved to ``new``: ordered on both bookings' streams and, as it plans ``new``, its lead's."""
    return _record(
        EventKind.BOOKING_RESCHEDULED, old.booking_type, old.pk, at,
        streams=[booking_stream(old), booking_stream(new), stream_of(EventSubject.LEAD, new.lead_id)],
        new_booking_id=str(new.pk),
    )


def tutor_changed(booking, at):
    return _record_booking(EventKind.TUTOR_CHANGED, booking, at)


def meet_link_changed(booking, at):
    return _record_booking(EventKind.MEET_LINK_CHANGED, booking, at)


def booking_completed(booking, at):
    return _record_booking(EventKind.BOOKING_COMPLETED, booking, at)


def lead_owner_changed(lead, at):
    return _record_lead(EventKind.LEAD_OWNER_CHANGED, lead, at)


def lead_timezone_changed(lead, at):
    return _record_lead(EventKind.LEAD_TIMEZONE_CHANGED, lead, at)


def lead_details_changed(lead, at):
    return _record_lead(EventKind.LEAD_DETAILS_CHANGED, lead, at)


def sender_contact_changed(account, at):
    """A BDE's name or mobile number changed: the messages they sign are to be checked again."""
    return _record(
        EventKind.SENDER_CONTACT_CHANGED, EventSubject.STAFF, account.pk, at,
        streams=[stream_of(EventSubject.STAFF, account.pk)],
    )


class PlanStatus:
    """Where a booking's plan stands, for the Hub (communications.overview) and the refusals (communications.services)."""
    PLANNED = 'PLANNED'
    # Its event is still to be applied: written in a moment (or once Celery is back).
    PENDING = 'PENDING'
    # The event that was to write it FAILED: for the technical team to retry (manage.py communication_events).
    FAILED = 'FAILED'
    # Never to be written: a booking made before communications existed, or a Re-Demo.
    NOT_PLANNED = 'NOT_PLANNED'


def plan_status(booking, planned=None):
    """
    ``booking``'s PlanStatus; ``planned`` is whether it has tasks, when the
    caller already knows. Only the event that writes its plan counts -- its
    creation, or the reschedule that made it -- never its other events: a
    parent's answer waiting to be applied says nothing about a plan whose
    event failed.
    """
    if planned is None:
        planned = booking.communication_tasks.exists()
    if planned:
        return PlanStatus.PLANNED
    # A reschedule's event writes the plan of the booking it made, never of the one it closed.
    plan_events = CommunicationEvent.objects.filter(
        kind__in=PLAN_EVENT_KINDS, streams__contains=[booking_stream(booking)],
    ).exclude(kind=EventKind.BOOKING_RESCHEDULED, subject_id=booking.pk)
    if plan_events.filter(status__in=UNFINISHED_EVENT_STATUSES).exists():
        return PlanStatus.PENDING
    if plan_events.filter(status=EventStatus.FAILED).exists():
        return PlanStatus.FAILED
    return PlanStatus.NOT_PLANNED


def _record_booking(kind, booking, at, **payload):
    return _record(kind, booking.booking_type, booking.pk, at, streams=[booking_stream(booking)], **payload)


def _record_lead(kind, lead, at):
    return _record(kind, EventSubject.LEAD, lead.pk, at, streams=[stream_of(EventSubject.LEAD, lead.pk)])


def _record(kind, subject_type, subject_id, at, *, streams, **payload):
    event = CommunicationEvent.objects.create(
        kind=kind,
        subject_type=subject_type,
        subject_id=subject_id,
        streams=streams,
        payload={key: value for key, value in payload.items() if value is not None},
        occurred_at=at or timezone.now(),
    )
    if getattr(settings, 'COMMUNICATIONS_OUTBOX_INLINE', False):
        _apply_inline(event)
    return event


def _id(obj):
    return str(obj.pk) if obj is not None else None


# ---------------------------------------------------------------- applying

def ready_events(now):
    """PENDING events due by ``now`` with no earlier unfinished event on any of their streams, oldest first."""
    earlier = CommunicationEvent.objects.filter(
        pk__lt=OuterRef('pk'), status__in=UNFINISHED_EVENT_STATUSES, streams__overlap=OuterRef('streams'),
    )
    return CommunicationEvent.objects.filter(
        ~Exists(earlier), status=EventStatus.PENDING, available_at__lte=now,
    ).order_by('pk')


def claim_next(now=None, streams=None):
    """
    Claim the next ready event -- PROCESSING, one more attempt -- and return
    it, or None when none is ready; with ``streams``, only an event on one of
    them. Rows another processor holds are skipped.
    """
    now = now or timezone.now()
    ready = ready_events(now)
    if streams:
        ready = ready.filter(streams__overlap=streams)
    with transaction.atomic():
        event = ready.select_for_update(of=('self',), skip_locked=True).first()
        if event is None:
            return None
        event.status = EventStatus.PROCESSING
        event.attempts += 1
        event.claimed_at = timezone.now()
        event.save(update_fields=['status', 'attempts', 'claimed_at', 'updated_at'])
    return event


def apply_claimed(event):
    """
    Apply ``event``, claimed by claim_next, in one transaction: its row locked
    again (still PROCESSING under this claim, else SKIPPED), the planner's
    writes in a savepoint, and DONE -- or, if the planner raised, the attempt
    rolled back and the event retried later or FAILED. Returns an Outcome.

    The transaction can also fail when it COMMITs: the tables' foreign keys are
    checked then, and a booking row a business write holds FOR UPDATE makes
    that check wait -- past the lock timeout, or into a deadlock, it fails and
    everything written, DONE included, is rolled back. That attempt is
    recorded failed, in a transaction of its own (_record_commit_failure), like
    any other: retried after its delay, or FAILED after the last.
    """
    try:
        with transaction.atomic():
            _set_lock_timeout()
            locked = CommunicationEvent.objects.select_for_update().filter(
                pk=event.pk, status=EventStatus.PROCESSING, claimed_at=event.claimed_at,
            ).first()
            if locked is None:
                return Outcome.SKIPPED
            return _apply(locked)
    except DatabaseError as exc:
        return _record_commit_failure(event, exc)


def apply_ready_for(booking, limit=10):
    """
    Apply ``booking``'s ready events now, oldest first, as the job would --
    claimed, then applied in a transaction of their own -- for a view that
    shows or needs its plan straight after a business change. Never raises:
    an event that fails is left for the job's retry, and one another
    processor holds, or that waits behind an earlier event, is left to it.
    Call it outside any transaction (after the business write committed).
    Returns how many were applied.
    """
    applied = 0
    try:
        for _ in range(limit):
            event = claim_next(streams=[booking_stream(booking)])
            if event is None:
                break
            applied += apply_claimed(event) == Outcome.DONE
    except Exception:  # Communication never fails the request: the job applies it later.
        logger.exception('Communication events of booking %s could not be applied now; left for the job.', booking.pk)
    return applied


def run(now=None, limit=RUN_BATCH, time_budget=RUN_TIME_BUDGET):
    """
    One processing run: stuck claims taken back, then ready events claimed and
    applied one at a time until none is ready, ``limit`` were applied or the
    time budget is spent. One event's trouble never stops the others.
    Returns what it did.
    """
    started = time.monotonic()
    summary = Counter()
    try:
        recovered = len(recover_stuck(now))
        if recovered:
            summary['recovered'] = recovered
    except Exception:  # Recovery never stops the run.
        summary['errors'] += 1
        logger.exception('Communication events: stuck claims could not be taken back.')
    for _ in range(limit):
        if time.monotonic() - started > time_budget:
            summary['stopped_early'] = 1
            break
        event = claim_next(now)
        if event is None:
            break
        try:
            summary[apply_claimed(event)] += 1
        except Exception:  # Its claim stays; recover_stuck takes it back.
            summary['errors'] += 1
            logger.exception('Communication event %s could not be applied or recorded.', event.pk)
    result = dict(summary)
    if result:
        logger.info('Communication events: %s', result)
    return result


def recover_stuck(now=None, limit=200):
    """
    Take back every claim older than STUCK_AFTER whose row nobody holds -- its
    processor stopped before applying or failing it -- as a failed attempt:
    retried later, or FAILED once it had its last. A claim being applied
    right now is locked, so it is skipped. Returns the ids taken back.
    """
    now = now or timezone.now()
    cutoff = now - STUCK_AFTER
    taken = []
    stuck = CommunicationEvent.objects.filter(status=EventStatus.PROCESSING, claimed_at__lt=cutoff)
    for pk in stuck.order_by('pk').values_list('pk', flat=True)[:limit]:
        with transaction.atomic():
            event = stuck.select_for_update(skip_locked=True).filter(pk=pk).first()
            if event is None:
                continue
            _failed(event, 'Processing stopped before the event was applied (worker lost).', now)
        taken.append(pk)
        logger.warning('Communication event %s: stuck claim taken back.', pk)
    return taken


def requeue(event_ids, force=False, now=None):
    """
    Put FAILED events back to PENDING, with their attempts reset, for an
    operator (manage.py communication_events --retry). Applying one after a
    later event of its streams could undo that event's work (a booking's plan
    written after its cancellation), so an event with any later event of its
    streams that is not FAILED too -- applied, waiting or being applied -- is
    left FAILED unless ``force``. (purge_done keeps every applied event that
    follows a FAILED one, so this never misses one.) Returns (requeued ids,
    refused ids).
    """
    now = now or timezone.now()
    done, refused = [], []
    for pk in event_ids:
        with transaction.atomic():
            event = CommunicationEvent.objects.select_for_update().filter(pk=pk, status=EventStatus.FAILED).first()
            if event is None:
                continue
            later = CommunicationEvent.objects.filter(
                pk__gt=event.pk, streams__overlap=event.streams,
            ).exclude(status=EventStatus.FAILED).exists()
            if later and not force:
                refused.append(pk)
                continue
            event.status, event.attempts, event.available_at, event.claimed_at = EventStatus.PENDING, 0, now, None
            event.save(update_fields=['status', 'attempts', 'available_at', 'claimed_at', 'updated_at'])
            done.append(pk)
    return done, refused


def purge_done(now=None, limit=5000):
    """
    Delete up to ``limit`` events applied more than DONE_RETENTION ago;
    returns how many. One that follows a FAILED event of its streams is kept
    while that one is FAILED: requeue reads it to refuse a replay that would
    undo it.
    """
    now = now or timezone.now()
    failed_before = CommunicationEvent.objects.filter(
        pk__lt=OuterRef('pk'), status=EventStatus.FAILED, streams__overlap=OuterRef('streams'),
    )
    old = CommunicationEvent.objects.filter(
        ~Exists(failed_before), status=EventStatus.DONE, processed_at__lt=now - DONE_RETENTION,
    )
    ids = list(old.order_by('pk').values_list('pk', flat=True)[:limit])
    return CommunicationEvent.objects.filter(pk__in=ids).delete()[0] if ids else 0


def health(now=None):
    """What a monitor wants to see: counts by status, the oldest event still to apply, and stuck claims."""
    now = now or timezone.now()
    counts = dict(
        CommunicationEvent.objects.values_list('status').annotate(count=Count('pk')).order_by()
    )
    oldest = CommunicationEvent.objects.filter(status__in=UNFINISHED_EVENT_STATUSES).aggregate(at=Min('created_at'))['at']
    return {
        'counts': {status: counts.get(status, 0) for status in EventStatus.values},
        'oldest_unfinished_age_seconds': int((now - oldest).total_seconds()) if oldest else None,
        'stuck': CommunicationEvent.objects.filter(
            status=EventStatus.PROCESSING, claimed_at__lt=now - STUCK_AFTER,
        ).count(),
    }


# ---------------------------------------------------------------- helpers

def _apply(event):
    """Apply ``event`` (row held by the caller): the handler in a savepoint, then DONE, or the failure recorded."""
    from .event_handlers import apply_event

    try:
        with transaction.atomic():
            apply_event(event)
    except Exception as exc:
        logger.exception('Communication event %s (%s) failed on attempt %s.', event.pk, event.kind, event.attempts)
        return _failed(event, _describe(exc), timezone.now())
    event.status = EventStatus.DONE
    event.processed_at = timezone.now()
    event.last_error = ''
    event.save(update_fields=['status', 'processed_at', 'last_error', 'updated_at'])
    return Outcome.DONE


def _record_commit_failure(event, exc):
    """
    ``event``'s transaction failed with the database error ``exc`` -- at its
    COMMIT, or while locking its row -- and was rolled back whole, so the event
    is as claim_next left it, still PROCESSING under its claim. Record the
    attempt as failed in a fresh transaction, as _apply does for a planner
    that raised. An event no longer PROCESSING under this claim (its commit
    had gone through after all; stuck-claim recovery took it back) is left
    alone: SKIPPED. If even recording fails the claim stays and recover_stuck
    takes it back, as for a processor that died: ``exc`` is raised again.
    """
    logger.warning('Communication event %s (%s): its transaction failed on attempt %s -- %s',
                   event.pk, event.kind, event.attempts, _describe(exc))
    try:
        with transaction.atomic():
            _set_lock_timeout()
            locked = CommunicationEvent.objects.select_for_update().filter(
                pk=event.pk, status=EventStatus.PROCESSING, claimed_at=event.claimed_at,
            ).first()
            if locked is None:
                return Outcome.SKIPPED
            return _failed(locked, _describe(exc), timezone.now())
    except DatabaseError:
        logger.exception('Communication event %s: the failed attempt could not be recorded; '
                         'stuck-claim recovery takes it back.', event.pk)
        raise exc


def _apply_inline(event):
    """COMMUNICATIONS_OUTBOX_INLINE: apply ``event`` now, inside the caller's transaction, when nothing holds it back."""
    earlier = CommunicationEvent.objects.filter(
        pk__lt=event.pk, status__in=UNFINISHED_EVENT_STATUSES, streams__overlap=event.streams,
    )
    if earlier.exists():
        return Outcome.HELD
    event.status = EventStatus.PROCESSING
    event.attempts += 1
    event.claimed_at = timezone.now()
    event.save(update_fields=['status', 'attempts', 'claimed_at', 'updated_at'])
    return _apply(event)


def _failed(event, error, now):
    """Record a failed attempt of ``event``: retried after its delay, or FAILED after the last."""
    event.last_error = error[:ERROR_TEXT_LIMIT]
    event.claimed_at = None
    if event.attempts >= MAX_ATTEMPTS:
        event.status = EventStatus.FAILED
        outcome = Outcome.FAILED
        logger.error('Communication event %s (%s) FAILED after %s attempts.', event.pk, event.kind, event.attempts)
    else:
        event.status = EventStatus.PENDING
        event.available_at = now + RETRY_DELAYS[max(event.attempts, 1) - 1]
        outcome = Outcome.RETRYING
    event.save(update_fields=['status', 'available_at', 'claimed_at', 'last_error', 'updated_at'])
    return outcome


def _describe(exc):
    """The exception's type and first line only: a database error's detail line can quote row values."""
    first = (str(exc).strip().splitlines() or [''])[0]
    return f'{type(exc).__name__}: {first}' if first else type(exc).__name__


def _set_lock_timeout():
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
