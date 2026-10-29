"""
Bookings as the Admin / Coordinator manages them (/api/bookings/): every Demo
and Diagnostic booking, whichever BDE's lead it is, with the parent and child,
the slot, the BDE it was credited to and the tutor teaching it -- and, for a
booking's slot, every active tutor with whether they are free. Read-only:
every write goes through bookings.booking_service (assign_tutor /
unassign_tutor), which checks it all again under its locks.

The views guard these with accounts.view_all_bookings and
accounts.assign_booking_tutor, which only the ADMIN role may hold. Slot dates
and times are Indian time (bookings.scheduling); every comparison is between
instants (starts_at, ends_at).
"""
import uuid
from datetime import date as date_type

from core.timezones import DATE_PATTERN

from . import enquiries
from .booking_service import (
    CONFLICT_SESSION,
    BookingCancelled,
    SlotStarted,
    assignable_tutors,
    tutor_conflicts,
)
from .models import Booking, BookingStatus, BookingType, Lead
from .scheduling import BOOKING_TIMEZONE, BOOKING_TIMEZONE_NAME

AVAILABLE, UNAVAILABLE = 'AVAILABLE', 'UNAVAILABLE'
UPCOMING, PAST = 'upcoming', 'past'
BOOLEANS = {'true': True, 'false': False}
MAX_SEARCH_LENGTH = 100


# ------------------------------------------------------------------ the list

def parse_filters(params):
    """
    The list filters from a query string, as (filters, invalid): ``invalid``
    names every parameter whose value is not one the list knows, and nothing
    is guessed for it. Unset parameters are left out of ``filters``.

        type      DEMO | DIAGNOSTIC
        status    BOOKED | CANCELLED
        assigned  true | false             (whether a tutor is assigned)
        tutor     <account id>             (the assigned tutor)
        slot      <slot id>
        from, to  YYYY-MM-DD               (the slot's Indian date, inclusive)
        when      upcoming | past          (the slot has not ended / has ended)
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

    choice('type', BookingType.values, 'booking_type')
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

    q = text('q')
    if q:
        if len(q) > MAX_SEARCH_LENGTH:
            invalid.append('q')
        else:
            filters['q'] = q
    return filters, invalid


def listed():
    """Every booking, with what its rows show."""
    return Booking.objects.select_related(
        'slot', 'lead', 'lead__owner_bde', 'assigned_tutor', 'attributed_bde', 'tutor_assigned_by', 'cancelled_by',
    )


def filtered(bookings, now, booking_type=None, status=None, assigned=None, tutor_id=None, slot_id=None,
             date_from=None, date_to=None, when=None, q=None):
    """
    ``bookings`` narrowed by ``parse_filters``' filters, soonest slot first --
    except ``when=past``, most recent first.
    """
    if booking_type:
        bookings = bookings.filter(booking_type=booking_type)
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
        return {'code': BookingCancelled.code, 'message': BookingCancelled.message}
    if booking.slot.starts_at <= now:
        return {'code': SlotStarted.code, 'message': SlotStarted.message}
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
    }


def booking_detail(booking, now):
    """One booking in full: the row, the lead's details, who assigned the tutor, and any cancellation."""
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
        'tutor_changeable': refusal is None,
        'tutor_change_refusal': refusal,
        'cancelled_at': _when(booking.cancelled_at),
        'cancelled_by': _person(booking.cancelled_by),
        'cancel_reason': booking.cancel_reason,
    }


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
