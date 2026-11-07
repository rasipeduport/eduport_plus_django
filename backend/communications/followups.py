"""
A BDE's follow-ups (GET /api/bde/follow-ups/, communications.bde_views): a
list of reminders -- what needs the BDE's attention now, and nothing the
system does by itself. Five reminders, each read from where its work is
recorded, never copied, and each gone from the list once it is resolved or
its time is up:

    NEW_ENQUIRY_CALL     an administrator gave them an enquiry with no booking
                         yet (bookings.ownership): call the parent. Shown for
                         24 hours (a FollowUp), until the BDE sends the parent
                         one of their booking links from the enquiry
                         (link_shared) or the enquiry has a booking -- its
                         progress is then its status's and its bookings'
    PARENT_CONFIRMATION  a Demo or Diagnostic whose parent has not answered,
                         from its confirmation request's due time -- 12 hours
                         before it, or at once for one booked later than that
                         (planner.plan_booking) -- until the answer is
                         recorded or the class starts
    PRE_ACTIVITY_CALL    from 15 minutes before a Demo or Diagnostic until it
                         starts, or until the BDE records how the call went
                         (its communication step; a call nobody recorded is
                         Missed, never done: planner.close_expired)
    TUTOR_REPORT         the tutor submitted the booking's report: share it
                         with the parent. Shown for 24 hours, until the BDE
                         sends it from the enquiry's tutor feedback (a
                         reports.ReportShare)
    REDEMO_CONFIRMATION  an administrator scheduled a Re-Demo, its date, time
                         and tutor chosen (bookings.redemos): confirm it with
                         the parent, until their answer is recorded or it starts

The acknowledgement, the confirmed and after-activity messages and what
WhatsApp reports about them, a report being submitted, a tutor being assigned
and a booking being completed are never reminders: they are the system's,
and stay in the booking's communication and history. Nor is a Re-Demo
request, until the Re-Demo is scheduled. A reminder that is over is not kept
here: what happened stays where it belongs -- the enquiry's status and
bookings, the booking's communication, the report's shares.

Whose a reminder is follows the lead's owner now, never who owned it when it
began: a lead given to another BDE takes its reminders with it, as its
communication goes (communications.views), and the BDE before sees none of
them. A reminder is Due today when the moment it is due by -- the class's
start, or the end of its 24 hours -- falls on today's Indian date, and
Pending when later; none outlives that moment, so none is ever overdue.
Acting on one stays with the API that owns its record.

Each row is written out field by field, so nothing reaches the BDE by being
added elsewhere: what is due and when, the booking it is for, and whose it is
-- the parent's name and number, which the BDE's own enquiry shows them.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.db import OperationalError, transaction
from django.db.models import Exists, OuterRef, Q, TextChoices
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from bookings.booking_service import BUSY_SQLSTATES, BookingBusy, _set_lock_timeout
from bookings.enquiries import booking_brief, enquiry_brief
from bookings.lifecycle import activity_state
from bookings.models import BOOKING_MODELS, BookingStatus, DemoBooking, DiagnosticBooking, Lead, ParentConfirmation
from bookings.scheduling import BOOKING_TIMEZONE, indian_today
from reports.models import REPORT_MODELS

from .models import CommunicationTask, FollowUp, FollowUpKind, FollowUpStatus, Message, Step, TaskStatus


class FollowUpType(TextChoices):
    """The five reminders, in the order an enquiry meets them."""
    NEW_ENQUIRY_CALL = 'NEW_ENQUIRY_CALL', 'Call new enquiry'
    PARENT_CONFIRMATION = 'PARENT_CONFIRMATION', 'Parent confirmation'
    PRE_ACTIVITY_CALL = 'PRE_ACTIVITY_CALL', 'Pre-activity call'
    TUTOR_REPORT = 'TUTOR_REPORT', 'Share tutor report'
    REDEMO_CONFIRMATION = 'REDEMO_CONFIRMATION', 'Re-Demo confirmation'


class FollowUpState(TextChoices):
    DUE_TODAY = 'DUE_TODAY', 'Due today'
    PENDING = 'PENDING', 'Pending'


TODAY, UPCOMING = 'today', 'upcoming'
DUE_FILTERS = (TODAY, UPCOMING)
_DUE_STATES = {TODAY: FollowUpState.DUE_TODAY, UPCOMING: FollowUpState.PENDING}
_TYPE_ORDER = {value: index for index, value in enumerate(FollowUpType.values)}

# How long the reminders an event starts are shown: a new enquiry's call from
# its assignment, a report's sharing from its submission.
REMINDER_WINDOW = timedelta(hours=24)

SEND_COMMUNICATIONS = 'accounts.send_lead_communications'
RECORD_CONFIRMATION = 'accounts.record_parent_confirmation'
VIEW_OWN_LEAD_REPORTS = 'accounts.view_own_lead_reports'


class EnquiryNotOwned(Exception):
    """Not one of the caller's own leads -- or none at all: answered alike."""
    code = 'NOT_FOUND'
    http_status = 404
    message = 'No such enquiry.'


