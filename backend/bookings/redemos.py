"""
Re-Demos: teaching a lead's completed Demo again.

1. Request. An administrator -- or the BDE who owns the lead -- asks for a
   Re-Demo of a COMPLETED Demo, giving the reason
   (booking_service.request_redemo). The Demo is RE-DEMO REQUIRED at once,
   with no approval step, and otherwise kept as it was: its tutor, slot,
   report and history.
2. Scheduling. An administrator picks the tutor -- any active tutor but those
   who taught a Demo of the chain -- a date and a time that tutor is free
   for, and adds remarks for them; confirming books the Re-Demo straight away
   (booking_service.schedule_redemo): a new Demo of the lead with that tutor
   and their Meet link, naming the request (DemoBooking.redemo_for). They pick
   by tutor (the tutor, then their slots: slot_options) or by time (a slot,
   then the tutors free for it: time_options, slot_tutor_options), each slot
   shown on the student's own clock beside its Indian time (student_clock).
   Nothing is sent to the parent -- no link, no message: a Re-Demo has no
   communication plan (communications.planner) -- and the BDE tells them the
   confirmed time by hand, with the Demo messages' own wording filled in
   (communications.redemo_messages).
3. Teaching. The Re-Demo is a Demo booking: started, taught, reported on --
   a report of its own; the Demo taught before keeps its own -- moved,
   given another tutor and cancelled as any booking is. Its tutor sees it
   as a RE-DEMO, with the Demo it follows, its report, the reason and the
   remarks (bookings.tutor_bookings); the remarks no longer change once it
   has started (set_remarks). Cancelled, it leaves the request to be
   scheduled again.
4. Closing. While nothing is booked for it the request may be closed, for a
   reason code, and reopened (booking_service.close_redemo / reopen_redemo).
5. Again. Once the Re-Demo is taught it may have a Re-Demo of its own: each
   request names the Demo it teaches again, and the Demo scheduled for it
   names the request, so a lead's Re-Demos form a chain (request_chain).

Where a request stands is bookings.redemo_chain's. Who may do what is the
views' check, made again under the locks where it depends on the lead's
owner: an administrator (accounts.view_all_bookings, and
accounts.assign_booking_tutor to schedule a request or change its remarks)
for any lead; a BDE asks, closes and reopens only for their own leads. The
reason and the remarks are staff's words, kept on the request: no booking
history, activity log or parent sees them, and the BDE never sees the
remarks. Every write logs ids only.
"""
from datetime import date as date_type, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import OperationalError, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from communications.redemo_messages import redemo_messages

from . import enquiries, student_timezones
from .booking_service import (
    BUSY_SQLSTATES,
    BookingBusy,
    RedemoEarlierTutor,
    RedemoOriginalTutor,
    RedemoRemarksLocked,
    _check_offered,
    _locked_booking,
    _overlapping_bookings,
    _overlapping_classes,
    _set_lock_timeout,
    assignable_tutors,
    clean_redemo_remarks,
    redemo_refusal,
    tutor_conflicts,
)
from .coordination import (
    EARLIER_TUTOR_REASON,
    ORIGINAL_TUTOR_REASON,
    booking_actions,
    conflict_reason,
    report_brief,
    report_summary,
    slot_brief,
    slot_options as booking_slot_options,
    tutor_change_refusal,
)
from .lifecycle import ActivityState, activity_state
from .models import (
    CONDUCTED,
    BookingStatus,
    BookingType,
    CancelReason,
    DemoBooking,
    Lead,
    ParentConfirmation,
    RedemoCloseReason,
    ReDemoRequest,
    ReDemoStatus,
)
from .redemo_chain import excluded_tutor_ids, redemo_number, state
from .scheduling import BOOKING_TIMEZONE, BOOKING_TIMEZONE_NAME, FULLY_BOOKED, bookable_window, slot_instants

