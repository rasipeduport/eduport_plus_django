"""
A BDE's follow-ups (GET /api/bde/follow-ups/, communications.bde_views): what
the BDE must do next on their own leads -- and nothing the system does by
itself. Five kinds, each read from where its work is recorded, never copied:

    NEW_ENQUIRY_CALL     an administrator gave them an enquiry with no booking
                         yet (bookings.ownership): call the parent, then record
                         how it went -- a FollowUp, due within 3 hours
    PARENT_CONFIRMATION  a Demo or Diagnostic whose parent has not answered,
                         from its confirmation request's due time (12 hours
                         before it, planner.plan_booking): ask the parent, then
                         record the answer -- the booking itself, due by its
                         start and Missed if that comes first
    PRE_ACTIVITY_CALL    from 15 minutes before a Demo or Diagnostic until it
                         starts: call the parent, then record how it went --
                         its communication step, Missed at the start
                         (planner.close_expired)
    REPORT_DISCUSSION    the tutor submitted the booking's report
                         (reports.services): share it with the parent and
                         discuss it, then mark it done -- a FollowUp, due
                         within a day
    REDEMO_CONFIRMATION  an administrator scheduled a Re-Demo, its date, time
                         and tutor chosen (bookings.redemos): tell the parent,
                         then record their answer -- the booking, due by its
                         start and Missed if that comes first

The acknowledgement, the confirmed and after-activity messages and what
WhatsApp reports about them, a report being submitted, a tutor being assigned
and a booking being completed are never follow-ups: they are the system's,
and stay in the booking's communication and history -- a failed message
included. Nor is a Re-Demo request, until the Re-Demo is scheduled.

Whose a follow-up is follows the lead's owner now, never who owned it when it
began: a lead given to another BDE takes its follow-ups with it, as its
communication goes (communications.views), and the BDE before sees none of
them. An open one is Overdue (past due: only a call or a report can be),
Due today or Pending (due on a later day), in Indian days, the days the slots
are booked in; one that is over is Completed or Missed. Acting on one stays
with the API that owns its record: the booking's communication for the
confirmations and the call (communications.views), complete() here for a
FollowUp.

Each row is written out field by field, so nothing reaches the BDE by being
added elsewhere: what is due and when, the booking it is for, and whose it is
-- the parent's name and number, which the BDE's own enquiry shows them.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.db import OperationalError, transaction
from django.db.models import Q, TextChoices
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from bookings.booking_service import BUSY_SQLSTATES, BookingBusy, _set_lock_timeout
from bookings.enquiries import booking_brief, enquiry_brief
from bookings.lifecycle import activity_state
from bookings.models import BOOKING_MODELS, BookingStatus, DemoBooking, DiagnosticBooking, Lead, ParentConfirmation
from bookings.scheduling import BOOKING_TIMEZONE, indian_today

from .models import (
    CALL_OUTCOMES,
    FOLLOW_UP_OUTCOMES,
    CommunicationTask,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Message,
    Step,
    TaskStatus,
)
from .planner import booking_field


class FollowUpType(TextChoices):
    """The five things a BDE follows up, in the order a lead meets them."""
    NEW_ENQUIRY_CALL = 'NEW_ENQUIRY_CALL', 'Call new enquiry'
    PARENT_CONFIRMATION = 'PARENT_CONFIRMATION', 'Parent confirmation'
    PRE_ACTIVITY_CALL = 'PRE_ACTIVITY_CALL', 'Pre-activity call'
    REPORT_DISCUSSION = 'REPORT_DISCUSSION', 'Discuss tutor report'
    REDEMO_CONFIRMATION = 'REDEMO_CONFIRMATION', 'Re-Demo confirmation'


class FollowUpState(TextChoices):
    OVERDUE = 'OVERDUE', 'Overdue'
    DUE_TODAY = 'DUE_TODAY', 'Due today'
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    MISSED = 'MISSED', 'Missed'


OPEN, CLOSED = 'open', 'closed'
STATES = (OPEN, CLOSED)
OVERDUE, TODAY, UPCOMING = 'overdue', 'today', 'upcoming'
DUE_FILTERS = (OVERDUE, TODAY, UPCOMING)
_DUE_STATES = {OVERDUE: FollowUpState.OVERDUE, TODAY: FollowUpState.DUE_TODAY, UPCOMING: FollowUpState.PENDING}
_TYPE_ORDER = {value: index for index, value in enumerate(FollowUpType.values)}

# A new enquiry is called within 3 hours of reaching the BDE -- the PRD's
# first-contact target, as for the acknowledgement -- and a report discussed
# within a day of being submitted.
NEW_ENQUIRY_CALL_TARGET = timedelta(hours=3)
REPORT_DISCUSSION_TARGET = timedelta(days=1)

SEND_COMMUNICATIONS = 'accounts.send_lead_communications'
RECORD_CONFIRMATION = 'accounts.record_parent_confirmation'
VIEW_OWN_LEAD_REPORTS = 'accounts.view_own_lead_reports'
SHARE_BOOKING_REPORT = 'accounts.share_booking_report'
# What completing each FollowUp kind needs, beside seeing the follow-ups: a
# call is following up with the parent; a report's is seeing it and recording
# that it reached them.
COMPLETE_PERMISSIONS = {
    FollowUpKind.NEW_ENQUIRY_CALL: (SEND_COMMUNICATIONS,),
    FollowUpKind.REPORT_DISCUSSION: (VIEW_OWN_LEAD_REPORTS, SHARE_BOOKING_REPORT),
}
# What the parent answered, as a completed confirmation shows it.
_ANSWERS = {
    ParentConfirmation.CONFIRMED: 'Parent confirmed',
    ParentConfirmation.NOT_CONFIRMED: 'Parent did not confirm (booking cancelled)',
}


class FollowUpError(Exception):
    code = 'FOLLOW_UP_FAILED'
    http_status = 400
    message = 'That could not be done.'


class FollowUpNotFound(FollowUpError):
    """Not one of the caller's own leads' -- or none at all: answered alike."""
    code = 'NOT_FOUND'
    http_status = 404
    message = 'No such follow-up.'


class FollowUpDone(FollowUpError):
    code = 'FOLLOW_UP_DONE'
    http_status = 409
    message = 'This follow-up is already completed.'


class InvalidFollowUpOutcome(FollowUpError):
    code = 'INVALID_OUTCOME'
    message = 'Choose one of the outcomes listed.'


@dataclass
class Item:
    """One follow-up, open or over, as read -- before it is written out (row)."""
    type: str
    id: object
    lead: Lead
    due_at: datetime
    booking: object = None
    state: str = ''
    # When the call can be recorded from (its 15 minutes before the start).
    opens_at: datetime = None
    closed_at: datetime = None
    # (code, label) of what was recorded, once Completed.
    outcome: tuple = None
    # Who completed it (a user id), once Completed.
    by_id: object = None
    # The parent confirmation's request message, once the parent was asked.
    request: Message = None
    actions: dict = field(default_factory=dict)


# ---------------------------------------------------------------- triggers

def enquiry_assigned(lead, now):
    """
    ``lead`` has just been given to a BDE (bookings.ownership, which holds its
    lock). A new enquiry -- no booking of either type yet -- gets its call,
    due within NEW_ENQUIRY_CALL_TARGET; one still open from an owner before
    goes with the lead and is due as soon from now; one already done is
    history, and the lead is not called again. At most one per lead, however
    often this runs. Returns the call, or None.
    """
    if lead.owner_bde_id is None:
        return None
    if DemoBooking.objects.filter(lead=lead).exists() or DiagnosticBooking.objects.filter(lead=lead).exists():
        return None
    due_at = now + NEW_ENQUIRY_CALL_TARGET
    call, created = FollowUp.objects.get_or_create(
        lead=lead, kind=FollowUpKind.NEW_ENQUIRY_CALL, defaults={'due_at': due_at, 'created_at': now},
    )
    if not created and call.status == FollowUpStatus.OPEN:
        call.due_at = due_at
        call.save(update_fields=['due_at', 'updated_at'])
    return call


def report_submitted(booking, now):
    """
    The tutor has just submitted ``booking``'s report (reports.services, which
    holds the booking's lock): the lead's BDE is to share it with the parent
    and discuss it, within REPORT_DISCUSSION_TARGET -- whoever owns the lead
    now or later. Once per booking: an edit of the report adds none.
    """
    discussion, _created = FollowUp.objects.get_or_create(
        **booking_field(booking), kind=FollowUpKind.REPORT_DISCUSSION,
        defaults={'lead_id': booking.lead_id, 'due_at': now + REPORT_DISCUSSION_TARGET, 'created_at': now},
    )
    return discussion


# ---------------------------------------------------------------- completing

def own_follow_ups(user):
    """The FollowUps of the leads ``user`` owns now."""
    return FollowUp.objects.filter(lead__owner_bde=user)


def complete(follow_up, outcome, *, actor, owner_bde, now=None):
    """
    Record ``outcome`` on ``follow_up`` (a FollowUp), which completes it: how
    a new enquiry's call went, or that the report was discussed
    (FOLLOW_UP_OUTCOMES, else InvalidFollowUpOutcome). Only on ``owner_bde``'s
    own lead's, checked under the lead's lock -- a lead given to another BDE
    meanwhile answers as one that does not exist (FollowUpNotFound) -- and
    only once (FollowUpDone). Logged with ids and codes only.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            # The lead first, as an assignment takes it (bookings.ownership), then the follow-up.
            lead = Lead.objects.select_for_update(no_key=True).filter(pk=follow_up.lead_id).first()
            if lead is None or lead.owner_bde_id != owner_bde.pk:
                raise FollowUpNotFound()
            follow_up = FollowUp.objects.select_for_update().get(pk=follow_up.pk)
            if outcome not in FOLLOW_UP_OUTCOMES[follow_up.kind]:
                raise InvalidFollowUpOutcome()
            if follow_up.status != FollowUpStatus.OPEN:
                raise FollowUpDone()
            follow_up.status = FollowUpStatus.DONE
            follow_up.outcome = outcome
            follow_up.resolved_at = now
            follow_up.resolved_by = actor
            follow_up.save(update_fields=['status', 'outcome', 'resolved_at', 'resolved_by', 'updated_at'])
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    booking_id = follow_up.demo_booking_id or follow_up.diagnostic_booking_id
    log_activity(
        action='follow_up.complete',
        entity_type='follow_up',
        entity_id=follow_up.id,
        entity_label=follow_up.get_kind_display(),
        # Ids and codes only: no names, phone numbers or text.
        context={
            'kind': follow_up.kind,
            'outcome': outcome,
            'lead_id': str(follow_up.lead_id),
            'booking_id': str(booking_id) if booking_id else None,
        },
        actor=actor,
    )
    return follow_up


