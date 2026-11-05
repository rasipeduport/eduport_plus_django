"""
Bookings as the Admin / Coordinator manages them (/api/bookings/<type>/): every
Demo or every Diagnostic booking -- each type its own table
(bookings.models.booking_model) -- whichever BDE's lead it is, with the parent
and child, the slot, the BDE it was credited to and the tutor teaching it --
and, for a booking's slot, every active tutor with whether they are free. Read-only:
every write goes through bookings.booking_service (assign_tutor /
unassign_tutor), which checks it all again under its locks.

The views guard these with accounts.view_all_bookings and
accounts.assign_booking_tutor, which only the ADMIN role may hold. Slot dates
and times are Indian time (bookings.scheduling); every comparison is between
instants (starts_at, ends_at).
"""
import uuid
from datetime import date as date_type

from accounts.authz import has_app_permission
from accounts.models import User
from core.timezones import DATE_PATTERN

from . import enquiries
from .booking_service import (
    CONFLICT_SESSION,
    BookingCancelled,
    BookingCompleted,
    BookingRescheduled,
    BookingStarted,
    CancelledNotMovable,
    LeadAlreadyBooked,
    SlotEnded,
    StartedNotMovable,
    assignable_tutors,
    is_assignable_tutor,
    lead_commitments,
    live_booking,
    tutor_commitments,
    tutor_conflicts,
)
from .lifecycle import activity_state
from .models import BookingEvent, BookingSlot, BookingStatus, CancelReason, Lead, NotConfirmedReason, RescheduleReason
from .scheduling import BOOKING_TIMEZONE, BOOKING_TIMEZONE_NAME, bookable_window, slot_instants

CANCEL_BOOKING = 'accounts.cancel_booking'
RESCHEDULE_BOOKING = 'accounts.reschedule_booking'


AVAILABLE, UNAVAILABLE = 'AVAILABLE', 'UNAVAILABLE'
UPCOMING, PAST = 'upcoming', 'past'
BOOLEANS = {'true': True, 'false': False}
REPORT_FILTERS = {'submitted': True, 'missing': False}
REPORT_DUE = 'due'
MAX_SEARCH_LENGTH = 100


# ------------------------------------------------------------------ the list

def parse_filters(params):
    """
    The list filters from a query string, as (filters, invalid): ``invalid``
    names every parameter whose value is not one the list knows, and nothing
    is guessed for it. Unset parameters are left out of ``filters``. The
    booking type is the list's own (its URL), never a parameter.

        status    BOOKED | COMPLETED | CANCELLED | RESCHEDULED
        assigned  true | false             (whether a tutor is assigned)
        tutor     <account id>             (the assigned tutor)
        slot      <slot id>
        from, to  YYYY-MM-DD               (the slot's Indian date, inclusive)
        when      upcoming | past          (the slot has not ended / has ended)
        report    submitted | missing      (whether the booking has its report)
                  | due                    (started, the slot over, no report: report_summary's report_due)
        q         parent or child name, or phone digits
    """
    filters, invalid = {}, []

    def text(name):
        return (params.get(name) or '').strip()

    def choice(name, values, key):
        value = text(name).upper()
        if value:
            if value in values:
                filters[key] = value
            else:
                invalid.append(name)

    choice('status', BookingStatus.values, 'status')

    assigned = text('assigned').lower()
    if assigned:
        if assigned in BOOLEANS:
            filters['assigned'] = BOOLEANS[assigned]
        else:
            invalid.append('assigned')

    for name, key in (('tutor', 'tutor_id'), ('slot', 'slot_id')):
        value = text(name)
        if value:
            try:
                filters[key] = uuid.UUID(value)
            except ValueError:
                invalid.append(name)

    for name, key in (('from', 'date_from'), ('to', 'date_to')):
        value = text(name)
        if value:
            try:
                if not DATE_PATTERN.match(value):
                    raise ValueError(value)
                filters[key] = date_type.fromisoformat(value)
            except ValueError:
                invalid.append(name)
    if 'date_from' in filters and 'date_to' in filters and filters['date_from'] > filters['date_to']:
        invalid.append('to')

    when = text('when').lower()
    if when:
        if when in (UPCOMING, PAST):
            filters['when'] = when
        else:
            invalid.append('when')

    report = text('report').lower()
    if report:
        if report in REPORT_FILTERS:
            filters['has_report'] = REPORT_FILTERS[report]
        elif report == REPORT_DUE:
            filters['report_due'] = True
        else:
            invalid.append('report')

    q = text('q')
    if q:
        if len(q) > MAX_SEARCH_LENGTH:
            invalid.append('q')
        else:
            filters['q'] = q
    return filters, invalid