@dataclass
class Item:
    """One reminder as read, before it is written out (row)."""
    type: str
    id: object
    lead: Lead
    due_at: datetime
    booking: object = None
    state: str = ''
    # When the call can be recorded from (its 15 minutes before the start).
    opens_at: datetime = None
    # The parent confirmation's request message, once the parent was asked.
    request: Message = None
    actions: dict = field(default_factory=dict)


# ---------------------------------------------------------------- the new enquiry's call

def _has_booking(lead):
    return DemoBooking.objects.filter(lead=lead).exists() or DiagnosticBooking.objects.filter(lead=lead).exists()


def enquiry_assigned(lead, now):
    """
    ``lead`` has just been given to a BDE (bookings.ownership, which holds its
    lock). A new enquiry -- no booking of either type yet -- gets the reminder
    to call it, shown for REMINDER_WINDOW from now: set going again when it
    had one, done or not, since its new BDE has not spoken to the parent.
    One per lead, however often this runs. Returns it, or None.
    """
    if lead.owner_bde_id is None or _has_booking(lead):
        return None
    reminder, _created = FollowUp.objects.update_or_create(
        lead=lead, kind=FollowUpKind.NEW_ENQUIRY_CALL,
        defaults={'status': FollowUpStatus.OPEN, 'due_at': now + REMINDER_WINDOW, 'resolved_at': None,
                  'resolved_by': None},
        create_defaults={'status': FollowUpStatus.OPEN, 'due_at': now + REMINDER_WINDOW, 'created_at': now},
    )
    return reminder


def link_shared(lead_id, booking_type, *, actor, now=None):
    """
    ``actor``, a BDE, has just sent the parent of their lead ``lead_id`` one of
    their booking links (``booking_type``) from the enquiry -- copied it there,
    or opened the parent's WhatsApp chat with it: the reminder to call the new
    enquiry is done. Only on the actor's own lead, checked under the lead's
    lock (EnquiryNotOwned); nothing left to do -- no reminder, or one done or
    past its 24 hours -- is no error. Returns whether a reminder was done now,
    which is logged with ids only.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            # The lead first, as an assignment takes it (bookings.ownership), then its reminder.
            lead = Lead.objects.select_for_update(no_key=True).filter(pk=lead_id).first()
            if lead is None or lead.owner_bde_id != actor.pk:
                raise EnquiryNotOwned()
            reminder = FollowUp.objects.select_for_update().filter(
                lead=lead, kind=FollowUpKind.NEW_ENQUIRY_CALL, status=FollowUpStatus.OPEN, due_at__gt=now,
            ).first()
            if reminder is None:
                return False
            reminder.status, reminder.resolved_at, reminder.resolved_by = FollowUpStatus.DONE, now, actor
            reminder.save(update_fields=['status', 'resolved_at', 'resolved_by', 'updated_at'])
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='follow_up.complete',
        entity_type='follow_up',
        entity_id=reminder.id,
        entity_label=reminder.get_kind_display(),
        # Ids and codes only: no names, phone numbers or links.
        context={'kind': reminder.kind, 'lead_id': str(lead.pk), 'booking_type': booking_type},
        actor=actor,
    )
    return True


# ---------------------------------------------------------------- reading

def _today_bounds(now):
    """Today's Indian date as the two instants that bound it -- the day the slots are booked in."""
    start = datetime.combine(indian_today(now), time.min, tzinfo=BOOKING_TIMEZONE)
    return start, start + timedelta(days=1)