AVAILABLE, UNAVAILABLE_TUTOR = 'AVAILABLE', 'UNAVAILABLE'
ASSIGN_BOOKING_TUTOR = 'accounts.assign_booking_tutor'
VIEW_ALL_BOOKINGS = 'accounts.view_all_bookings'
RESCHEDULE_BOOKING = 'accounts.reschedule_booking'
# A slot open for the child whose chosen tutor is not free then (slot_options).
TUTOR_BUSY = 'TUTOR_BUSY'
# A slot open for the child with no tutor who may teach the Re-Demo free then (time_options).
NO_TUTOR_FREE = 'NO_TUTOR_FREE'

# What a request needs looked at, beside where it stands (``attention``).
LAST_ATTEMPT_CANCELLED = 'LAST_ATTEMPT_CANCELLED'  # its Re-Demo was cancelled: schedule it again, or close it
NOT_STARTED = 'NOT_STARTED'  # its Re-Demo's slot ended with no start: move or cancel it
REPORT_DUE = 'REPORT_DUE'  # its Re-Demo was taught and the report is not in yet
NO_MEET_LINK = 'NO_MEET_LINK'  # its Re-Demo's tutor has no Meet room on the booking
NO_BDE = 'NO_BDE'  # nobody owns the lead: nobody is reminded to tell the parent
ATTENTION_LABELS = {
    LAST_ATTEMPT_CANCELLED: 'Last Re-Demo cancelled',
    NOT_STARTED: 'Slot ended without a start',
    REPORT_DUE: 'Report due',
    NO_MEET_LINK: 'No Meet link',
    NO_BDE: 'No BDE on the lead',
}
# The list's status filter: a ReDemoStatus, or every open request needing a look.
ATTENTION = 'ATTENTION'
STATUS_FILTERS = (*ReDemoStatus.values, ATTENTION)
OPEN_STATUSES = (ReDemoStatus.AWAITING_SCHEDULING, ReDemoStatus.SCHEDULED)


# ------------------------------------------------------------------ reading

def listed():
    """Every Re-Demo request, with what its rows show: the lead, the Demo to teach again and the Demos scheduled for it."""
    bookings = DemoBooking.objects.select_related('slot', 'assigned_tutor', 'report').prefetch_related('report__shares')
    return ReDemoRequest.objects.select_related(
        'lead', 'lead__owner_bde', 'demo_booking__slot', 'demo_booking__assigned_tutor', 'demo_booking__report',
        'demo_booking__redemo_for', 'requested_by', 'remarks_updated_by', 'closed_by',
    ).prefetch_related(Prefetch('bookings', queryset=bookings))


def search(redemos, q):
    """Requests whose lead matches ``q``: the parent's or student's name, or phone digits (the enquiry search)."""
    if not (q or '').strip():
        return redemos
    return redemos.filter(lead__in=enquiries.search(Lead.objects.all(), q))


def narrowed(redemos, owner=None, no_owner=False, requested_from=None, requested_to=None, lead_id=None,
             booking_id=None):
    """
    ``redemos`` narrowed by the list's other filters: the lead's BDE
    (``owner``, or ``no_owner``), the Indian dates the request was made on,
    one lead, and one booking -- the Demo a request teaches again, or any
    Demo booked for it (a workspace's way into its request).
    """
    if owner:
        redemos = redemos.filter(lead__owner_bde_id=owner)
    if no_owner:
        redemos = redemos.filter(lead__owner_bde__isnull=True)
    if requested_from:
        redemos = redemos.filter(requested_at__gte=_day_start(requested_from))
    if requested_to:
        redemos = redemos.filter(requested_at__lt=_day_start(requested_to + timedelta(days=1)))
    if lead_id:
        redemos = redemos.filter(lead_id=lead_id)
    if booking_id:
        ids = set(DemoBooking.objects.filter(pk=booking_id).values_list('redemo_for_id', flat=True)) - {None}
        redemos = redemos.filter(Q(pk__in=ids) | Q(demo_booking_id=booking_id))
    return redemos