def listed(model):
    """Every booking of ``model``'s type (a booking table), with what its rows show."""
    return model.objects.select_related(
        'slot', 'lead', 'lead__owner_bde', 'assigned_tutor', 'attributed_bde', 'tutor_assigned_by', 'cancelled_by',
        'rescheduled_by', 'rescheduled_from__slot', 'rescheduled_to__slot', 'report', 'started_by',
    )


def filtered(bookings, now, status=None, assigned=None, tutor_id=None, slot_id=None,
             date_from=None, date_to=None, when=None, has_report=None, report_due=None, q=None):
    """
    ``bookings`` narrowed by ``parse_filters``' filters, soonest slot first --
    except ``when=past``, most recent first.
    """
    if status:
        bookings = bookings.filter(status=status)
    if assigned is not None:
        bookings = bookings.filter(assigned_tutor__isnull=not assigned)
    if tutor_id:
        bookings = bookings.filter(assigned_tutor_id=tutor_id)
    if slot_id:
        bookings = bookings.filter(slot_id=slot_id)
    if date_from:
        bookings = bookings.filter(slot__local_date__gte=date_from)
    if date_to:
        bookings = bookings.filter(slot__local_date__lte=date_to)
    if when == UPCOMING:
        bookings = bookings.filter(slot__ends_at__gt=now)
    elif when == PAST:
        bookings = bookings.filter(slot__ends_at__lte=now)
    if has_report is not None:
        bookings = bookings.filter(report__isnull=not has_report)
    if report_due:
        # The rows' report_due (report_summary): started, its slot over, and no report.
        bookings = bookings.filter(
            status=BookingStatus.BOOKED, started_at__isnull=False, slot__ends_at__lte=now, report__isnull=True,
        )
    if q:
        # The enquiry search, on the bookings' leads: parent or child name, or phone digits.
        bookings = bookings.filter(lead__in=enquiries.search(Lead.objects.all(), q))
    if when == PAST:
        return bookings.order_by('-slot__starts_at', '-created_at', 'id')
    return bookings.order_by('slot__starts_at', 'created_at', 'id')


# ------------------------------------------------------------------ one booking

def _person(user):
    return {'id': str(user.pk), 'full_name': user.full_name or user.email} if user else None


def _when(value):
    return value.isoformat() if value else None


def slot_brief(slot, now):
    """
    A slot, in Indian time. ``started`` and ``ended`` say whether its scheduled
    start and end have passed -- the slot's clock, never whether a booking in
    it has started: that is the booking's own ``activity_state`` and
    ``started_at`` (bookings.lifecycle).
    """
    return {
        'id': str(slot.id),
        'booking_type': slot.booking_type,
        'date': slot.local_date.isoformat(),
        'time': slot.local_time.strftime('%H:%M'),
        'starts_at': slot.starts_at.isoformat(),
        'ends_at': slot.ends_at.isoformat(),
        'started': slot.starts_at <= now,
        'ended': slot.ends_at <= now,
    }


def tutor_change_refusal(booking, now):
    """Why ``booking``'s tutor cannot be changed now (booking_service's own refusals), or None."""
    if booking.status != BookingStatus.BOOKED:
        refusal = {
            BookingStatus.COMPLETED: BookingCompleted,
            BookingStatus.RESCHEDULED: BookingRescheduled,
        }.get(booking.status, BookingCancelled)
        return {'code': refusal.code, 'message': refusal.message}
    if booking.started_at is not None:
        return {'code': BookingStarted.code, 'message': BookingStarted.message}
    if booking.slot.ends_at <= now:
        return {'code': SlotEnded.code, 'message': SlotEnded.message}
    return None


