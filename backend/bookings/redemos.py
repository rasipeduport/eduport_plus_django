"""
Re-Demos: teaching a lead's completed Demo again.

1. Request. An administrator -- or the BDE who owns the lead -- asks for a
   Re-Demo of a COMPLETED Demo, giving the reason
   (booking_service.request_redemo). The Demo is RE-DEMO REQUIRED at once,
   with no approval step, and otherwise kept as it was: its tutor, slot,
   report and history.
2. Scheduling. An administrator picks the tutor -- the original one or
   another active tutor -- a date and a time that tutor is free for, and
   adds remarks for them; confirming books the Re-Demo straight away
   (booking_service.schedule_redemo): a new Demo of the lead with that tutor
   and their Meet link, naming the request (DemoBooking.redemo_for). Nothing
   is sent to the parent -- no link, no message: a Re-Demo has no
   communication plan (communications.planner) -- and the BDE tells them the
   confirmed time by hand.
3. Teaching. The Re-Demo is a Demo booking: started, taught, reported on --
   a report of its own; the Demo taught before keeps its own -- moved,
   given another tutor and cancelled as any booking is. Its tutor sees it
   as a RE-DEMO, with the Demo it follows, the reason and the remarks
   (bookings.tutor_bookings). Cancelled, it leaves the request to be
   scheduled again.
4. Again. Once the Re-Demo is taught it may have a Re-Demo of its own: each
   request names the Demo it teaches again, and the Demo scheduled for it
   names the request, so a lead's Re-Demos form a chain (request_chain).

Where a request stands is bookings.redemo_chain's. Who may do what is the
views' check, made again under the locks where it depends on the lead's
owner: an administrator (accounts.view_all_bookings, and
accounts.assign_booking_tutor to schedule a request or change its remarks)
for any lead; a BDE asks only for their own leads. The reason and the
remarks are staff's words, kept on the request: no booking history,
activity log or parent sees them, and the BDE never sees the remarks.
Every write logs ids only.
"""
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity

from . import enquiries
from .booking_service import (
    _overlapping_bookings,
    _overlapping_classes,
    assignable_tutors,
    clean_redemo_remarks,
    redemo_refusal,
)
from .coordination import report_brief, slot_brief, slot_options as booking_slot_options
from .lifecycle import activity_state
from .models import BookingType, DemoBooking, Lead, ReDemoRequest, ReDemoStatus
from .redemo_chain import redemo_number, state
from .scheduling import BOOKING_TIMEZONE_NAME, FULLY_BOOKED, bookable_window, slot_instants

AVAILABLE, UNAVAILABLE_TUTOR = 'AVAILABLE', 'UNAVAILABLE'
ASSIGN_BOOKING_TUTOR = 'accounts.assign_booking_tutor'
# A slot open for the child whose chosen tutor is not free then (slot_options).
TUTOR_BUSY = 'TUTOR_BUSY'


# ------------------------------------------------------------------ reading

def listed():
    """Every Re-Demo request, with what its rows show: the lead, the Demo to teach again and the Demos scheduled for it."""
    bookings = DemoBooking.objects.select_related('slot', 'assigned_tutor', 'report')
    return ReDemoRequest.objects.select_related(
        'lead', 'lead__owner_bde', 'demo_booking__slot', 'demo_booking__assigned_tutor', 'demo_booking__report',
        'demo_booking__redemo_for', 'requested_by', 'remarks_updated_by',
    ).prefetch_related(Prefetch('bookings', queryset=bookings))


def search(redemos, q):
    """Requests whose lead matches ``q``: the parent's or student's name, or phone digits (the enquiry search)."""
    if not (q or '').strip():
        return redemos
    return redemos.filter(lead__in=enquiries.search(Lead.objects.all(), q))


def _person(user):
    return {'id': str(user.pk), 'full_name': user.full_name or user.email} if user else None


def _when(value):
    return value.isoformat() if value else None


def _report(booking):
    report = getattr(booking, 'report', None)
    return {'has_report': report is not None, 'report_version': report.version if report is not None else None}


def _booking(booking, now):
    """A Demo of the chain as the Re-Demo views link to it: when, its status, its tutor, its Meet room and its report."""
    if booking is None:
        return None
    return {
        'id': str(booking.id),
        'status': booking.status,
        'slot': slot_brief(booking.slot, now),
        'tutor': _person(booking.assigned_tutor),
        'tutor_meet_link': booking.tutor_meet_link,
        'activity_state': activity_state(booking, now),
        **_report(booking),
    }