def _day_start(day):
    return datetime.combine(day, datetime.min.time(), tzinfo=BOOKING_TIMEZONE)


def _person(user):
    return {'id': str(user.pk), 'full_name': user.full_name or user.email} if user else None


def _staff(user):
    """Who did it, with the role they did it in."""
    if user is None:
        return None
    return {**_person(user), 'role': user.role, 'role_label': user.get_role_display()}


def _when(value):
    return value.isoformat() if value else None


def _label(choices, code):
    return {'code': code, 'label': choices(code).label} if code else None


def _report(booking):
    report = getattr(booking, 'report', None)
    return {
        'has_report': report is not None,
        'report_version': report.version if report is not None else None,
        # Whether its BDE has sent the report to the parent (reports.ReportShare), at any version.
        'report_shared': report is not None and any(True for _ in report.shares.all()),
    }


def _booking(booking, now):
    """
    A Demo of the chain as the Re-Demo views link to it: when, its status, its
    tutor, its Meet room, the parent's answer, its start and its report -- and,
    cancelled, why (a code: these views are the administrators').
    """
    if booking is None:
        return None
    return {
        'id': str(booking.id),
        'status': booking.status,
        'slot': slot_brief(booking.slot, now),
        'tutor': _person(booking.assigned_tutor),
        'tutor_meet_link': booking.tutor_meet_link,
        'activity_state': activity_state(booking, now),
        'started_at': _when(booking.started_at),
        'completed_at': _when(booking.completed_at),
        'booked_at': booking.created_at.isoformat(),
        'parent_confirmation': booking.parent_confirmation,
        'cancel_reason': _label(CancelReason, booking.cancel_reason_code),
        'report_due': report_summary(booking, now)['report_due'],
        **_report(booking),
    }


def remarks_locked(current):
    """Whether the remarks are kept as they are: the Re-Demo they brief has started, or been taught."""
    booking = current.booking
    if booking is None:
        return False
    return booking.status in CONDUCTED or (booking.status == BookingStatus.BOOKED and booking.started_at is not None)


def attention(redemo, current, now):
    """What an open request needs looked at, as codes (ATTENTION_LABELS); nothing for a completed or closed one."""
    if current.status not in OPEN_STATUSES:
        return []
    booking = current.booking
    found = []
    if current.status == ReDemoStatus.AWAITING_SCHEDULING and booking is not None:
        found.append(LAST_ATTEMPT_CANCELLED)
    if current.status == ReDemoStatus.SCHEDULED:
        state_now = activity_state(booking, now)
        if state_now == ActivityState.NOT_STARTED:
            found.append(NOT_STARTED)
        elif report_summary(booking, now)['report_due']:
            found.append(REPORT_DUE)
        if not booking.tutor_meet_link and booking.started_at is None and state_now != ActivityState.NOT_STARTED:
            found.append(NO_MEET_LINK)
    if redemo.lead.owner_bde_id is None:
        found.append(NO_BDE)
    return found


def needs_action(current, flags):
    """An administrator's step: a request to schedule, or a Re-Demo whose slot ended with no start."""
    return current.status == ReDemoStatus.AWAITING_SCHEDULING or NOT_STARTED in flags


def _closed(redemo):
    if redemo.closed_at is None:
        return None
    return {
        'at': redemo.closed_at.isoformat(),
        'by': _staff(redemo.closed_by),
        'reason': _label(RedemoCloseReason, redemo.close_reason_code),
    }