# ---------------------------------------------------------------- reading

def _today_bounds(now):
    """Today's Indian date as the two instants that bound it -- the day the slots are booked in."""
    start = datetime.combine(indian_today(now), time.min, tzinfo=BOOKING_TIMEZONE)
    return start, start + timedelta(days=1)


def _permissions(user, request):
    names = (SEND_COMMUNICATIONS, RECORD_CONFIRMATION, VIEW_OWN_LEAD_REPORTS, SHARE_BOOKING_REPORT)
    return {name: has_app_permission(user, name, request) for name in names}


def _actions(record_outcome=False, request_confirmation=False, record_answer=False, complete=False):
    """What the caller may do on a follow-up now: each action the API that owns it checks again."""
    return {
        'record_outcome': record_outcome,
        'request_confirmation': request_confirmation,
        'record_answer': record_answer,
        'complete': complete,
    }


def open_items(user, now, request=None, enquiry=None):
    """
    Every open follow-up of the leads ``user`` owns now -- one lead's with
    ``enquiry`` -- soonest due first, each with its state and what ``user``
    may do on it. A report's only for one who may see the reports.
    """
    can = _permissions(user, request)
    items = [
        *_enquiry_calls(user, enquiry, can),
        *_confirmations(user, now, enquiry, can),
        *_calls(user, now, enquiry, can),
    ]
    if can[VIEW_OWN_LEAD_REPORTS]:
        items += _report_discussions(user, enquiry, can)
    end_of_today = _today_bounds(now)[1]
    for item in items:
        if item.due_at < now:
            item.state = FollowUpState.OVERDUE
        elif item.due_at < end_of_today:
            item.state = FollowUpState.DUE_TODAY
        else:
            item.state = FollowUpState.PENDING
    return sorted(items, key=lambda item: (item.due_at, _TYPE_ORDER[item.type], str(item.id)))


