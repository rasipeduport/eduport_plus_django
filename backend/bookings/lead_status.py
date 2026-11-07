"""
A lead's current status: where it stands in the Demo/Diagnostic workflow,
read from its bookings every time -- never stored and never set by hand, so
it cannot disagree with them. The BDE's My Leads and the administrators'
Leads page show the same status (bookings.enquiries, bookings.lead_admin).

One booking decides, of the lead's Diagnostic and Demo bookings together,
the first of these that the lead has:

    booked        booked, its slot not ended: still to come or under way --
                  of several, the soonest (the one "Next booking" shows)
    completed     completed, or started by its tutor and its slot over: the
                  class happened -- of several, the latest; a Demo sent for a
                  Re-Demo (bookings.redemos) shows as Re-Demo required
    not started   booked, its slot over with no start: the class never
                  happened (bookings.lifecycle) and the booking awaits the
                  Admin -- of several, the latest
    cancelled     cancelled, never shown as booked -- of several, the latest
                  cancelled

and the status names its type: "Demo booked", "Diagnostic completed", ...
So a booking to come always shows, and a class that happened is never hidden
by a later cancellation or no-show. A rescheduled booking never decides: the
booking it was moved to does, so a move shows once. With no other booking
the lead is New.

Enrolled would come before all of these, but nothing in the database records
an enrolment against a lead (a Student has no link to the lead it came from),
so it is not derived: an enrolment status needs that link first.
"""
from django.db.models import Case, CharField, DateTimeField, F, IntegerField, OuterRef, Q, Subquery, TextChoices, Value, When

from .models import CONDUCTED, BookingStatus, BookingType, DemoBooking, DiagnosticBooking


class LeadStatus(TextChoices):
    NEW = 'NEW', 'New'
    DIAGNOSTIC_BOOKED = 'DIAGNOSTIC_BOOKED', 'Diagnostic booked'
    DIAGNOSTIC_COMPLETED = 'DIAGNOSTIC_COMPLETED', 'Diagnostic completed'
    DIAGNOSTIC_NOT_STARTED = 'DIAGNOSTIC_NOT_STARTED', 'Diagnostic not started'
    DIAGNOSTIC_CANCELLED = 'DIAGNOSTIC_CANCELLED', 'Diagnostic cancelled'
    DEMO_BOOKED = 'DEMO_BOOKED', 'Demo booked'
    DEMO_COMPLETED = 'DEMO_COMPLETED', 'Demo completed'
    DEMO_REDEMO_REQUIRED = 'DEMO_REDEMO_REQUIRED', 'Re-Demo required'
    DEMO_NOT_STARTED = 'DEMO_NOT_STARTED', 'Demo not started'
    DEMO_CANCELLED = 'DEMO_CANCELLED', 'Demo cancelled'


# Where a booking stands, most relevant first (a higher rank decides).
BOOKED, COMPLETED, NOT_STARTED, CANCELLED = 4, 3, 2, 1
_STATUSES = {
    BookingType.DIAGNOSTIC: {
        BOOKED: LeadStatus.DIAGNOSTIC_BOOKED,
        COMPLETED: LeadStatus.DIAGNOSTIC_COMPLETED,
        NOT_STARTED: LeadStatus.DIAGNOSTIC_NOT_STARTED,
        CANCELLED: LeadStatus.DIAGNOSTIC_CANCELLED,
    },
    BookingType.DEMO: {
        BOOKED: LeadStatus.DEMO_BOOKED,
        COMPLETED: LeadStatus.DEMO_COMPLETED,
        NOT_STARTED: LeadStatus.DEMO_NOT_STARTED,
        CANCELLED: LeadStatus.DEMO_CANCELLED,
    },
}