def redemo_row(redemo, now, redemo_state=None):
    """One request as the Re-Demo list shows it."""
    current = redemo_state or state(redemo, now)
    lead = redemo.lead
    booking = current.booking
    flags = attention(redemo, current, now)
    return {
        'id': str(redemo.id),
        'status': current.status,
        'status_label': ReDemoStatus(current.status).label,
        'requested_at': redemo.requested_at.isoformat(),
        'requested_by': _staff(redemo.requested_by),
        'reason': redemo.reason,
        'student_name': lead.student_name,
        'grade': lead.grade,
        'syllabus': lead.syllabus,
        'parent_name': lead.parent_name,
        'phone': f'{lead.phone_dial_code} {lead.phone_number}',
        # The zone the student books from, for their own time of each slot; null when not known.
        'student_timezone': student_timezones.of(lead),
        'lead_id': str(lead.id),
        'owner_bde': _person(lead.owner_bde),
        # The Demo to teach again, with its original tutor and report.
        'original': _booking(redemo.demo_booking, now),
        # The Demo scheduled for it, as last moved, once there is one -- and its tutor.
        'booking': _booking(booking, now),
        'tutor': _person(booking.assigned_tutor) if booking is not None else None,
        'attempts': len(current.bookings),
        'attention': [{'code': code, 'label': ATTENTION_LABELS[code]} for code in flags],
        'needs_action': needs_action(current, flags),
        'closed': _closed(redemo),
    }


def redemo_detail(redemo, now, user=None, request=None):
    """
    One request in full: the row, which Re-Demo of the chain it is, the
    lead, the original Demo's report, the remarks, every Demo scheduled for
    it, the lead's whole chain of Re-Demos (request_chain), where it has got
    to (``progress``), the parent messages its BDE may send by hand now, and
    what ``user`` may do with it now (``actions``) and with the Demo booked
    for it (``booking_actions``).
    """
    current = state(redemo, now)
    lead = redemo.lead
    manage = user is not None and has_app_permission(user, ASSIGN_BOOKING_TUTOR, request)
    may_close = user is not None and all(
        has_app_permission(user, permission, request) for permission in (VIEW_ALL_BOOKINGS, RESCHEDULE_BOOKING)
    )
    locked = remarks_locked(current)
    booking = current.booking
    live = booking if booking is not None and booking.status == BookingStatus.BOOKED else None
    original_report = report_brief(redemo.demo_booking)
    return {
        **redemo_row(redemo, now, current),
        'number': redemo_number(redemo),
        'timezone': BOOKING_TIMEZONE_NAME,
        'lead': {
            'id': str(lead.id),
            'phone_dial_code': lead.phone_dial_code,
            'phone_number': lead.phone_number,
            'school_name': lead.school_name,
            'grade': lead.grade,
            'syllabus': lead.syllabus,
            'country': lead.country,
            'student_timezone': student_timezones.of(lead),
            'source': lead.source,
            'owner_bde': _person(lead.owner_bde),
        },
        'original_report': (
            {**original_report, 'version_at_request': redemo.original_report_version} if original_report else None
        ),
        'admin_remarks': redemo.admin_remarks,
        'remarks_updated_at': _when(redemo.remarks_updated_at),
        'remarks_updated_by': _person(redemo.remarks_updated_by),
        'remarks_locked': locked,
        'bookings': [_booking(booking, now) for booking in current.bookings],
        'chain': request_chain(redemo, now),
        'progress': progress(redemo, current),
        # The Demo messages' wording, filled in for the parent, while the Re-Demo is still to come.
        'parent_messages': redemo_messages(live, now) if live is not None else None,
        'actions': {
            'schedule': manage and current.status == ReDemoStatus.AWAITING_SCHEDULING,
            'edit_remarks': manage and not locked,
            'close': may_close and current.status == ReDemoStatus.AWAITING_SCHEDULING,
            'reopen': may_close and current.status == ReDemoStatus.CLOSED,
        },
        # What may be done with the Demo booked for it, as that booking's own workspace offers it.
        'booking_actions': (
            {**booking_actions(live, now, user, request), 'change_tutor': manage and tutor_change_refusal(live, now) is None}
            if live is not None else None
        ),
    }


