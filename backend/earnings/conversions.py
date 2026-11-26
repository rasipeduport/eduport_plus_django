"""
Demo Conversion: when the student of a Demo that counted towards Tutor
Earnings enrolls, the Demo's tutor earns more. The conversion rate is the
TOTAL a converted Demo earns. The tutor already has the Demo's own earning,
so the Demo Conversion earning is only the difference:

    incentive = conversion rate - what the Demo earned     (₹350 - ₹200 = ₹150)

-- never the rate on top of it. The Demo's own earning is never touched.

Which Demo converts, from relationships only (never a name, phone number or
date matched):

- An enrollment is an initial sale (New or Token, sales.Sale) that enrolled
  its student (sales.enrollment.enroll): run once, under the sale's lock, by
  the first verified tuition payment, whatever its path -- a direct receipt,
  a Stripe webhook, AutoPay -- and never undone (an enrolled sale is
  immutable). An additional purchase is never an enrollment.
- Its enquiry (Sale.enquiry; a lead has at most one initial sale) is the
  lead whose Demo bookings may have converted.
- The converting Demo is ONE booking: the lead's latest Demo -- by slot, a
  Re-Demo included -- that was started before the enrollment and is not
  cancelled. A Re-Demo is taught because an earlier Demo did not convert, so
  the last Demo taught before the enrollment is the one that did. (Enrollment
  picks the student's first tutor differently -- from the latest Demo booked,
  taught or not -- so the two can differ; the student's tutor is never read
  here.) An earlier Demo of the lead never converts, so an enrollment never
  pays two tutors.
- It converts only if that Demo counted: it has its own Demo earning (its
  tutor started it and reported on it, earnings.eligibility), not reversed.
  The incentive goes to that earning's tutor -- the Demo's tutor, whoever
  teaches the student after the enrollment.
- While that Demo may still count (its report, or the sync, to come) the
  conversion waits for it. If it never counts, nothing converts: no earlier
  Demo is paid in its place.

Pricing: the conversion rate in effect for the Demo's tutor -- their own,
else the global one -- at the moment the student enrolled, as a class is
priced at its scheduled end. A rate saved later never reprices it, and an
enrollment before any conversion rate was in effect is not paid (there is no
backfill). When that rate is not above what the Demo earned -- possible only
if the rates changed between the Demo and the enrollment, since a rate change
that would make it so is refused (earnings.rates) -- there is no incentive
and nothing is written: a conversion never lowers what a Demo earned.

When: at once, as soon as both halves stand -- the student enrolled and the
Demo counts, whichever comes second (earnings.hooks: an enrollment, a Demo
report, the end of a slot a Demo was reported in) -- and otherwise at the
next 10-minute sync, the backup (earnings.ledger).

Once: the check and the sync are the only writers, under the same lock. The
database allows one Demo Conversion earning per sale and one per Demo
earning, and checks its sum (migration 0003). Repeated payments, webhooks,
enrollments, checks or sync runs change nothing, and a reversed conversion is
never written again. It counts in the month of the enrollment, in India time.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Exists, OuterRef

from bookings.models import CONDUCTED, BookingStatus, DemoBooking
from sales.payment_models import INITIAL_KINDS, Sale

from .eligibility import activated_at
from .models import ClassType, EarningEntry, EntryKind
from .values import month_of

ONE = Decimal('1.00')

# How an enrollment not converted yet stands.
READY = 'READY'  # Its Demo counted, a conversion rate is in effect and above the Demo's earning: the sync writes it.
WAITING_FOR_DEMO = 'WAITING_FOR_DEMO'  # Its Demo may still count: its report, or the sync, is to come.
NO_INCENTIVE = 'NO_INCENTIVE'  # The conversion rate is not above what the Demo earned.
NO_RATE = 'NO_RATE'  # No conversion rate was in effect when the student enrolled.
NOT_ELIGIBLE = 'NOT_ELIGIBLE'  # Its Demo never counted, or its earning was reversed.


@dataclass
class Conversion:
    """An enrollment not converted yet, its converting Demo, and how it stands."""

    sale: Sale
    demo: DemoBooking
    state: str
    demo_earning: EarningEntry = None
    version: object = None
    source: str = None
    incentive: Decimal = None

    @property
    def tutor_id(self):
        """Whose it is: the Demo earning's tutor, or -- before it has one -- the Demo's."""
        return self.demo_earning.tutor_id if self.demo_earning is not None else self.demo.assigned_tutor_id


def _iso(moment):
    return moment.isoformat() if moment else None


def _converted(sale_ref):
    return EarningEntry.objects.filter(kind=EntryKind.EARNING, class_type=ClassType.DEMO_CONVERSION, source_id=sale_ref)


def unconverted_enrollments():
    """Every initial sale that enrolled its student since the activation and has no Demo Conversion earning."""
    since = activated_at()
    if since is None:
        return Sale.objects.none()
    return (
        Sale.objects.filter(kind__in=INITIAL_KINDS, enquiry__isnull=False, enrolled_at__isnull=False,
                            enrolled_at__gte=since)
        .filter(~Exists(_converted(OuterRef('pk'))))
        .select_related('student')
    )


def converting_demo(sale, demos):
    """
    ``sale``'s converting Demo among ``demos`` (its lead's), or None: the
    latest by slot that was started before the enrollment and is not cancelled.
    """
    taught = [demo for demo in demos if demo.lead_id == sale.enquiry_id and demo.started_at is not None
              and demo.started_at < sale.enrolled_at and demo.status != BookingStatus.CANCELLED]
    return max(taught, key=lambda demo: (demo.slot.starts_at, demo.created_at), default=None)


def _may_still_count(demo, since):
    """
    Whether ``demo``, with no Demo earning yet, may still count: its own tutor
    started it, and its report or the sync is to come.
    """
    return (
        demo.started_by_id is not None and demo.started_by_id == demo.assigned_tutor_id
        and demo.slot.ends_at >= since
        and (demo.status == BookingStatus.BOOKED
             or (demo.status in CONDUCTED and demo.completed_by_id == demo.assigned_tutor_id))
    )


def pending(book, sales=None):
    """
    How every enrollment not converted yet stands (``sales``: a queryset of
    them, every one by default), as Conversions -- an enrollment with no
    converting Demo is not one. ``book`` (earnings.rates.RateBook) prices them.
    """
    since = activated_at()
    if since is None:
        return []
    sales = list(unconverted_enrollments() if sales is None else sales)
    if not sales:
        return []
    demos = list(
        DemoBooking.objects.filter(lead_id__in={sale.enquiry_id for sale in sales}, started_at__isnull=False)
        .exclude(status=BookingStatus.CANCELLED)
        .select_related('slot', 'lead')
    )
    by_lead = defaultdict(list)
    for demo in demos:
        by_lead[demo.lead_id].append(demo)
    chosen = [(sale, converting_demo(sale, by_lead[sale.enquiry_id])) for sale in sales]
    chosen = [(sale, demo) for sale, demo in chosen if demo is not None]
    earnings = {
        entry.source_id: entry
        for entry in EarningEntry.objects.filter(
            kind=EntryKind.EARNING, class_type=ClassType.DEMO, source_id__in=[demo.pk for _sale, demo in chosen],
        ).select_related('reversal', 'conversion')
    }
    found = []
    for sale, demo in chosen:
        earning = earnings.get(demo.pk)
        if earning is None:
            state = WAITING_FOR_DEMO if _may_still_count(demo, since) else NOT_ELIGIBLE
            found.append(Conversion(sale=sale, demo=demo, state=state))
            continue
        if getattr(earning, 'reversal', None) is not None or getattr(earning, 'conversion', None) is not None:
            found.append(Conversion(sale=sale, demo=demo, state=NOT_ELIGIBLE, demo_earning=earning))
            continue
        version, source = book.resolve(earning.tutor_id, ClassType.DEMO_CONVERSION, sale.enrolled_at)
        if version is None:
            found.append(Conversion(sale=sale, demo=demo, state=NO_RATE, demo_earning=earning))
            continue
        incentive = version.amount - earning.amount
        found.append(Conversion(sale=sale, demo=demo, state=READY if incentive > 0 else NO_INCENTIVE,
                                demo_earning=earning, version=version, source=source, incentive=incentive))
    return found


def earning_for(conversion, run=None):
    """The Demo Conversion EARNING for a READY ``conversion``: the incentive, the rate reached, the Demo topped up."""
    sale, demo, earning, version = conversion.sale, conversion.demo, conversion.demo_earning, conversion.version
    student = sale.student
    return EarningEntry(
        kind=EntryKind.EARNING,
        tutor_id=earning.tutor_id,
        amount=conversion.incentive,
        class_type=ClassType.DEMO_CONVERSION,
        source_id=sale.pk,
        class_start=earning.class_start,
        class_end=earning.class_end,
        month=month_of(sale.enrolled_at),
        units=ONE,
        rate=version.amount,
        rate_source=conversion.source,
        rate_version=version,
        converts=earning,
        details={
            'sale_id': str(sale.pk),
            'lead_id': str(sale.enquiry_id),
            'student_id': str(student.pk) if student else None,
            'student_code': student.student_code if student else None,
            'student_name': student.full_name if student else demo.lead.student_name,
            'converted_at': _iso(sale.enrolled_at),
            'demo_booking_id': str(demo.pk),
            'demo_entry_id': str(earning.pk),
            'demo_started_at': _iso(demo.started_at),
            'is_redemo': demo.redemo_for_id is not None,
            'demo_amount': f'{earning.amount:.2f}',
            'demo_rate': f'{earning.rate:.2f}',
            'conversion_rate': f'{version.amount:.2f}',
            'incentive': f'{conversion.incentive:.2f}',
            'final_amount': f'{earning.amount + conversion.incentive:.2f}',
            'activated_at': _iso(activated_at()),
        },
        sync_run=run,
    )
