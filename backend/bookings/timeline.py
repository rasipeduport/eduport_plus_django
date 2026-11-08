"""
History: what happened to a student's bookings, one entry per change, as
each booking's history keeps it (bookings.BookingEvent: written in the same
transaction as the change and never updated or deleted, by its database
trigger). Nothing here writes; each entry is read back from its event every
time, with the slots, tutors and reason codes it names.

Each entry says when, what happened, to which booking, who did it -- a staff
member by name and role, the parent (a booking made on a public page or with
an invitation), or the system -- and what changed: the slot before and after
a move, the tutor before and after a change, the status before and after,
and for a cancellation, move, parent non-confirmation or Re-Demo closure its
reason, always a code from a fixed list, never words. Never a parent's or
student's name or phone, a Meet link, report text, or staff's own words (a
Re-Demo's reason and remarks stay on the request).

Who reads which history is the views':

    ADMIN   any student's: every event of all their bookings (lead_bookings),
            with the ids an administrator's screens link by
    BDE     their own lead's, the same events, less the parent's answers
            without accounts.view_own_lead_communications -- the answer
            events, and a cancellation's "Parent did not confirm" reason --
            and report edits without accounts.view_own_lead_reports, as their
            activity feed hides them (bookings.bde_activity)
    TUTOR   one booking assigned to them now: its own events and those of the
            bookings it replaced when moved, and for a Re-Demo those of the
            Demos it repeats (tutor_bookings) -- but a Re-Demo request made on
            their own booking stays hidden from them, as their booking's
            status does (bookings.tutor_bookings: the request is not theirs),
            and so do the parent's answers, which no tutor reads. Who asked
            for a Re-Demo, closed or reopened its request, and who scheduled
            it -- its booking and its tutor -- is never named to a tutor
            (bookings.tutor_bookings): those steps say only that staff did them.
"""
from django.db.models import Q

from accounts.models import User

from . import student_timezones
from .coordination import chain_of
from .models import (
    BOOKING_MODELS,
    CONDUCTED,
    BookingEvent,
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    NotConfirmedReason,
    RedemoCloseReason,
    RescheduleReason,
)
from .redemo_chain import taught_before
from .scheduling import BOOKING_TIMEZONE_NAME

ADMIN, BDE, TUTOR = 'ADMIN', 'BDE', 'TUTOR'
# Who did it, when the event names no account.
STAFF, PARENT, SYSTEM = 'STAFF', 'PARENT', 'SYSTEM'
# The bookings a parent makes themselves: a public page, or a Demo invitation's page.
PARENT_ORIGINS = ('public_booking', 'demo_invite')

REASONS = {
    BookingEventKind.CANCELLED: CancelReason,
    BookingEventKind.RESCHEDULED: RescheduleReason,
    BookingEventKind.PARENT_NOT_CONFIRMED: NotConfirmedReason,
    BookingEventKind.REDEMO_CLOSED: RedemoCloseReason,
}
REDEMO_REQUEST_KINDS = (
    BookingEventKind.REDEMO_REQUESTED, BookingEventKind.REDEMO_CLOSED, BookingEventKind.REDEMO_REOPENED,
)
COMMUNICATION_KINDS = (BookingEventKind.PARENT_CONFIRMED, BookingEventKind.PARENT_NOT_CONFIRMED)
REPORT_KINDS = (BookingEventKind.REPORT_EDITED,)
SLOT_KEYS = ('slot_id', 'old_slot_id', 'new_slot_id')
TUTOR_KEYS = ('old_tutor_id', 'new_tutor_id')
# What an entry may say beyond its slots, tutors and reason, for the BDE and the tutor.
SHARED_KEYS = ('via', 'from_status', 'to_status', 'version', 'changed_fields', 'has_meet_link')
# ... and what an administrator's screens also read: ids to link by, the seat and the referral.
ADMIN_KEYS = (
    *SHARED_KEYS, 'seat', 'referral_status', 'redemo_request_id', 'replacement_id', 'rescheduled_from_id',
)


def lead_bookings(lead):
    """Every booking of ``lead``, of both types, with its slot."""
    return [booking for model in BOOKING_MODELS for booking in model.objects.filter(lead=lead).select_related('slot')]


def tutor_bookings(booking):
    """
    The bookings whose history the tutor teaching ``booking`` reads: its
    reschedule chain, and for a Re-Demo every Demo it repeats with theirs.
    Returns (bookings, own): ``own`` the ids of ``booking``'s own chain.
    """
    own = chain_of(booking)
    found = list(own)
    if isinstance(booking, DemoBooking) and booking.redemo_for_id:
        for demo in taught_before(booking.redemo_for):
            found.extend(chain_of(DemoBooking.objects.select_related('slot').get(pk=demo.pk)))
    seen, bookings = set(), []
    for item in found:
        if (type(item), item.pk) not in seen:
            seen.add((type(item), item.pk))
            bookings.append(item)
    return bookings, {item.pk for item in own}


def events_of(bookings):
    """The events of ``bookings``, oldest first."""
    demo = [b.pk for b in bookings if isinstance(b, DemoBooking)]
    diagnostic = [b.pk for b in bookings if not isinstance(b, DemoBooking)]
    return (
        BookingEvent.objects.filter(Q(demo_booking_id__in=demo) | Q(diagnostic_booking_id__in=diagnostic))
        .select_related('actor')
        .order_by('created_at', 'id')
    )