def progress(redemo, current):
    """
    Where the request has got to, step by step: asked for, scheduled, the
    parent's confirmation, taught, reported on, sent to the parent -- each
    done (with when, where it is known), or not yet. A closed request stops
    where it was; the steps after scheduling read the Demo booked last.
    """
    booking = current.booking
    live = booking is not None and booking.status in (BookingStatus.BOOKED, *CONDUCTED)
    report = getattr(booking, 'report', None) if live else None
    shares = sorted(report.shares.all(), key=lambda share: share.shared_at) if report is not None else []
    steps = [
        ('REQUESTED', 'Requested', True, redemo.requested_at),
        ('SCHEDULED', 'Scheduled', live, booking.created_at if live else None),
        ('CONFIRMED', 'Parent confirmed',
         live and booking.parent_confirmation == ParentConfirmation.CONFIRMED,
         booking.parent_confirmation_at if live else None),
        ('TAUGHT', 'Taught', live and booking.started_at is not None, booking.started_at if live else None),
        ('REPORTED', 'Report submitted', report is not None, report.submitted_at if report is not None else None),
        ('SHARED', 'Report shared', bool(shares), shares[0].shared_at if shares else None),
    ]
    return [{'key': key, 'label': label, 'done': bool(done), 'at': _when(at) if done else None}
            for key, label, done, at in steps]


def request_chain(redemo, now):
    """
    The lead's chain of Re-Demos ``redemo`` belongs to, oldest first: each
    request with the Demo it teaches again and the Demo scheduled for it, so
    every Demo -- and its own report -- can be reached from any of them.
    """
    earlier = []
    node = redemo.demo_booking.redemo_for
    while node is not None and len(earlier) < 50:
        earlier.append(node)
        node = node.demo_booking.redemo_for
    later = []
    node = _request_on(state(redemo, now).booking)
    while node is not None and len(later) < 50:
        later.append(node)
        node = _request_on(state(node, now).booking)
    chain = []
    for item in [*reversed(earlier), redemo, *later]:
        current = state(item, now)
        chain.append({
            'id': str(item.id),
            'status': current.status,
            'status_label': ReDemoStatus(current.status).label,
            'requested_at': item.requested_at.isoformat(),
            'original': _booking(item.demo_booking, now),
            'booking': _booking(current.booking, now),
            'current': item.pk == redemo.pk,
        })
    return chain


def _request_on(booking):
    """The Re-Demo request made on ``booking``, or None."""
    if booking is None:
        return None
    return ReDemoRequest.objects.select_related('demo_booking__slot', 'demo_booking__redemo_for').filter(
        demo_booking=booking,
    ).first()


def redemo_rows(redemos, now, status=None):
    """The rows of ``redemos`` (from ``listed``); with ``status`` (a ReDemoStatus), only the requests that stand there."""
    rows = []
    for redemo in redemos:
        current = state(redemo, now)
        if status and current.status != status:
            continue
        rows.append(redemo_row(redemo, now, current))
    return rows


def _order(row):
    """
    The list's order: an administrator's steps first, oldest request first;
    then the Re-Demos to come, soonest first; then those taught, latest first;
    the closed ones last, latest closed first.
    """
    if row['needs_action']:
        return (0, row['requested_at'])
    if row['status'] == ReDemoStatus.SCHEDULED:
        return (1, row['booking']['slot']['starts_at'])
    if row['status'] == ReDemoStatus.COMPLETED:
        return (2, _reversed(row['booking']['slot']['starts_at']))
    return (3, _reversed(row['closed']['at'] if row['closed'] else row['requested_at']))


def _reversed(moment):
    """An ISO instant that sorts latest first."""
    return -datetime.fromisoformat(moment).timestamp()


