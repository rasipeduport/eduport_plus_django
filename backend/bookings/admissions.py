"""
The administrators' Admissions Dashboard (GET /api/admissions/dashboard/):
the admissions pipeline at a glance. Over a span of Indian dates, the leads
that came in and where each stands now, and the Demo and Diagnostic bookings
for classes in it; then, whatever the span, today's bookings, what awaits an
administrator, the latest leads and the latest admissions activity.

Everything is read from the leads, the bookings and the activity log as they
stand -- nothing is stored or estimated here -- and each count that opens a
list counts what that list shows: a pipeline stage is the Leads page's status
filter (lead_status.STAGES) over the same dates, and each booking action one
of the Bookings pages' filters (coordination.filtered). Enrolments are not
counted: nothing links a student to the lead they came from (lead_status).
"""
from collections import Counter
from datetime import timedelta

from django.db.models import Count, Q

from activity.models import ActivityLog
from activity.serializers import ActivityLogSerializer
from core.querysets import scope_activity

from . import coordination, lead_admin, redemos
from .lead_status import STAGES, LeadStatus, with_status
from .models import BOOKING_MODELS, HOLDS_SEAT, BookingStatus, Lead, ParentConfirmation, ReDemoStatus
from .scheduling import BOOKING_TIMEZONE_NAME, indian_today

# The span a dashboard opened without dates shows: the last seven Indian days, today included.
DEFAULT_DAYS = 7
# The longest span it reads at once.
MAX_DAYS = 366
TODAY_ROWS = 12
RECENT_ROWS = 6
ACTIVITY_ROWS = 8

# The stages a lead moves through, in that order. Completed takes in a Demo
# sent for a Re-Demo; Not started is a class whose slot ended with no start.
PIPELINE = (
    ('NEW', 'New'),
    ('BOOKED', 'Booked'),
    ('COMPLETED', 'Completed'),
    ('NOT_STARTED', 'Not started'),
    ('CANCELLED', 'Cancelled'),
)
_STAGE_OF = {LeadStatus.NEW: 'NEW', **{status: stage for stage, statuses in STAGES.items() for status in statuses}}
_STAGE_OF[LeadStatus.ENROLLED] = 'ENROLLED'

# What the admissions workflow writes to the activity log: leads, booking
# links, bookings (their communication and reports included), slots and the
# schedule, Demo invitations and Re-Demo requests.
ADMISSIONS_ENTITIES = (
    'lead', 'booking_link', 'booking', 'booking_slot', 'booking_schedule', 'demo_invite', 'redemo_request', 'report',
)


def span(params, now):
    """
    The dashboard's dates from ``from`` and ``to`` (Indian dates, inclusive),
    as ((date_from, date_to), invalid): both or neither -- the last
    DEFAULT_DAYS days when neither -- the first on or before the last, at
    most MAX_DAYS days apart. ``invalid`` names what is wrong, and nothing is
    guessed for it.
    """
    (date_from, date_to), invalid = lead_admin.received_dates(params)
    if invalid:
        return (None, None), invalid
    if date_from is None and date_to is None:
        today = indian_today(now)
        return (today - timedelta(days=DEFAULT_DAYS - 1), today), []
    if date_from is None or date_to is None:
        return (None, None), ['from' if date_from is None else 'to']
    if (date_to - date_from).days >= MAX_DAYS:
        return (None, None), ['to']
    return (date_from, date_to), []


def _by_type(make_count):
    """{DEMO: n, DIAGNOSTIC: n}: ``make_count(model)`` for each booking table."""
    return {model.BOOKING_TYPE: make_count(model) for model in BOOKING_MODELS}