def booking_row(booking, now):
    """One booking as the list shows it."""
    lead = booking.lead
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'status': booking.status,
        'slot': slot_brief(booking.slot, now),
        'student_name': lead.student_name,
        'grade': lead.grade,
        'parent_name': lead.parent_name,
        'phone': f'{lead.phone_dial_code} {lead.phone_number}',
        'tutor': _person(booking.assigned_tutor),
        # The BDE whose link brought this booking, if one did.
        'bde': _person(booking.attributed_bde),
        'booked_at': booking.created_at.isoformat(),
        # Whether its tutor has started it, and when (bookings.lifecycle): read-only here.
        'activity_state': activity_state(booking, now),
        'started_at': _when(booking.started_at),
        **report_summary(booking, now),
    }


def report_summary(booking, now):
    """
    Whether the booking has its report and at which version, and whether one is
    due: a booking its tutor started whose slot has ended without a report
    stays booked, shown as Report due, until its tutor submits one (design
    B.1). One never started is not due a report -- it is NOT_STARTED
    (bookings.lifecycle). The Admin's rows and the tutor's alike
    (bookings.tutor_bookings).
    """
    report = getattr(booking, 'report', None)
    return {
        'has_report': report is not None,
        'report_version': report.version if report is not None else None,
        'report_due': (
            report is None and booking.status == BookingStatus.BOOKED and booking.started_at is not None
            and booking.slot.ends_at <= now
        ),
    }


def report_brief(booking):
    """The booking's report, as its detail names it -- which version, saved when, by whom -- or None. Its text is …/report/."""
    report = getattr(booking, 'report', None)
    if report is None:
        return None
    return {
        'id': str(report.id),
        'version': report.version,
        'submitted_at': _when(report.submitted_at),
        'submitted_by': _person(report.submitted_by),
        'updated_at': _when(report.updated_at),
    }


def booking_detail(booking, now, user=None, request=None):
    """
    One booking in full: the row, the lead's details, who assigned the tutor,
    any cancellation or move -- with the bookings before and after it in its
    chain -- and what ``user`` may do with it now (``actions``).
    """
    lead = booking.lead
    refusal = tutor_change_refusal(booking, now)
    return {
        **booking_row(booking, now),
        'timezone': BOOKING_TIMEZONE_NAME,
        'seat': booking.seat,
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
        'referral_status': booking.referral_status,
        'tutor_assigned_at': _when(booking.tutor_assigned_at),
        'tutor_assigned_by': _person(booking.tutor_assigned_by),
        # Who started it -- its tutor, by their own Start -- with the row's started_at.
        'started_by': _person(booking.started_by),
        # The Meet room this booking is taught in (its own copy of the tutor's
        # link), or null: no tutor, or one with no link configured.
        'tutor_meet_link': booking.tutor_meet_link,
        'tutor_changeable': refusal is None,
        'tutor_change_refusal': refusal,
        'cancelled_at': _when(booking.cancelled_at),
        'cancelled_by': _person(booking.cancelled_by),
        # A code and its label, never free text (M1).
        'cancel_reason': _label(CancelReason, booking.cancel_reason_code),
        'cancel_reason_code': booking.cancel_reason_code,
        'rescheduled_at': _when(booking.rescheduled_at),
        'rescheduled_by': _person(booking.rescheduled_by),
        'reschedule_reason': _label(RescheduleReason, booking.reschedule_reason_code),
        'reschedule_reason_code': booking.reschedule_reason_code,
        'rescheduled_from': _chain_link(booking.rescheduled_from, now),
        'rescheduled_to': _chain_link(successor(booking), now),
        'report': report_brief(booking),
        'actions': booking_actions(booking, now, user, request),
    }