def worklist(redemos, now, status=None):
    """
    Every row of ``redemos`` in the list's order (_order), the ones ``status``
    keeps -- a ReDemoStatus, or ATTENTION for the open requests with
    something to look at -- and how many stand at each, before ``status``
    narrows them: (rows, counts).
    """
    rows = sorted((redemo_row(redemo, now) for redemo in redemos), key=_order)
    counts = {'ALL': len(rows), **{value: 0 for value in STATUS_FILTERS}}
    for row in rows:
        counts[row['status']] += 1
        if row['attention'] and row['status'] in OPEN_STATUSES:
            counts[ATTENTION] += 1
    if status == ATTENTION:
        rows = [row for row in rows if row['attention'] and row['status'] in OPEN_STATUSES]
    elif status:
        rows = [row for row in rows if row['status'] == status]
    return rows, counts


def owners(redemos):
    """The BDEs who own the leads of ``redemos``, by name: the list's BDE filter."""
    found = {redemo.lead.owner_bde for redemo in redemos if redemo.lead.owner_bde_id}
    return sorted((_person(user) for user in found), key=lambda person: person['full_name'].lower())


# ------------------------------------------------------------------ the student's clock

def student_zone(lead):
    """The zone a lead's student reads times in: (IANA zone, known) -- India's, not known, without one."""
    zone = student_timezones.of(lead)
    return (zone, True) if zone else (BOOKING_TIMEZONE_NAME, False)


def clock(lead, now):
    """What a picker says about the student's clock: the zone shown, whether it is the student's, and its label."""
    zone, known = student_zone(lead)
    return {
        'student_timezone': zone if known else None,
        'display_timezone': zone,
        'display_timezone_label': student_timezones.zone_label(zone, now),
        'student_timezone_known': known,
    }


def student_clock(starts_at, zone):
    """
    The student's own date and time of the instant ``starts_at``, in the IANA
    zone ``zone``, with the zone's name then: what the picker shows first.
    The instant -- and so the slot -- stays the one it is.
    """
    local = starts_at.astimezone(ZoneInfo(zone))
    return {
        'student_date': local.date().isoformat(),
        'student_time': local.strftime('%H:%M'),
        'student_label': student_timezones.zone_label(zone, starts_at),
    }


def _with_student_clock(dates, zone):
    for entry in dates:
        for slot in entry['slots']:
            slot.update(student_clock(datetime.fromisoformat(slot['starts_at']), zone))
    return dates


# ------------------------------------------------------------------ scheduling

def _window_slots(now):
    """The Demo slots the booking pages offer that still have a seat: (starts_at, ends_at) each."""
    return [
        slot_instants(day, entry['time'])
        for day, entries in bookable_window(BookingType.DEMO, now)
        for entry in entries
        if entry['status'] != FULLY_BOOKED
    ]


def _commitments(tutors, slots):
    """Every SCHEDULED class and live booking of ``tutors`` over ``slots``' span, as {tutor id: [(start, end)]}."""
    busy = {tutor.pk: [] for tutor in tutors}
    if not slots or not tutors:
        return busy
    first, last = min(slot[0] for slot in slots), max(slot[1] for slot in slots)
    for session in _overlapping_classes(first, last).filter(tutor__in=tutors):
        busy[session.tutor_id].append((session.start_time, session.end_time))
    for booking in _overlapping_bookings(first, last, assigned_tutor__in=tutors):
        busy[booking.assigned_tutor_id].append((booking.slot.starts_at, booking.slot.ends_at))
    return busy


def _free(slot, busy):
    starts_at, ends_at = slot
    return not any(start < ends_at and end > starts_at for start, end in busy)


def _eligibility(redemo, tutor_id, excluded):
    """Whether ``tutor_id`` may teach ``redemo``'s Re-Demo: (eligible, original, earlier, reason or None)."""
    if tutor_id == redemo.demo_booking.assigned_tutor_id:
        return False, True, False, {'code': RedemoOriginalTutor.code, 'message': ORIGINAL_TUTOR_REASON}
    if tutor_id in excluded:
        return False, False, True, {'code': RedemoEarlierTutor.code, 'message': EARLIER_TUTOR_REASON}
    return True, False, False, None


