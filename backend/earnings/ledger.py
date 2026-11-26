"""
The earnings ledger's sync (reconcile): every 10 minutes (the Celery beat
schedule) or by hand (manage.py reconcile_tutor_earnings), each class that
counts (earnings.eligibility) and has no earning yet gets one -- priced at the
rate in effect at its scheduled end (earnings.rates.RateBook), with its units,
where the rate came from, and what made it count. No page read ever writes an
earning.

In the same run, after the classes, each enrollment whose converting Demo
has its earning gets its Demo Conversion earning (earnings.conversions): the
conversion rate less what the Demo earned, priced when the student enrolled.

A Demo conversion does not wait for the sync: record_conversion checks one
lead at once -- when its student enrolls, and when its Demo's report is in
(earnings.hooks) -- and writes the converting Demo's earning, if the sync has
not yet, and the conversion: the very rows the sync would write, priced the
same way. The sync and the check are the only writers of an earning; they take
the same lock, and the sync stays the backup for anything the check missed.

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
from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from bookings.models import CONDUCTED, DemoBooking, DiagnosticBooking
from sales.payment_models import INITIAL_KINDS, Sale
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
from .values import hours_between, lock_named, month_of, priced, try_lock_named

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
        found += [booking_candidate(booking, class_type, since) for booking in bookings]
    return found


def booking_candidate(booking, class_type, since):
    """The Candidate of an eligible ``booking`` (with its slot, lead and report) not earned yet."""
    redemo = getattr(booking, 'redemo_for_id', None)
    return Candidate(
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
    )


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


# How long the conversion check waits for a sync under way before leaving the lead to the next sync.
CHECK_LOCK_TIMEOUT = '5s'


@dataclass
class ConversionCheck:
    """
    What one lead's conversion check found: its Demo Conversion earning, if it
    has one now, and -- when the converting Demo's report is in but its slot has
    not ended, so it cannot count yet -- the moment to look again.
    """

    conversion: object = None
    due_at: object = None


def _conversion_of_lead(lead_id):
    return (EarningEntry.objects
            .filter(kind=EntryKind.EARNING, class_type=ClassType.DEMO_CONVERSION,
                    source_id__in=Sale.objects.filter(enquiry_id=lead_id).values('pk'))
            .first())


def record_conversion(lead_id, now=None):
    """
    The conversion check of one lead, at once (earnings.hooks): if its
    student has enrolled and the converting Demo counts (earnings.conversions),
    write the Demo's earning -- when the sync has not -- and the Demo Conversion
    earning, exactly as the sync would. Under the sync's lock, waiting at most
    CHECK_LOCK_TIMEOUT for a sync under way (then the database refuses to wait
    and the error is the caller's: the next sync does it instead). Nothing is
    ever written twice: what is already there is skipped. Off with the sync
    (TUTOR_EARNINGS_SYNC_ENABLED), and before activation or pricing. Returns a
    ConversionCheck.
    """
    if not getattr(settings, 'TUTOR_EARNINGS_SYNC_ENABLED', True):
        return ConversionCheck()
    # Most Demo reports have no enrollment behind them yet: those never wait for the sync's lock. (An
    # enrollment committed just after this asks for its own check.)
    if not Sale.objects.filter(enquiry_id=lead_id, kind__in=INITIAL_KINDS, enrolled_at__isnull=False).exists():
        return ConversionCheck()
    now = now or timezone.now()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{CHECK_LOCK_TIMEOUT}'")
        lock_named('sync')
        since = activated_at()
        if since is None or not TutorEarningsPricing.objects.exists():
            return ConversionCheck()
        sales = conversions.unconverted_enrollments().filter(enquiry_id=lead_id)
        book = RateBook.load()
        found = conversions.pending(book, sales.all())
        item = found[0] if found else None
        if item is not None and item.state == conversions.WAITING_FOR_DEMO:
            booking = (eligible_bookings(DemoBooking, DemoBooking.objects.filter(pk=item.demo.pk), now=now)
                       .filter(_not_earned(ClassType.DEMO))
                       .select_related('slot', 'lead', 'report')
                       .first())
            if booking is None:
                # Reported, but its slot is still on: it counts once the slot ends.
                reported = item.demo.status in CONDUCTED and item.demo.slot.ends_at > now
                return ConversionCheck(due_at=item.demo.slot.ends_at if reported else None)
            earning = earning_for(booking_candidate(booking, ClassType.DEMO, since), book)
            if earning is None:
                return ConversionCheck()
            EarningEntry.objects.bulk_create([earning], ignore_conflicts=True)
            found = conversions.pending(book, sales.all())
            item = found[0] if found else None
        if item is not None and item.state == conversions.READY:
            EarningEntry.objects.bulk_create([conversions.earning_for(item)], ignore_conflicts=True)
    return ConversionCheck(conversion=_conversion_of_lead(lead_id))