def _permissions(user, request):
    names = (SEND_COMMUNICATIONS, RECORD_CONFIRMATION, VIEW_OWN_LEAD_REPORTS)
    return {name: has_app_permission(user, name, request) for name in names}


def _actions(record_outcome=False, request_confirmation=False, record_answer=False):
    """What the caller may do on a reminder from the list: each action the API that owns it checks again."""
    return {
        'record_outcome': record_outcome,
        'request_confirmation': request_confirmation,
        'record_answer': record_answer,
    }


def open_items(user, now, request=None, enquiry=None):
    """
    The reminders of the leads ``user`` owns now -- one lead's with
    ``enquiry`` -- soonest due first, each with its state and what ``user``
    may do on it. A report's only for one who may see the reports.
    """
    can = _permissions(user, request)
    items = [
        *_enquiry_calls(user, now, enquiry),
        *_confirmations(user, now, enquiry, can),
        *_calls(user, now, enquiry, can),
    ]
    if can[VIEW_OWN_LEAD_REPORTS]:
        items += _reports(user, now, enquiry)
    end_of_today = _today_bounds(now)[1]
    for item in items:
        item.state = FollowUpState.DUE_TODAY if item.due_at < end_of_today else FollowUpState.PENDING
    return sorted(items, key=lambda item: (item.due_at, _TYPE_ORDER[item.type], str(item.id)))


def _enquiry_calls(user, now, enquiry):
    """New enquiries to call: within their 24 hours, not yet sent a booking link, and still without a booking."""
    reminders = FollowUp.objects.filter(
        ~Exists(DemoBooking.objects.filter(lead=OuterRef('lead'))),
        ~Exists(DiagnosticBooking.objects.filter(lead=OuterRef('lead'))),
        lead__owner_bde=user, kind=FollowUpKind.NEW_ENQUIRY_CALL, status=FollowUpStatus.OPEN, due_at__gt=now,
    ).select_related('lead')
    if enquiry:
        reminders = reminders.filter(lead_id=enquiry)
    return [Item(FollowUpType.NEW_ENQUIRY_CALL, reminder.id, reminder.lead, reminder.due_at) for reminder in reminders]


def _awaiting(model, user, now, enquiry):
    """``model``'s bookings of ``user``'s leads, still to come and not yet started, whose parent has not answered."""
    bookings = model.objects.filter(
        lead__owner_bde=user, status=BookingStatus.BOOKED, started_at__isnull=True, slot__starts_at__gt=now,
        parent_confirmation=ParentConfirmation.AWAITING,
    ).select_related('slot', 'lead')
    return bookings.filter(lead_id=enquiry) if enquiry else bookings


def _confirmations(user, now, enquiry, can):
    items = []
    for model in BOOKING_MODELS:
        # From the confirmation request's due time: 12 hours before the start, or
        # at once for a booking made later than that. A Re-Demo has no steps.
        bookings = list(_awaiting(model, user, now, enquiry).filter(
            communication_tasks__step=Step.CONFIRMATION_REQUEST, communication_tasks__due_at__lte=now,
        ))
        requests = _confirmation_requests(model, bookings)
        for booking in bookings:
            asked = requests.get(booking.pk)
            items.append(Item(
                FollowUpType.PARENT_CONFIRMATION, booking.id, booking.lead, booking.slot.starts_at, booking=booking,
                request=asked,
                actions=_actions(
                    request_confirmation=asked is None and can[SEND_COMMUNICATIONS],
                    record_answer=can[RECORD_CONFIRMATION],
                ),
            ))
    # A Re-Demo from when an administrator schedules it -- its date, time and
    # tutor chosen -- never while it is only requested.
    for booking in _awaiting(DemoBooking, user, now, enquiry).filter(redemo_for__isnull=False):
        items.append(Item(
            FollowUpType.REDEMO_CONFIRMATION, booking.id, booking.lead, booking.slot.starts_at, booking=booking,
            actions=_actions(record_answer=can[RECORD_CONFIRMATION]),
        ))
    return items