def tutor_options(redemo, now):
    """
    Every active tutor for the scheduling picker: AVAILABLE with how many
    Demo slots with a seat left in the booking window they are free for, or
    UNAVAILABLE with none; each with the Meet room a Re-Demo of theirs is
    taught in. The tutors who taught a Demo of the chain are listed, marked
    ``original`` (the Demo being repeated) or ``earlier`` and not
    ``eligible``, with why: they never teach this Re-Demo
    (booking_service.check_redemo_tutor). What a picker shows;
    booking_service.schedule_redemo checks the tutor again under its locks.
    """
    excluded = excluded_tutor_ids(redemo)
    tutors = list(assignable_tutors().order_by('full_name', 'email', 'id'))
    slots = _window_slots(now)
    busy = _commitments(tutors, slots)
    rows = []
    for tutor in tutors:
        free = sum(_free(slot, busy[tutor.pk]) for slot in slots)
        eligible, original, earlier, reason = _eligibility(redemo, tutor.pk, excluded)
        if reason is None and not free:
            reason = {'code': 'TUTOR_UNAVAILABLE', 'message': 'No free Demo slot in the booking window.'}
        rows.append({
            'id': str(tutor.pk),
            'full_name': tutor.full_name or tutor.email,
            'email': tutor.email,
            'status': AVAILABLE if free else UNAVAILABLE_TUTOR,
            'free_slots': free,
            'reason': reason,
            'tutor_meet_link': tutor.tutor_meet_link,
            'original': original,
            'earlier': earlier,
            'eligible': eligible,
        })
    return rows


def slot_options(redemo, tutor, now):
    """
    Where ``redemo``'s Re-Demo may be booked with ``tutor``: the Demo slots
    of the booking window as a reschedule's picker shows them
    (coordination.slot_options) for the request's lead, a slot the tutor is
    not free for refused too (TUTOR_BUSY, with why), since the Re-Demo is
    booked with them -- each with the student's own date and time of it
    (student_clock). schedule_redemo checks it all again under its locks.
    """
    dates = booking_slot_options(BookingType.DEMO, redemo.lead, tutor, now)
    for entry in dates:
        for slot in entry['slots']:
            if slot['bookable'] and not slot['tutor_free']:
                slot['bookable'] = False
                slot['unavailable_reason'] = TUTOR_BUSY
    return _with_student_clock(dates, student_zone(redemo.lead)[0])


def time_options(redemo, now):
    """
    Scheduling by time: every Demo slot of the booking window for the
    request's lead (coordination.slot_options, no tutor chosen), each with how
    many tutors who may teach the Re-Demo are free then (``free_tutors``) --
    one with none refused as NO_TUTOR_FREE -- and the student's own date and
    time of it. slot_tutor_options then names them.
    """
    excluded = excluded_tutor_ids(redemo)
    tutors = [tutor for tutor in assignable_tutors() if tutor.pk not in excluded]
    dates = booking_slot_options(BookingType.DEMO, redemo.lead, None, now)
    instants = [
        (datetime.fromisoformat(slot['starts_at']), datetime.fromisoformat(slot['ends_at']))
        for entry in dates for slot in entry['slots']
    ]
    busy = _commitments(tutors, instants)
    for entry in dates:
        for slot in entry['slots']:
            window = (datetime.fromisoformat(slot['starts_at']), datetime.fromisoformat(slot['ends_at']))
            slot['free_tutors'] = sum(_free(window, busy[tutor.pk]) for tutor in tutors)
            if slot['bookable'] and not slot['free_tutors']:
                slot['bookable'] = False
                slot['unavailable_reason'] = NO_TUTOR_FREE
    return _with_student_clock(dates, student_zone(redemo.lead)[0])