def _pending(now, show_bookings, show_confirmation):
    """
    What awaits an administrator now, whatever the span: leads no BDE owns
    yet, and -- for whoever may see every booking -- the classes still to
    come that need a tutor, the started classes whose report is due, the
    Re-Demo requests to schedule and, for whoever may see the bookings'
    communication too, the classes still to come awaiting the parent's
    confirmation.
    """
    pending = {
        'unassigned_leads': Lead.objects.filter(owner_bde__isnull=True).count(),
        'needs_tutor': None,
        'report_due': None,
        'redemo_scheduling': None,
        'awaiting_confirmation': None,
    }
    if not show_bookings:
        return pending
    pending['needs_tutor'] = _by_type(lambda model: coordination.filtered(
        model.objects.all(), now, status=BookingStatus.BOOKED, assigned=False, when=coordination.UPCOMING,
    ).count())
    pending['report_due'] = _by_type(lambda model: coordination.filtered(model.objects.all(), now, report_due=True).count())
    # Where a request stands is read from its rows, every request at once: Re-Demos are few.
    pending['redemo_scheduling'] = len(redemos.redemo_rows(redemos.listed(), now, status=ReDemoStatus.AWAITING_SCHEDULING))
    if show_confirmation:
        pending['awaiting_confirmation'] = _by_type(lambda model: model.objects.filter(
            status=BookingStatus.BOOKED, slot__ends_at__gt=now, parent_confirmation=ParentConfirmation.AWAITING,
        ).count())
    return pending


def _bookings(now, date_from, date_to):
    """
    Each type's bookings for classes on the span's dates that hold their seat
    (booked, completed or sent for a Re-Demo; never a cancelled or moved one),
    and how many of those are still to come.
    """
    in_span = Q(slot__local_date__gte=date_from, slot__local_date__lte=date_to)
    to_come = Q(status=BookingStatus.BOOKED, slot__ends_at__gt=now)
    return _by_type(lambda model: model.objects.filter(in_span).aggregate(
        total=Count('pk', filter=Q(status__in=HOLDS_SEAT)),
        upcoming=Count('pk', filter=to_come),
    ))


def _today_bookings(now):
    """Today's classes of both types (the Indian date) that hold their seat, soonest first, as the Bookings lists show them."""
    today = indian_today(now)
    total, rows = 0, []
    for model in BOOKING_MODELS:
        on_today = coordination.listed(model).filter(status__in=HOLDS_SEAT, slot__local_date=today)
        total += on_today.count()
        rows.extend(on_today.order_by('slot__starts_at', 'created_at', 'id')[:TODAY_ROWS])
    rows.sort(key=lambda booking: (booking.slot.starts_at, booking.created_at))
    return {
        'date': today.isoformat(),
        'total': total,
        'rows': [coordination.booking_row(booking, now) for booking in rows[:TODAY_ROWS]],
    }


def _activity(user, request):
    """The latest entries of the admissions workflow's activity, as the activity log shows them to ``user``."""
    entries = scope_activity(ActivityLog.objects.filter(entity_type__in=ADMISSIONS_ENTITIES), user, request)
    return ActivityLogSerializer(entries.order_by('-created_at')[:ACTIVITY_ROWS], many=True).data


def dashboard(now, date_from, date_to, *, user, request=None, show_bookings=False, show_confirmation=False,
              show_activity=False):
    """
    The dashboard for the span ``date_from``..``date_to`` (Indian dates,
    inclusive). The booking parts are null unless ``show_bookings`` (the
    caller may see every booking), the confirmations unless
    ``show_confirmation`` too, and the activity unless ``show_activity``
    (the caller may read the activity log, scoped as it is for them).
    """
    received = with_status(lead_admin.received_between(Lead.objects.all(), date_from, date_to), now)
    # Each lead's status is read from its bookings (lead_status), so the stages are counted as the rows come.
    stages = Counter(_STAGE_OF[status] for status in received.values_list('lead_status', flat=True))
    return {
        'timezone': BOOKING_TIMEZONE_NAME,
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'leads': {'received': sum(stages.values()), 'new': stages['NEW']},
        'pipeline': [{'stage': stage, 'label': label, 'count': stages[stage]} for stage, label in PIPELINE]
                    + ([{'stage': 'ENROLLED', 'label': 'Enrolled', 'count': stages['ENROLLED']}] if stages['ENROLLED'] else []),
        'bookings': _bookings(now, date_from, date_to) if show_bookings else None,
        'today_bookings': _today_bookings(now) if show_bookings else None,
        'pending': _pending(now, show_bookings, show_confirmation),
        'recent_leads': lead_admin.lead_rows(lead_admin.listed(Lead.objects.all(), now)[:RECENT_ROWS], now),
        'activity': _activity(user, request) if show_activity else None,
    }