def visible(events, audience, *, show_communication=True, show_reports=True, own=()):
    """``events`` less what ``audience`` may not read (see the module's table)."""
    hidden = []
    if audience == BDE:
        hidden += [*(() if show_communication else COMMUNICATION_KINDS), *(() if show_reports else REPORT_KINDS)]
    if audience == TUTOR:
        hidden += COMMUNICATION_KINDS
    events = events.exclude(kind__in=hidden) if hidden else events
    if audience == TUTOR and own:
        events = events.exclude(kind__in=REDEMO_REQUEST_KINDS, demo_booking_id__in=list(own))
    return events


def rows(events, bookings, audience, *, show_communication=True):
    """
    ``events`` (from events_of, narrowed by visible) as History entries for
    ``audience``; ``show_communication`` as visible was given it (a tutor
    never reads the parent's answers).
    """
    events = list(events)
    by_id = {(type(b).BOOKING_TYPE, b.pk): b for b in bookings}
    slot_ids = {e.data.get(key) for e in events for key in SLOT_KEYS if e.data.get(key)}
    slots = {str(slot.pk): slot for slot in BookingSlot.objects.filter(pk__in=slot_ids)}
    tutor_ids = {e.data.get(key) for e in events for key in TUTOR_KEYS if e.data.get(key)}
    tutors = {str(user.pk): user for user in User.objects.filter(pk__in=tutor_ids)}
    keys = ADMIN_KEYS if audience == ADMIN else SHARED_KEYS
    answers = show_communication and audience != TUTOR
    return [_row(event, by_id, slots, tutors, keys, audience, answers) for event in events]


def _slot(slot):
    if slot is None:
        return None
    return {
        'date': slot.local_date.isoformat(),
        'time': slot.local_time.strftime('%H:%M'),
        'starts_at': slot.starts_at.isoformat(),
    }


def _row(event, by_id, slots, tutors, keys, audience, answers):
    data = event.data or {}
    booking_type = 'DIAGNOSTIC' if event.diagnostic_booking_id else 'DEMO'
    booking = by_id.get((booking_type, event.diagnostic_booking_id or event.demo_booking_id))
    details = {key: data[key] for key in keys if key in data}
    for key in SLOT_KEYS:
        if key in data:
            details[key.removesuffix('_id')] = _slot(slots.get(data[key]))
    for key in TUTOR_KEYS:
        if key in data:
            tutor = tutors.get(data[key]) if data[key] else None
            details[key.removesuffix('_id')] = {'full_name': tutor.full_name or tutor.email} if tutor else None
    choices = REASONS.get(event.kind)
    code = data.get('reason_code')
    # "Parent did not confirm" is the parent's answer: only for whoever may read the answers.
    if choices is not None and code and (answers or code != CancelReason.NOT_CONFIRMED):
        details['reason'] = {'code': code, 'label': choices(code).label if code in choices.values else code}
    return {
        'id': str(event.id),
        'at': event.created_at.isoformat(),
        'kind': event.kind,
        'kind_label': event.get_kind_display(),
        'booking': {
            'id': str(event.diagnostic_booking_id or event.demo_booking_id),
            'booking_type': booking_type,
            'slot': _slot(booking.slot) if booking is not None else None,
            'redemo': bool(getattr(booking, 'redemo_for_id', None)),
        },
        **_who(event, data, audience),
        'details': details,
    }


def _who(event, data, audience):
    """
    Who did it: ``by`` (STAFF, PARENT or SYSTEM) and, for a staff member,
    their name and role -- but for a tutor, never who asked for a Re-Demo,
    closed or reopened its request, or scheduled it (``via`` redemo: its
    booking and its tutor): staff, unnamed.
    """
    actor = event.actor
    if actor is not None and audience == TUTOR and (
        event.kind in REDEMO_REQUEST_KINDS or data.get('via') == 'redemo'
    ):
        return {'by': STAFF, 'actor': None}
    if actor is not None:
        return {
            'by': STAFF,
            'actor': {'full_name': actor.full_name or actor.email, 'role': actor.role, 'role_label': actor.get_role_display()},
        }
    parent = event.kind == BookingEventKind.CREATED and data.get('via') in PARENT_ORIGINS
    return {'by': PARENT if parent else SYSTEM, 'actor': None}


def payload(entries, bookings, audience, *, lead=None, current=None, chain=()):
    """
    A History response: its entries oldest first, the bookings they belong to
    (for the booking filter, soonest slot first), and -- from a booking's own
    workspace -- that booking (``current``) and the ids of its reschedule
    chain (``chain``), what "This booking" shows -- and the zone ``lead``'s
    student books from, for their own time of each slot (null when not
    known). A tutor reads a Demo sent for a Re-Demo as Completed, as their
    booking lists do.
    """
    def status(booking):
        if audience == TUTOR and booking.status in CONDUCTED:
            return BookingStatus.COMPLETED
        return booking.status

    ordered = sorted(bookings, key=lambda b: (b.slot.starts_at, b.created_at))
    return {
        'timezone': BOOKING_TIMEZONE_NAME,
        'student_timezone': student_timezones.of(lead) if lead is not None else None,
        'booking_id': str(current.pk) if current is not None else None,
        'chain_ids': [str(pk) for pk in chain],
        'bookings': [
            {
                'id': str(b.pk),
                'booking_type': b.BOOKING_TYPE,
                'status': status(b),
                'slot': _slot(b.slot),
                'redemo': bool(getattr(b, 'redemo_for_id', None)),
            }
            for b in ordered
        ],
        'entries': entries,
    }