def _own_follow_ups(user, enquiry):
    follow_ups = own_follow_ups(user).select_related('lead', 'demo_booking__slot', 'diagnostic_booking__slot')
    return follow_ups.filter(lead_id=enquiry) if enquiry else follow_ups


def _enquiry_calls(user, enquiry, can):
    follow_ups = _own_follow_ups(user, enquiry).filter(kind=FollowUpKind.NEW_ENQUIRY_CALL, status=FollowUpStatus.OPEN)
    return [
        Item(FollowUpType.NEW_ENQUIRY_CALL, call.id, call.lead, call.due_at,
             actions=_actions(record_outcome=can[SEND_COMMUNICATIONS]))
        for call in follow_ups
    ]


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


def _report_discussions(user, enquiry, can):
    follow_ups = _own_follow_ups(user, enquiry).filter(kind=FollowUpKind.REPORT_DISCUSSION, status=FollowUpStatus.OPEN)
    return [
        Item(FollowUpType.REPORT_DISCUSSION, discussion.id, discussion.lead, discussion.due_at,
             booking=discussion.booking, actions=_actions(complete=can[SHARE_BOOKING_REPORT]))
        for discussion in follow_ups
    ]


def closed_items(user, now, enquiry, request=None):
    """
    The follow-ups that are over on ``enquiry``, one of ``user``'s own leads,
    newest first: Completed -- the BDE recorded what it asked for -- or Missed,
    its booking having started first. A booking cancelled or moved before its
    parent answered takes its confirmation with it: the booking's history says
    what happened (bookings.history).
    """
    can = _permissions(user, request)
    lead = Lead.objects.filter(pk=enquiry, owner_bde=user).first()
    if lead is None:
        return []
    follow_ups = FollowUp.objects.filter(lead=lead, status=FollowUpStatus.DONE).select_related(
        'lead', 'demo_booking__slot', 'diagnostic_booking__slot',
    )
    items = [
        done_item(follow_up) for follow_up in follow_ups
        if follow_up.kind != FollowUpKind.REPORT_DISCUSSION or can[VIEW_OWN_LEAD_REPORTS]
    ]
    for model in BOOKING_MODELS:
        column = _column(model)
        # Planned bookings have the step; one made before parent communication never had this follow-up.
        asked = set(CommunicationTask.objects.filter(
            **{f'{column}__lead': lead}, step=Step.CONFIRMATION_REQUEST,
        ).values_list(f'{column}_id', flat=True))
        for booking in model.objects.filter(lead=lead).exclude(status=BookingStatus.RESCHEDULED).select_related('slot'):
            redemo = getattr(booking, 'redemo_for_id', None) is not None
            if not redemo and booking.pk not in asked:
                continue
            item = Item(FollowUpType.REDEMO_CONFIRMATION if redemo else FollowUpType.PARENT_CONFIRMATION, booking.id,
                        lead, booking.slot.starts_at, booking=booking)
            answer = booking.parent_confirmation
            if answer != ParentConfirmation.AWAITING:
                items.append(_completed(item, booking.parent_confirmation_at, (answer, _ANSWERS[answer]),
                                        booking.parent_confirmation_by_id))
            elif booking.status != BookingStatus.CANCELLED and (booking.started_at or booking.slot.starts_at <= now):
                started = [moment for moment in (booking.started_at, booking.slot.starts_at) if moment]
                items.append(_missed(item, min(started)))
    calls = CommunicationTask.objects.filter(
        Q(demo_booking__lead=lead) | Q(diagnostic_booking__lead=lead),
        step=Step.PRE_ACTIVITY_CALL, status__in=(TaskStatus.DONE, TaskStatus.MISSED),
    ).select_related('demo_booking__slot', 'diagnostic_booking__slot')
    for task in calls:
        item = Item(FollowUpType.PRE_ACTIVITY_CALL, task.id, lead, task.due_at, booking=task.booking,
                    opens_at=task.active_from)
        if task.status == TaskStatus.DONE and task.resolution in CALL_OUTCOMES:
            items.append(_completed(item, task.resolved_at, (task.resolution, task.get_resolution_display()),
                                    task.resolved_by_id))
        else:
            items.append(_missed(item, task.resolved_at))
    return sorted(items, key=lambda item: (item.closed_at, _TYPE_ORDER[item.type], str(item.id)), reverse=True)


