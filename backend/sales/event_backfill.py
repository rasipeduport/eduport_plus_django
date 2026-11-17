"""Webhook backfill: Stripe events the webhook never delivered, found at Stripe and processed late.

The signed webhook stays the primary path. Every ten minutes
(sales.tasks.recover_missed_stripe_events) this lists the events Stripe created
since a stored checkpoint, skips those Django already recorded with a final
outcome, and hands the rest, oldest first, to stripe_gateway.process_event --
the webhook's own handler. That handler records each event once, under a row
lock, so a webhook delivery and a backfill run never both process one event;
payments, installments and classes follow its rules and unique constraints.

The checkpoint (StripeEventCursor) only moves past handled events: it stops at
the earliest event that failed, which the next run retries, and a run that
cannot read Stripe leaves it where it was. Events newer than GRACE are left to
the webhook and Stripe's own retries. The first run looks back
STRIPE_EVENT_BACKFILL_INITIAL_LOOKBACK_HOURS.

Stripe lists events for 30 days only. After a longer outage the run says which
period it can no longer recover (reconcile_stripe_ledger still checks it) and
carries on from the oldest listable event.

Each event comes rendered in the API version current when Stripe created it
(its ``api_version``), whatever the webhook endpoint's version. Billing, refund
and dispute handling re-reads the object by ID; Checkout and PaymentIntent
handling validates the fields it reads, so a payload whose shape differs is
REJECTED for review, never credited. Every log line names the version.
"""
import logging
import time
from collections import Counter
from datetime import datetime, timedelta, timezone as utc

from django.conf import settings
from django.utils import timezone

from . import stripe_gateway
from .payment_models import StripeEvent, StripeEventCursor

logger = logging.getLogger(__name__)

# Only events at least this old are taken; newer ones are still the webhook's.
GRACE = timedelta(minutes=10)
# Each run looks back this far before the checkpoint again; recorded events cost one query.
OVERLAP = timedelta(hours=1)
# Stripe lists events for 30 days.
RETENTION = timedelta(days=30) - timedelta(hours=1)
# Events one run processes at most, and the seconds it keeps doing so (Celery's soft limit is 300).
BATCH = 500
TIME_BUDGET = 240


def _moment(epoch):
    return datetime.fromtimestamp(epoch, utc.utc)


def recorded(event_ids):
    """IDs Django already processed to a final outcome, by the webhook or an earlier run."""
    return set(StripeEvent.objects.filter(pk__in=event_ids).exclude(outcome='RECEIVED').values_list('event_id', flat=True))


def run(now=None, batch=BATCH, time_budget=TIME_BUDGET):
    """One backfill run (see recover_missed_stripe_events); returns what it did."""
    now = now or timezone.now()
    mode = 'live' if settings.STRIPE_LIVE_MODE else 'test'
    cursor = StripeEventCursor.objects.filter(pk=mode).first()
    oldest = now - RETENTION
    if cursor:
        since = cursor.processed_through - OVERLAP
    else:
        since = now - timedelta(hours=settings.STRIPE_EVENT_BACKFILL_INITIAL_LOOKBACK_HOURS)
    until = now - GRACE
    summary = {'mode': mode, 'since': max(since, oldest).isoformat(), 'until': until.isoformat(), 'listed': 0,
               'already_recorded': 0, 'recovered': {}, 'failed': [], 'stopped_early': False}
    if cursor and cursor.processed_through < oldest:
        summary['unrecoverable'] = {'from': cursor.processed_through.isoformat(), 'to': oldest.isoformat()}
        logger.error('Stripe backfill: no complete run since %s and Stripe no longer lists events before %s. Events of that '
                     'period the webhook also missed cannot be recovered here; check it with reconcile_stripe_ledger.',
                     cursor.processed_through.isoformat(), oldest.isoformat())
    elif since < oldest and not cursor:
        logger.warning('Stripe backfill: the initial lookback is capped at Stripe event retention (%s).', oldest.isoformat())
    since = max(since, oldest)
    try:
        pages = stripe_gateway.client().v1.events.list(
            {'limit': 100, 'created': {'gte': int(since.timestamp()), 'lte': int(until.timestamp())}})
        events = [row if isinstance(row, dict) else row.to_dict() for row in pages.auto_paging_iter()]
    except Exception:  # Nothing is processed and the checkpoint stays; the next run tries again.
        logger.exception('Stripe backfill: events could not be listed; the checkpoint stays at %s.',
                         (cursor.processed_through if cursor else since).isoformat())
        if cursor is None:
            StripeEventCursor.objects.create(mode=mode, processed_through=since)
        summary['error'] = 'listing failed'
        return summary
    events = sorted((event for event in events if since.timestamp() <= event['created'] <= until.timestamp()),
                    key=lambda event: (event['created'], event['id']))
    summary['listed'] = len(events)
    done = recorded([event['id'] for event in events])
    started, processed, recovered, versions = time.monotonic(), 0, Counter(), Counter()
    first_failure = stopped_at = None
    for event in events:
        if event['id'] in done:
            summary['already_recorded'] += 1
            continue
        if processed >= batch or time.monotonic() - started > time_budget:
            summary['stopped_early'], stopped_at = True, event['created']
            break
        processed += 1
        version = event.get('api_version') or 'unknown'
        versions[version] += 1
        try:
            record = stripe_gateway.process_event(event, source='BACKFILL')
        except Exception:  # One event's trouble never stops the run; it stays pending.
            logger.exception('Stripe backfill: event %s (%s, API %s) failed and stays pending.', event['id'], event['type'], version)
            summary['failed'].append(event['id'])
            first_failure = event['created'] if first_failure is None else first_failure
            continue
        if record.source != 'BACKFILL':  # The webhook recorded it meanwhile.
            summary['already_recorded'] += 1
            continue
        recovered[record.outcome] += 1
        (logger.warning if record.outcome == 'REJECTED' else logger.info)(
            'Stripe backfill: recovered %s %s %s (API %s) -> %s%s', event['id'], event['type'],
            event.get('data', {}).get('object', {}).get('id', ''), version, record.outcome, f' ({record.error})' if record.error else '')
    # Every event created before the new checkpoint is now recorded.
    processed_through = min([until] + [_moment(epoch) for epoch in (first_failure, stopped_at) if epoch is not None])
    StripeEventCursor.objects.update_or_create(mode=mode, defaults={'processed_through': processed_through})
    summary.update(recovered=dict(recovered), api_versions=dict(versions), processed_through=processed_through.isoformat())
    if recovered or summary['failed'] or summary['stopped_early']:
        (logger.warning if summary['failed'] else logger.info)('Stripe backfill: %s', summary)
    return summary
