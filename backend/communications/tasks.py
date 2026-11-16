"""
Scheduled jobs for parent WhatsApp messages (Phase 2B, step 4), run by Celery
beat (settings.CELERY_BEAT_SCHEDULE). Thin by design: the work lives in
communications.sending and communications.planner, which these only call.

    dispatch_messages             every minute: Waiting messages checked again
                                  (the fallback for a change no hook sees), then
                                  each due Pending message to an allowed number
                                  handed to send_message -- which makes every
                                  check again under its locks, the safety gate
                                  included; none at all while sending is off or
                                  the provider sends nothing
    recover_stuck_sends           every 5 minutes: messages claimed for more than
                                  5 minutes taken back as unknown
    close_expired_communications  every 5 minutes: tasks whose time ran out
                                  Missed, unsent messages past their window --
                                  a retry left Pending included -- cancelled,
                                  never one whose outcome is unknown
    reconcile_status_updates      every 5 minutes: statuses kept for a message id
                                  a message now holds applied to it; ones no
                                  message took within a week forgotten

Each job runs once at a time across every worker and process: a run holds a
PostgreSQL advisory lock for its job, and a run that cannot take it does
nothing (single_run). Beat's ticks expire when no worker takes them in time
(the schedule's ``expires``), so a worker that was down does not come back to
a pile of runs. One message's trouble is logged and never stops the rest of a
run, nor one part of a run the next. Nothing is sent, or even picked up for
sending, while COMMUNICATIONS_SENDING_ENABLED is off.
"""
import logging
import time
from collections import Counter
from contextlib import contextmanager

from celery import shared_task
from django.db import connection
from django.utils import timezone

from . import planner, sending, status_updates
from .safety import sending_block_for_all

logger = logging.getLogger(__name__)

# The advisory-lock class of these jobs, beside sessions.services (1 student,
# 2 tutor) and accounts.team (3 team); the key is the job's name.
_LOCK_CLASS_JOBS = 4
# Messages one dispatch run hands to the sender at most, and the seconds it
# keeps doing so -- well inside the minute, so runs do not overlap.
DISPATCH_BATCH = 100
DISPATCH_TIME_BUDGET = 45
# Waiting messages one dispatch run checks again at most, per booking type --
# above all a week's bookings can hold (7 days x 15 slots x 3 seats each).
REFRESH_BATCH = 1000


@contextmanager
def single_run(job):
    """
    Whether this run is the only one of ``job`` (yields True), or another holds
    it (False). A session advisory lock, taken without waiting and released at
    the end -- or by PostgreSQL itself if the worker's connection dies.
    """
    if connection.vendor != 'postgresql':
        yield True
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [_LOCK_CLASS_JOBS, job])
        held = cursor.fetchone()[0]
    try:
        yield held
    finally:
        if held:
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s))', [_LOCK_CLASS_JOBS, job])
            except Exception:  # A lost connection releases it anyway.
                logger.exception('Could not release the %s lock.', job)


@shared_task(name='communications.tasks.dispatch_messages')
def dispatch_messages():
    with single_run('dispatch_messages') as only_run:
        if not only_run:
            logger.info('WhatsApp dispatch skipped: another run is in progress.')
            return {'skipped': True}
        return run_dispatch()


def run_dispatch(now=None, time_budget=DISPATCH_TIME_BUDGET):
    """
    One dispatch run (see dispatch_messages); returns what it did -- with
    ``held_back``, the SendBlock, when nothing at all could be sent. ``now``
    fixes the clock for the whole run (tests); otherwise each message is sent
    on the clock as it is then.
    """
    started = time.monotonic()
    summary = {'refreshed': 0, 'errors': 0, 'stopped_early': False, 'held_back': ''}
    try:
        summary['refreshed'] = planner.refresh_waiting(now or timezone.now(), limit=REFRESH_BATCH)
    except Exception:  # The check never stops the sending.
        summary['errors'] += 1
        logger.exception('WhatsApp dispatch: Waiting messages could not be checked again.')
    outcomes = Counter()
    summary['held_back'] = sending_block_for_all() or ''
    due = [] if summary['held_back'] else sending.due_message_ids(now or timezone.now(), limit=DISPATCH_BATCH)
    for message_id in due:
        if time.monotonic() - started > time_budget:
            summary['stopped_early'] = True
            break
        try:
            outcomes[sending.send_message(message_id, now=now).outcome] += 1
        except Exception:  # One message's trouble never stops the batch.
            summary['errors'] += 1
            logger.exception('WhatsApp dispatch: message %s could not be sent.', message_id)
    summary['outcomes'] = dict(outcomes)
    if outcomes or summary['errors'] or summary['refreshed'] or summary['stopped_early']:
        logger.info('WhatsApp dispatch: %s', summary)
    return summary


@shared_task(name='communications.tasks.recover_stuck_sends')
def recover_stuck_sends():
    with single_run('recover_stuck_sends') as only_run:
        if not only_run:
            logger.info('Stuck-send recovery skipped: another run is in progress.')
            return {'skipped': True}
        recovered = sending.recover_stuck_sends(timezone.now())
        if recovered:
            logger.warning('Stuck-send recovery: %d message(s) recovered as unknown.', len(recovered))
        return {'recovered': len(recovered)}


@shared_task(name='communications.tasks.close_expired_communications')
def close_expired_communications():
    with single_run('close_expired_communications') as only_run:
        if not only_run:
            logger.info('Expiry sweep skipped: another run is in progress.')
            return {'skipped': True}
        missed, expired = planner.close_expired(timezone.now())
        if missed or expired:
            logger.info('Expiry sweep: %d task(s) missed, %d message(s) expired.', missed, expired)
        return {'missed': missed, 'expired': expired}


@shared_task(name='communications.tasks.reconcile_status_updates')
def reconcile_status_updates():
    with single_run('reconcile_status_updates') as only_run:
        if not only_run:
            logger.info('Status reconciliation skipped: another run is in progress.')
            return {'skipped': True}
        now = timezone.now()
        applied = purged = 0
        try:
            applied = status_updates.reconcile_unmatched(now)
        except Exception:  # Never stops the purge.
            logger.exception('Status reconciliation: kept statuses could not be applied.')
        try:
            purged = status_updates.purge_unmatched(now)
        except Exception:
            logger.exception('Status reconciliation: old kept statuses could not be forgotten.')
        if applied or purged:
            logger.info('Status reconciliation: %d kept status(es) applied, %d forgotten.', applied, purged)
        return {'applied': applied, 'purged': purged}