def done_item(follow_up):
    """A completed FollowUp as an item: in closed_items, and as completing one answers."""
    return _completed(
        Item(follow_up.kind, follow_up.id, follow_up.lead, follow_up.due_at, booking=follow_up.booking),
        follow_up.resolved_at, (follow_up.outcome, follow_up.get_outcome_display()), follow_up.resolved_by_id,
    )


def _completed(item, at, outcome, by_id):
    item.state, item.closed_at, item.outcome, item.by_id = FollowUpState.COMPLETED, at, outcome, by_id
    item.actions = _actions()
    return item


def _missed(item, at):
    item.state, item.closed_at = FollowUpState.MISSED, at
    item.actions = _actions()
    return item


def summary(items):
    """How many of the open ``items`` are overdue, due today and upcoming, and how many in all."""
    states = Counter(item.state for item in items)
    return {
        'total': len(items),
        OVERDUE: states[FollowUpState.OVERDUE],
        TODAY: states[FollowUpState.DUE_TODAY],
        UPCOMING: states[FollowUpState.PENDING],
    }


def filtered(items, due=None, follow_up_type=None):
    """``items`` narrowed to one due filter (open ones) and one type."""
    if due:
        items = [item for item in items if item.state == _DUE_STATES[due]]
    if follow_up_type:
        items = [item for item in items if item.type == follow_up_type]
    return items


def _when(value):
    return value.isoformat() if value else None


def row(item, now, user):
    """One follow-up as the BDE's lists show it."""
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
        'closed_at': _when(item.closed_at),
        'outcome': {'code': item.outcome[0], 'label': item.outcome[1]} if item.outcome else None,
        'by_you': item.by_id == user.pk if item.state == FollowUpState.COMPLETED else None,
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