def _label(choices, code):
    return choices(code).label if code else ''


def successor(booking):
    """The booking that replaced ``booking`` when it was moved, or None."""
    try:
        return booking.rescheduled_to
    except type(booking).DoesNotExist:
        return None


def _chain_link(booking, now):
    if booking is None:
        return None
    return {'id': str(booking.id), 'status': booking.status, 'slot': slot_brief(booking.slot, now)}


def booking_actions(booking, now, user=None, request=None):
    """
    What ``user`` may do with ``booking`` now, by the permissions they hold and
    the rules the service applies: cancel a booked booking, mark it No-show
    once its scheduled time has passed (D12), move it while its tutor has not
    started it (Q23, move_refusal).
    """
    def holds(permission):
        return user is not None and has_app_permission(user, permission, request)

    booked = booking.status == BookingStatus.BOOKED
    cancel = booked and holds(CANCEL_BOOKING)
    return {
        'cancel': cancel,
        'no_show': cancel and booking.slot.starts_at <= now,
        'reschedule': booked and holds(RESCHEDULE_BOOKING) and move_refusal(booking, now) is None,
    }


def move_refusal(booking, now):
    """
    Why ``booking`` cannot be moved now (reschedule_booking's own refusals), or
    None. One whose slot ended with no start may move, unless the lead has
    booked that type again since (LeadAlreadyBooked, Q26).
    """
    if booking.status != BookingStatus.BOOKED:
        refusal = {
            BookingStatus.COMPLETED: BookingCompleted,
            BookingStatus.RESCHEDULED: BookingRescheduled,
        }.get(booking.status, CancelledNotMovable)
        return {'code': refusal.code, 'message': refusal.message}
    if booking.started_at is not None:
        return {'code': StartedNotMovable.code, 'message': StartedNotMovable.message}
    live = live_booking(booking.lead, type(booking), now, exclude_booking=booking)
    if live is not None:
        refusal = LeadAlreadyBooked(live)
        return {'code': refusal.code, 'message': refusal.message}
    return None


# ------------------------------------------------------------------ tutors

def _clock(moment):
    local = moment.astimezone(BOOKING_TIMEZONE)
    return f"{(local.hour % 12) or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def conflict_reason(conflict):
    """
    Why a tutor is not free (a booking_service.TutorConflict), in Indian time:
    the class or booking that holds them, by id and window. Neither the
    class's student nor the booking's child is named.
    """
    local = conflict.starts_at.astimezone(BOOKING_TIMEZONE)
    window = f'{_clock(conflict.starts_at)} to {_clock(conflict.ends_at)} IST on {local:%a} {local.day} {local:%b} {local.year}'
    if conflict.kind == CONFLICT_SESSION:
        return {
            'code': 'CLASS_CONFLICT',
            'message': f'Teaching a class from {window}.',
            'session_id': str(conflict.id),
            'starts_at': conflict.starts_at.isoformat(),
            'ends_at': conflict.ends_at.isoformat(),
        }
    return {
        'code': 'BOOKING_CONFLICT',
        'message': f'Teaching another Demo or Diagnostic booking from {window}.',
        'booking_id': str(conflict.id),
        'booking_type': conflict.booking_type,
        'starts_at': conflict.starts_at.isoformat(),
        'ends_at': conflict.ends_at.isoformat(),
    }


def tutor_availability(slot, booking=None):
    """
    Every active tutor -- the accounts booking_service.assign_tutor accepts --
    each AVAILABLE or UNAVAILABLE for ``slot`` with the reason, and which one
    teaches ``booking`` now (its own assignment does not count against them).
    What a picker shows; the assignment itself checks again under its locks.
    """
    tutors = list(assignable_tutors().order_by('full_name', 'email', 'id'))
    conflicts = tutor_conflicts(tutors, slot.starts_at, slot.ends_at, exclude_booking=booking)
    current = booking.assigned_tutor_id if booking is not None else None
    rows = []
    for tutor in tutors:
        conflict = conflicts.get(tutor.pk)
        rows.append({
            'id': str(tutor.pk),
            'full_name': tutor.full_name or tutor.email,
            'email': tutor.email,
            'status': UNAVAILABLE if conflict else AVAILABLE,
            'reason': conflict_reason(conflict) if conflict else None,
            'current': tutor.pk == current,
        })
    return rows


