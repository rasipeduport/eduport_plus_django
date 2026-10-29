"""
Bookings as the tutor teaching them sees them (/api/tutor/bookings/): the Demo
and Diagnostic bookings assigned to the tutor now, each with its slot in
Indian time and the child it is for -- name, class, syllabus, school and
country -- and nothing more. Read-only: the tutor is assigned, changed and
unassigned only by the Admin / Coordinator (bookings.booking_service).

What a tutor is shown is written out field by field below, never taken from a
model or from bookings.coordination's rows, so nothing reaches a tutor by
being added elsewhere: not the parent's name or phone, not Booking.details
(the submission, which holds both), not the BDE or the referral, not who
assigned the tutor or when, not the cancellation's reason or author, nor the
lead's own id.

The views guard these with accounts.view_assigned_bookings, which only the
TUTOR role may hold. Which bookings are read is the caller's alone: always
``assigned_to(request.user)``, whatever a request says.
"""
from .coordination import PAST, UPCOMING, filtered, slot_brief
from .models import Booking, BookingType
from .scheduling import BOOKING_TIMEZONE_NAME

ALL = 'all'

# The child, from the booking's lead -- never the parent.
STUDENT_FIELDS = ('student_name', 'grade', 'syllabus', 'school_name', 'country')
# The slot, in Indian time (coordination.slot_brief), without its own id.
SLOT_FIELDS = ('date', 'time', 'starts_at', 'ends_at', 'started', 'ended')


def parse_filters(params):
    """
    The list filters from a query string, as (filters, invalid): ``invalid``
    names every parameter whose value is not one the list knows. No other
    parameter is read -- a ``tutor`` one, say, never is.

        type  DEMO | DIAGNOSTIC
        when  upcoming (the default: the slot has not ended) | past | all
    """
    filters, invalid = {'when': UPCOMING}, []
    booking_type = (params.get('type') or '').strip().upper()
    if booking_type:
        if booking_type in BookingType.values:
            filters['booking_type'] = booking_type
        else:
            invalid.append('type')
    when = (params.get('when') or '').strip().lower()
    if when:
        if when in (UPCOMING, PAST):
            filters['when'] = when
        elif when == ALL:
            filters['when'] = None
        else:
            invalid.append('when')
    return filters, invalid


def assigned_to(tutor):
    """
    The bookings ``tutor`` is assigned now, booked or cancelled (a cancelled
    booking keeps its tutor), and no others: one reassigned or unassigned is
    no longer theirs.
    """
    return Booking.objects.filter(assigned_tutor=tutor).select_related('slot', 'lead')


def listed(tutor, now, booking_type=None, when=UPCOMING):
    """``tutor``'s bookings narrowed by ``parse_filters``' filters, soonest slot first (``when=past``: most recent first)."""
    return filtered(assigned_to(tutor), now, booking_type=booking_type, when=when)


def booking_row(booking, now):
    """One booking as its tutor is shown it, in the list and in full alike."""
    slot = slot_brief(booking.slot, now)
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'status': booking.status,
        'slot': {field: slot[field] for field in SLOT_FIELDS},
        **{field: getattr(booking.lead, field) for field in STUDENT_FIELDS},
    }


def booking_detail(booking, now):
    """One booking in full: the row, and the time zone its slot is in."""
    return {**booking_row(booking, now), 'timezone': BOOKING_TIMEZONE_NAME}