def redemo_row(redemo, now, redemo_state=None):
    """One request as the Re-Demo list shows it."""
    current = redemo_state or state(redemo, now)
    lead = redemo.lead
    booking = current.booking
    return {
        'id': str(redemo.id),
        'status': current.status,
        'status_label': ReDemoStatus(current.status).label,
        'requested_at': redemo.requested_at.isoformat(),
        'requested_by': _person(redemo.requested_by),
        'reason': redemo.reason,
        'student_name': lead.student_name,
        'grade': lead.grade,
        'parent_name': lead.parent_name,
        'phone': f'{lead.phone_dial_code} {lead.phone_number}',
        'owner_bde': _person(lead.owner_bde),
        # The Demo to teach again, with its original tutor and report.
        'original': _booking(redemo.demo_booking, now),
        # The Demo scheduled for it, as last moved, once there is one -- and its tutor.
        'booking': _booking(booking, now),
        'tutor': _person(booking.assigned_tutor) if booking is not None else None,
    }


def redemo_detail(redemo, now, user=None, request=None):
    """
    One request in full: the row, which Re-Demo of the chain it is, the
    lead, the original Demo's report, the remarks, every Demo scheduled for
    it, the lead's whole chain of Re-Demos (request_chain) and what ``user``
    may do with it now (``actions``).
    """
    current = state(redemo, now)
    lead = redemo.lead
    manage = user is not None and has_app_permission(user, ASSIGN_BOOKING_TUTOR, request)
    return {
        **redemo_row(redemo, now, current),
        'number': redemo_number(redemo),
        'timezone': BOOKING_TIMEZONE_NAME,
        'lead': {
            'id': str(lead.id),
            'phone_dial_code': lead.phone_dial_code,
            'phone_number': lead.phone_number,
            'school_name': lead.school_name,
            'syllabus': lead.syllabus,
            'country': lead.country,
            'source': lead.source,
            'owner_bde': _person(lead.owner_bde),
        },
        'original_report': report_brief(redemo.demo_booking),
        'admin_remarks': redemo.admin_remarks,
        'remarks_updated_at': _when(redemo.remarks_updated_at),
        'remarks_updated_by': _person(redemo.remarks_updated_by),
        'bookings': [_booking(booking, now) for booking in current.bookings],
        'chain': request_chain(redemo, now),
        'actions': {
            'schedule': manage and current.status == ReDemoStatus.AWAITING_SCHEDULING,
            'edit_remarks': manage,
        },
    }


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


def tutor_options(redemo, now):
    """
    Every active tutor for the scheduling picker: AVAILABLE with how many
    Demo slots with a seat left in the booking window they are free for, or
    UNAVAILABLE with none; each with the Meet room a Re-Demo of theirs is
    taught in, and the original Demo's tutor marked. What a picker shows;
    booking_service.schedule_redemo checks the tutor again under its locks.
    """
    tutors = list(assignable_tutors().order_by('full_name', 'email', 'id'))
    slots = _window_slots(now)
    busy = _commitments(tutors, slots)
    rows = []
    for tutor in tutors:
        free = sum(_free(slot, busy[tutor.pk]) for slot in slots)
        rows.append({
            'id': str(tutor.pk),
            'full_name': tutor.full_name or tutor.email,
            'email': tutor.email,
            'status': AVAILABLE if free else UNAVAILABLE_TUTOR,
            'free_slots': free,
            'reason': None if free else {'code': 'TUTOR_UNAVAILABLE', 'message': 'No free Demo slot in the booking window.'},
            'tutor_meet_link': tutor.tutor_meet_link,
            'original': tutor.pk == redemo.demo_booking.assigned_tutor_id,
        })
    return rows


def slot_options(redemo, tutor, now):
    """
    Where ``redemo``'s Re-Demo may be booked with ``tutor``: the Demo slots
    of the booking window as a reschedule's picker shows them
    (coordination.slot_options) for the request's lead, a slot the tutor is
    not free for refused too (TUTOR_BUSY, with why), since the Re-Demo is
    booked with them. schedule_redemo checks it all again under its locks.
    """
    dates = booking_slot_options(BookingType.DEMO, redemo.lead, tutor, now)
    for entry in dates:
        for slot in entry['slots']:
            if slot['bookable'] and not slot['tutor_free']:
                slot['bookable'] = False
                slot['unavailable_reason'] = TUTOR_BUSY
    return dates


def schedulable(redemo):
    """Whether ``redemo`` may be scheduled now (booking_service.redemo_refusal), with its refusal: (bool, refusal or None)."""
    refusal = redemo_refusal(redemo)
    return refusal is None, ({'code': refusal.code, 'message': refusal.message} if refusal else None)


# ------------------------------------------------------------------ writing

def set_remarks(redemo, remarks, actor, *, request=None):
    """
    Keep ``remarks`` -- the administrators' remarks for the Re-Demo's tutor,
    '' to clear them -- on ``redemo``; returns (redemo, changed). The log
    says that they changed, never what they say.
    """
    remarks = clean_redemo_remarks(remarks)
    with transaction.atomic():
        redemo = ReDemoRequest.objects.select_for_update().get(pk=redemo.pk)
        if redemo.admin_remarks == remarks:
            return redemo, False
        redemo.admin_remarks = remarks
        redemo.remarks_updated_at = timezone.now()
        redemo.remarks_updated_by = actor
        redemo.save(update_fields=['admin_remarks', 'remarks_updated_at', 'remarks_updated_by'])
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