def lead_conflict_reason(booking):
    """The lead's booking that holds the new time (booking_service.LeadTimeConflict), naming no one."""
    local = booking.slot.starts_at.astimezone(BOOKING_TIMEZONE)
    window = (f'{_clock(booking.slot.starts_at)} to {_clock(booking.slot.ends_at)} IST on '
              f'{local:%a} {local.day} {local:%b} {local.year}')
    return {
        'code': 'LEAD_TIME_CONFLICT',
        'message': f'Already has a {booking.get_booking_type_display()} booking from {window}.',
        'booking_id': str(booking.id),
        'booking_type': booking.booking_type,
        'starts_at': booking.slot.starts_at.isoformat(),
        'ends_at': booking.slot.ends_at.isoformat(),
    }


def tutor_outcome(result):
    """Whether the tutor moved with a rescheduled booking (Q24), and if not, why."""
    if result.tutor is None:
        return {'carried_over': False, 'tutor': None, 'reason': None}
    if result.tutor_carried_over:
        return {'carried_over': True, 'tutor': _person(result.tutor), 'reason': None}
    if result.tutor_not_assignable:
        reason = {'code': 'TUTOR_NOT_ASSIGNABLE', 'message': 'No longer an active tutor.'}
    else:
        reason = conflict_reason(result.tutor_conflict)
    return {'carried_over': False, 'tutor': _person(result.tutor), 'reason': reason}


# ----------------------------------------------------------- rescheduling

def reschedule_options(booking, now):
    """
    Where ``booking`` may move: every slot of its type the public pages offer,
    with its seats, whether the booking could go there and why not -- full,
    closed, its own slot, or the lead already booked then (Q26) -- and, when a
    tutor is assigned, whether they are free there (Q24: they carry over only
    if so). What the Admin's picker shows; reschedule_booking checks it all
    again under its locks.
    """
    window = bookable_window(booking.booking_type, now)
    tutor = booking.assigned_tutor
    tutor_assignable = is_assignable_tutor(tutor)
    # Read the tutor's and the lead's commitments once, over the whole window.
    instants = [slot_instants(day, entry['time']) for day, entries in window for entry in entries]
    tutor_busy, lead_busy = [], []
    if instants:
        first, last = min(start for start, _end in instants), max(end for _start, end in instants)
        if tutor is not None and tutor_assignable:
            tutor_busy = tutor_commitments(tutor, first, last, exclude_booking=booking)
        lead_busy = lead_commitments(booking.lead, first, last, exclude_booking=booking)
    dates = []
    for day, entries in window:
        slots = []
        for entry in entries:
            starts_at, ends_at = slot_instants(day, entry['time'])
            current = day == booking.slot.local_date and entry['time'] == booking.slot.local_time
            clash = next((b for b in lead_busy if b.slot.starts_at < ends_at and b.slot.ends_at > starts_at), None)
            seats_left = 0 if entry['closed'] else max(entry['capacity'] - entry['booked'], 0)
            if current:
                why = 'CURRENT'
            elif entry['closed']:
                why = 'CLOSED'
            elif seats_left == 0:
                why = 'FULL'
            elif clash is not None:
                why = 'LEAD_TIME_CONFLICT'
            else:
                why = None
            tutor_free, tutor_reason = None, None
            if tutor is not None:
                busy = next((c for c in tutor_busy if c.starts_at < ends_at and c.ends_at > starts_at), None)
                tutor_free = tutor_assignable and busy is None
                if not tutor_assignable:
                    tutor_reason = {'code': 'TUTOR_NOT_ASSIGNABLE', 'message': 'No longer an active tutor.'}
                elif busy is not None:
                    tutor_reason = conflict_reason(busy)
            slots.append({
                'time': entry['time'].strftime('%H:%M'),
                'starts_at': starts_at.isoformat(),
                'ends_at': ends_at.isoformat(),
                'status': entry['status'],
                'seats_left': seats_left,
                'bookable': why is None,
                'unavailable_reason': why,
                'lead_conflict': lead_conflict_reason(clash) if clash is not None else None,
                'tutor_free': tutor_free,
                'tutor_reason': tutor_reason,
            })
        dates.append({'date': day.isoformat(), 'slots': slots})
    refusal = move_refusal(booking, now)
    return {
        'booking_id': str(booking.id),
        'booking_type': booking.booking_type,
        'timezone': BOOKING_TIMEZONE_NAME,
        'slot': slot_brief(booking.slot, now),
        'tutor': _person(tutor),
        'reschedulable': refusal is None,
        'refusal': refusal,
        'dates': dates,
    }