def _column(model):
    """The column of ``model``'s bookings in the communication tables."""
    return 'diagnostic_booking' if model is DiagnosticBooking else 'demo_booking'


def _confirmation_requests(model, bookings):
    """The confirmation request each of ``bookings`` has, by booking id: its parent was asked."""
    column = _column(model)
    messages = Message.objects.filter(**{f'{column}__in': bookings}, template__step=Step.CONFIRMATION_REQUEST)
    return {getattr(message, f'{column}_id'): message for message in messages}


def _calls(user, now, enquiry, can):
    """The 15-minute calls open now: from 15 minutes before a booking still to come until its start."""
    def booked(column):
        return Q(**{
            f'{column}__lead__owner_bde': user, f'{column}__status': BookingStatus.BOOKED,
            f'{column}__started_at__isnull': True,
        })

    tasks = CommunicationTask.objects.filter(
        booked('demo_booking') | booked('diagnostic_booking'),
        step=Step.PRE_ACTIVITY_CALL, status=TaskStatus.OPEN, active_from__lte=now, due_at__gt=now,
    ).select_related('demo_booking__slot', 'demo_booking__lead', 'diagnostic_booking__slot', 'diagnostic_booking__lead')
    if enquiry:
        tasks = tasks.filter(Q(demo_booking__lead_id=enquiry) | Q(diagnostic_booking__lead_id=enquiry))
    return [
        Item(FollowUpType.PRE_ACTIVITY_CALL, task.id, task.booking.lead, task.due_at, booking=task.booking,
             opens_at=task.active_from, actions=_actions(record_outcome=can[SEND_COMMUNICATIONS]))
        for task in tasks
    ]


def _reports(user, now, enquiry):
    """The reports on ``user``'s leads' bookings submitted in the last 24 hours that nobody has sent the parent yet."""
    items = []
    for model in REPORT_MODELS:
        reports = model.objects.filter(
            booking__lead__owner_bde=user, submitted_at__gt=now - REMINDER_WINDOW, shares__isnull=True,
        ).select_related('booking__slot', 'booking__lead')
        if enquiry:
            reports = reports.filter(booking__lead_id=enquiry)
        items.extend(
            Item(FollowUpType.TUTOR_REPORT, report.id, report.booking.lead, report.submitted_at + REMINDER_WINDOW,
                 booking=report.booking)
            for report in reports
        )
    return items


def summary(items):
    """How many of ``items`` are due today and later, and how many in all."""
    states = Counter(item.state for item in items)
    return {'total': len(items), TODAY: states[FollowUpState.DUE_TODAY], UPCOMING: states[FollowUpState.PENDING]}


def filtered(items, due=None, follow_up_type=None):
    """``items`` narrowed to one due filter and one type."""
    if due:
        items = [item for item in items if item.state == _DUE_STATES[due]]
    if follow_up_type:
        items = [item for item in items if item.type == follow_up_type]
    return items


def _when(value):
    return value.isoformat() if value else None


def row(item, now):
    """One reminder as the BDE's lists show it."""
    lead = item.lead
    booking = item.booking
    return {
        'id': str(item.id),
        'type': item.type,
        'type_label': FollowUpType(item.type).label,
        'state': item.state,
        'state_label': FollowUpState(item.state).label,
        'due_at': _when(item.due_at),
        'opens_at': _when(item.opens_at),
        # Whether the parent was asked to confirm, and where that message stands.
        'request': (
            {'status': item.request.status, 'status_label': item.request.get_status_display()} if item.request else None
        ),
        'booking': {
            **booking_brief(booking),
            'status': booking.status,
            'activity_state': activity_state(booking, now),
            'redemo': getattr(booking, 'redemo_for_id', None) is not None,
        } if booking else None,
        'enquiry': {
            **enquiry_brief(lead),
            'phone': f'{lead.phone_dial_code} {lead.phone_number}',
            'phone_dial_code': lead.phone_dial_code,
            'phone_number': lead.phone_number,
        },
        'actions': item.actions or _actions(),
    }