def slot_tutor_options(redemo, local_date, local_time, now):
    """
    Scheduling by time, once a slot is chosen -- the Demo slot at the Indian
    ``local_date`` / ``local_time``: the slot as the by-time picker shows it
    (with the student's own date and time) and every active tutor, AVAILABLE
    or UNAVAILABLE for it with why -- a class or a booking of theirs then, or
    having taught a Demo of the chain. Raises DateOutOfWindow or
    SlotUnavailable for a slot the booking pages do not offer.
    schedule_redemo checks it all again under its locks.
    """
    _check_offered(BookingType.DEMO, local_date, local_time, now)
    starts_at, ends_at = slot_instants(local_date, local_time)
    slot = next(
        (slot for entry in time_options(redemo, now) if entry['date'] == local_date.isoformat()
         for slot in entry['slots'] if slot['time'] == local_time.strftime('%H:%M')),
        None,
    )
    excluded = excluded_tutor_ids(redemo)
    tutors = list(assignable_tutors().order_by('full_name', 'email', 'id'))
    conflicts = tutor_conflicts(tutors, starts_at, ends_at)
    rows = []
    for tutor in tutors:
        eligible, original, earlier, reason = _eligibility(redemo, tutor.pk, excluded)
        if reason is None and tutor.pk in conflicts:
            reason = conflict_reason(conflicts[tutor.pk])
        rows.append({
            'id': str(tutor.pk),
            'full_name': tutor.full_name or tutor.email,
            'email': tutor.email,
            'status': AVAILABLE if reason is None else UNAVAILABLE_TUTOR,
            'reason': reason,
            'tutor_meet_link': tutor.tutor_meet_link,
            'original': original,
            'earlier': earlier,
            'eligible': eligible,
        })
    return {'date': local_date.isoformat(), 'slot': slot, 'tutors': rows}


def schedulable(redemo):
    """Whether ``redemo`` may be scheduled now (booking_service.redemo_refusal), with its refusal: (bool, refusal or None)."""
    refusal = redemo_refusal(redemo)
    return refusal is None, ({'code': refusal.code, 'message': refusal.message} if refusal else None)


def parse_day(value):
    """A YYYY-MM-DD query value as a date, or None (ValueError for anything else)."""
    value = (value or '').strip()
    if not value:
        return None
    if len(value) != 10:
        raise ValueError(value)
    return date_type.fromisoformat(value)


# ------------------------------------------------------------------ writing

def set_remarks(redemo, remarks, actor, *, request=None):
    """
    Keep ``remarks`` -- the administrators' remarks for the Re-Demo's tutor,
    '' to clear them -- on ``redemo``; returns (redemo, changed). Refused once
    the Re-Demo they brief has started or been taught (RedemoRemarksLocked):
    they stay what its tutor read. The log says that they changed, never what
    they say.

    Locks: the Re-Demo booked for it, if one is -- its slot, then the booking,
    the locks its tutor's Start takes, so a Start racing this save waits for
    it, or it for the Start, and the check sees the start -- then the request.
    """
    remarks = clean_redemo_remarks(remarks)
    try:
        with transaction.atomic():
            _set_lock_timeout()
            live = DemoBooking.objects.filter(redemo_for=redemo, status=BookingStatus.BOOKED).first()
            if live is not None:
                _locked_booking(live)
            redemo = ReDemoRequest.objects.select_for_update().get(pk=redemo.pk)
            if redemo.admin_remarks == remarks:
                return redemo, False
            if remarks_locked(state(redemo, timezone.now())):
                raise RedemoRemarksLocked()
            redemo.admin_remarks = remarks
            redemo.remarks_updated_at = timezone.now()
            redemo.remarks_updated_by = actor
            redemo.save(update_fields=['admin_remarks', 'remarks_updated_at', 'remarks_updated_by'])
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    log_activity(
        action='redemo.remarks',
        entity_type='redemo_request',
        entity_id=redemo.id,
        entity_label='Re-Demo request',
        context={'booking_id': str(redemo.demo_booking_id), 'lead_id': str(redemo.lead_id), 'cleared': not remarks},
        request=request,
        actor=actor,
    )
    return redemo, True
