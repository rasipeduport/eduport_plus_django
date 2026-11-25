"""
The earnings ledger's sync (reconcile): every 10 minutes (the Celery beat
schedule) or by hand (manage.py reconcile_tutor_earnings), each class that
counts (earnings.eligibility) and has no earning yet gets one -- priced at the
rate in effect at its scheduled end (earnings.rates.RateBook), with its units,
where the rate came from, and what made it count. Nothing else ever writes an
earning, and no page read does.

In the same run, after the classes, each enrollment whose converting Demo
has its earning gets its Demo Conversion earning (earnings.conversions): the
conversion rate less what the Demo earned, priced when the student enrolled.

A class is earned once, ever: the database refuses a second earning for it
(one per class type and source), the sync takes a lock so two runs never work
side by side, and it inserts nothing that is already there. A reversed earning
stays in the ledger, so its class is never earned again automatically.

The sync only adds. A class that was earned and has since changed -- something
only an edit outside the Hub can do -- is never touched: it is listed for an
administrator to review (earnings.summaries.review_items), who reverses it or
keeps it as earned, with a reason (earnings.corrections); an adjustment alone
leaves it listed. Before pricing has started the sync counts what is waiting
and writes nothing.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from bookings.models import DemoBooking, DiagnosticBooking
from sessions.models import Session

from . import conversions
from .eligibility import activated_at, eligible_bookings, eligible_sessions
from .models import (
    ClassType,
    EarningEntry,
    EarningsSyncRun,
    EntryKind,
    SyncStatus,
    SyncTrigger,
    TutorEarningsPricing,
)
from .rates import RateBook
from .values import hours_between, month_of, priced, try_lock_named

logger = logging.getLogger(__name__)

ONE_CLASS = Decimal('1.00')


@dataclass
class Candidate:
    """A class that counts and has no earning yet."""

    class_type: str
    source_id: object
    tutor_id: object
    start: object
    end: object
    units: Decimal
    details: dict = field(default_factory=dict)


def _iso(moment):
    return moment.isoformat() if moment else None


def _not_earned(class_type):
    return ~Exists(EarningEntry.objects.filter(kind=EntryKind.EARNING, class_type=class_type, source_id=OuterRef('pk')))


def unearned_classes(now):
    """Every class that counts as of ``now`` and has no earning yet, as Candidates."""
    since = activated_at()
    found = []
    sessions = (
        eligible_sessions(Session.objects.filter(end_time__lte=now))
        .filter(_not_earned(ClassType.SESSION))
        .select_related('student', 'started_by')
    )
    for session in sessions:
        found.append(Candidate(
            class_type=ClassType.SESSION, source_id=session.pk, tutor_id=session.tutor_id,
            start=session.start_time, end=session.end_time, units=hours_between(session.start_time, session.end_time),
            details={
                'title': session.title,
                'student_id': str(session.student_id),
                'student_code': session.student.student_code,
                'student_name': session.student.full_name,
                'started_at': _iso(session.started_at),
                'started_by_id': str(session.started_by_id) if session.started_by_id else None,
                'started_by_name': session.started_by.full_name if session.started_by else None,
                'completed_at': _iso(session.completed_at),
                'activated_at': _iso(since),
            },
        ))
    for model, class_type in ((DiagnosticBooking, ClassType.DIAGNOSTIC), (DemoBooking, ClassType.DEMO)):
        bookings = (
            eligible_bookings(model, now=now)
            .filter(_not_earned(class_type))
            .select_related('slot', 'lead', 'report')
        )
        for booking in bookings:
            redemo = getattr(booking, 'redemo_for_id', None)
            found.append(Candidate(
                class_type=class_type, source_id=booking.pk, tutor_id=booking.assigned_tutor_id,
                start=booking.slot.starts_at, end=booking.slot.ends_at, units=ONE_CLASS,
                details={
                    'lead_id': str(booking.lead_id),
                    'student_name': booking.lead.student_name,
                    'started_at': _iso(booking.started_at),
                    'report_id': str(booking.report.pk),
                    'report_submitted_at': _iso(booking.report.submitted_at),
                    'slot_ends_at': _iso(booking.slot.ends_at),
                    'is_redemo': redemo is not None,
                    'redemo_request_id': str(redemo) if redemo else None,
                    'activated_at': _iso(since),
                },
            ))
    return found


def earning_for(candidate, book, run=None):
    """The EARNING for ``candidate``, priced from ``book``; None when it cannot be priced."""
    version, source = book.resolve(candidate.tutor_id, candidate.class_type, candidate.end)
    if version is None or candidate.units <= 0:
        return None
    return EarningEntry(
        kind=EntryKind.EARNING,
        tutor_id=candidate.tutor_id,
        amount=priced(candidate.units, version.amount),
        class_type=candidate.class_type,
        source_id=candidate.source_id,
        class_start=candidate.start,
        class_end=candidate.end,
        month=month_of(candidate.end),
        units=candidate.units,
        rate=version.amount,
        rate_source=source,
        rate_version=version,
        details=candidate.details,
        sync_run=run,
    )


def reconcile(now=None, trigger=SyncTrigger.SCHEDULE):
    """
    One run of the sync, recorded as an EarningsSyncRun and returned -- or
    None when the sync is switched off (TUTOR_EARNINGS_SYNC_ENABLED) or
    another run holds the lock. A run that fails writes nothing but its failure.
    """
    if not getattr(settings, 'TUTOR_EARNINGS_SYNC_ENABLED', True):
        return None
    now = now or timezone.now()
    try:
        with transaction.atomic():
            if not try_lock_named('sync'):
                return None
            candidates = unearned_classes(now) if activated_at() is not None else []
            if not TutorEarningsPricing.objects.exists():
                return EarningsSyncRun.objects.create(
                    started_at=now, finished_at=timezone.now(), status=SyncStatus.WAITING_FOR_PRICING,
                    trigger=trigger, waiting_count=len(candidates),
                )
            run = EarningsSyncRun.objects.create(started_at=now, status=SyncStatus.SUCCEEDED, trigger=trigger)
            book = RateBook.load()
            earnings = [entry for entry in (earning_for(candidate, book, run) for candidate in candidates) if entry]
            # Nothing already there is inserted: a class earned meanwhile is skipped, never doubled.
            EarningEntry.objects.bulk_create(earnings, ignore_conflicts=True)
            # Then the conversions, which read the Demo earnings just written too.
            found = conversions.pending(book)
            converted = [conversions.earning_for(item, run) for item in found if item.state == conversions.READY]
            # Likewise: an enrollment or a Demo converted meanwhile is skipped, never paid twice.
            EarningEntry.objects.bulk_create(converted, ignore_conflicts=True)
            run.earned_count = EarningEntry.objects.filter(sync_run=run).count()
            # Classes with no rate in effect or no booked length, and conversions with no incentive.
            run.skipped_count = (len(candidates) - len(earnings)
                                 + sum(1 for item in found if item.state == conversions.NO_INCENTIVE))
            run.finished_at = timezone.now()
            run.save(update_fields=['earned_count', 'skipped_count', 'finished_at'])
    except Exception as exc:
        logger.exception('Tutor Earnings sync failed')
        EarningsSyncRun.objects.create(
            started_at=now, finished_at=timezone.now(), status=SyncStatus.FAILED, trigger=trigger,
            error=f'{type(exc).__name__}: {exc}'[:2000],
        )
        raise
    if run.skipped_count:
        logger.warning('Tutor Earnings sync: %s eligible class(es) or conversion(s) could not be priced',
                       run.skipped_count)
    return run