# --------------------------------------------------------------- history

EVENT_TUTOR_KEYS = ('old_tutor_id', 'new_tutor_id')
EVENT_SLOT_KEYS = ('slot_id', 'old_slot_id', 'new_slot_id')


def chain_of(booking):
    """``booking``'s reschedule chain, oldest first: the bookings it replaced, itself, and those that replaced it."""
    model = type(booking)
    earlier = []
    node = booking
    while node.rescheduled_from_id:
        node = model.objects.select_related('slot').get(pk=node.rescheduled_from_id)
        earlier.append(node)
    later = []
    node = successor(booking)
    while node is not None:
        node = model.objects.select_related('slot').get(pk=node.pk)
        later.append(node)
        node = successor(node)
    return [*reversed(earlier), booking, *later]


def booking_history(booking, now):
    """
    ``booking``'s timeline (design B.6): every event of every booking in its
    chain, oldest first, each with who did it and what it changed -- slots,
    tutors and reasons read back from the ids and codes the history keeps.
    Staff only: it names staff, never a child or parent.
    """
    chain = chain_of(booking)
    column = 'diagnostic_booking' if booking.booking_type == 'DIAGNOSTIC' else 'demo_booking'
    events = list(
        BookingEvent.objects.filter(**{f'{column}__in': [b.pk for b in chain]})
        .select_related('actor')
        .order_by('created_at', 'id')
    )
    tutor_ids = {e.data.get(key) for e in events for key in EVENT_TUTOR_KEYS if e.data.get(key)}
    slot_ids = {e.data.get(key) for e in events for key in EVENT_SLOT_KEYS if e.data.get(key)}
    tutors = {str(u.pk): u for u in User.objects.filter(pk__in=tutor_ids)}
    slots = {str(slot.pk): slot for slot in BookingSlot.objects.filter(pk__in=slot_ids)}
    reasons = {'CANCELLED': CancelReason, 'RESCHEDULED': RescheduleReason, 'PARENT_NOT_CONFIRMED': NotConfirmedReason}

    def details(event):
        data = event.data
        out = {}
        for key, value in data.items():
            if key in EVENT_TUTOR_KEYS:
                out[key.removesuffix('_id')] = _person(tutors.get(value)) if value else None
            elif key in EVENT_SLOT_KEYS:
                out[key.removesuffix('_id')] = slot_brief(slots[value], now) if value in slots else None
            elif key == 'reason_code':
                choices = reasons.get(event.kind)
                out['reason'] = {'code': value, 'label': _label(choices, value) if choices else value}
            else:
                out[key] = value
        return out

    return {
        'booking_id': str(booking.id),
        'timezone': BOOKING_TIMEZONE_NAME,
        'chain': [{**_chain_link(b, now), 'current': b.pk == booking.pk} for b in chain],
        'events': [
            {
                'id': str(event.id),
                'booking_id': str(event.diagnostic_booking_id or event.demo_booking_id),
                'kind': event.kind,
                'kind_label': event.get_kind_display(),
                'at': event.created_at.isoformat(),
                'actor': _person(event.actor),
                'details': details(event),
            }
            for event in events
        ],
    }