def _deciding(model, now):
    """The outer lead's bookings in ``model``'s table, the one that decides first: its rank, moment and status."""
    to_come = Q(status=BookingStatus.BOOKED, slot__ends_at__gt=now)
    happened = Q(status__in=CONDUCTED) | Q(status=BookingStatus.BOOKED, started_at__isnull=False)
    ranks = [(to_come, BOOKED), (happened, COMPLETED), (Q(status=BookingStatus.BOOKED), NOT_STARTED)]
    statuses = _STATUSES[model.BOOKING_TYPE]
    # A Demo sent for a Re-Demo ranks as completed, and says so.
    redemo = [When(status=BookingStatus.REDEMO_REQUIRED, then=Value(LeadStatus.DEMO_REDEMO_REQUIRED))]
    return (
        model.objects.filter(lead=OuterRef('pk'))
        .exclude(status=BookingStatus.RESCHEDULED)
        .annotate(
            rank=Case(*(When(when, then=Value(rank)) for when, rank in ranks), default=Value(CANCELLED),
                      output_field=IntegerField()),
            gives=Case(*redemo, *(When(when, then=Value(statuses[rank])) for when, rank in ranks),
                       default=Value(statuses[CANCELLED]), output_field=CharField()),
            # A cancelled booking moved last when it was cancelled; any other is its slot.
            moment=Case(When(status=BookingStatus.CANCELLED, then=F('cancelled_at')), default=F('slot__starts_at'),
                        output_field=DateTimeField()),
            # Bookings to come are taken soonest first, the rest latest first.
            to_come_at=Case(When(to_come, then=F('slot__starts_at')), default=None, output_field=DateTimeField()),
        )
        .order_by('-rank', F('to_come_at').asc(nulls_last=True), '-moment', '-created_at')
    )


def with_status(leads, now):
    """``leads`` annotated with ``lead_status`` (a LeadStatus value) as of ``now``."""
    demo, diagnostic = _deciding(DemoBooking, now), _deciding(DiagnosticBooking, now)
    leads = leads.annotate(
        demo_rank=Subquery(demo.values('rank')[:1]),
        demo_gives=Subquery(demo.values('gives')[:1]),
        demo_moment=Subquery(demo.values('moment')[:1]),
        diagnostic_rank=Subquery(diagnostic.values('rank')[:1]),
        diagnostic_gives=Subquery(diagnostic.values('gives')[:1]),
        diagnostic_moment=Subquery(diagnostic.values('moment')[:1]),
    )
    same_rank = Q(demo_rank=F('diagnostic_rank'))
    demo_decides = (
        Q(demo_rank__gt=F('diagnostic_rank'))
        | (same_rank & Q(demo_rank=BOOKED) & Q(demo_moment__lte=F('diagnostic_moment')))
        | (same_rank & Q(demo_rank__lt=BOOKED) & Q(demo_moment__gte=F('diagnostic_moment')))
    )
    return leads.annotate(lead_status=Case(
        When(demo_gives__isnull=True, diagnostic_gives__isnull=True, then=Value(LeadStatus.NEW)),
        When(diagnostic_gives__isnull=True, then=F('demo_gives')),
        When(demo_gives__isnull=True, then=F('diagnostic_gives')),
        When(demo_decides, then=F('demo_gives')),
        default=F('diagnostic_gives'),
        output_field=CharField(),
    ))


# What a status filter may also name: one stage of either type ("BOOKED" is
# Diagnostic booked or Demo booked, and so on).
STAGES = {
    'BOOKED': (LeadStatus.DIAGNOSTIC_BOOKED, LeadStatus.DEMO_BOOKED),
    'COMPLETED': (LeadStatus.DIAGNOSTIC_COMPLETED, LeadStatus.DEMO_COMPLETED, LeadStatus.DEMO_REDEMO_REQUIRED),
    'NOT_STARTED': (LeadStatus.DIAGNOSTIC_NOT_STARTED, LeadStatus.DEMO_NOT_STARTED),
    'CANCELLED': (LeadStatus.DIAGNOSTIC_CANCELLED, LeadStatus.DEMO_CANCELLED),
}


def statuses_for(value):
    """The statuses a status filter ``value`` (a LeadStatus, or one of STAGES) stands for, or None for neither."""
    if value in LeadStatus.values:
        return (value,)
    return STAGES.get(value)


def status_label(status):
    return LeadStatus(status).label
