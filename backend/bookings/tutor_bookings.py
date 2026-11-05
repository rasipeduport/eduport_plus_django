"""
Bookings as the tutor teaching them sees them (/api/tutor/bookings/): the Demo
and Diagnostic bookings assigned to the tutor now, each with its slot in
Indian time, the child it is for -- name, class, syllabus, school and
country -- and the Google Meet room it is taught in, and nothing more. The
tutor's one write here is Start (booking_service.start_booking), offered by
each booking's ``actions.start``; the tutor is assigned, changed and
unassigned only by the Admin / Coordinator (bookings.booking_service).

What a tutor is shown is written out field by field below, never taken from a
model or from bookings.coordination's rows, so nothing reaches a tutor by
being added elsewhere: not the parent's name or phone, not a booking's
``details`` (the submission, which holds both), not the BDE or the referral,
not who assigned the tutor or when, not the cancellation's reason or author,
nor the lead's own id.

The views guard these with accounts.view_assigned_bookings, which only the
TUTOR role may hold. Which bookings are read is the caller's alone: always
``assigned_to(request.user)``, whatever a request says.
"""
from .booking_service import (
    CancelledNotStartable,
    CompletedNotStartable,
    RescheduledNotStartable,
    StartTooEarly,
    StartWindowClosed,
)
from .coordination import PAST, UPCOMING, filtered, report_summary, slot_brief
from .lifecycle import activity_state, start_opens_at
from .models import BOOKING_MODELS, BookingStatus, BookingType, booking_model
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


def assigned_to(tutor, model):
    """
    The bookings of ``model``'s type (a booking table) ``tutor`` is assigned
    now, whatever their status (a cancelled, rescheduled or completed booking
    keeps its tutor), and no others: one reassigned or unassigned is no longer
    theirs. Each comes with its report, if it has one (reports app).
    """
    return model.objects.filter(assigned_tutor=tutor).select_related('slot', 'lead', 'report')


def listed(tutor, now, booking_type=None, when=UPCOMING):
    """
    ``tutor``'s bookings of both types (or of ``booking_type``) narrowed by
    ``parse_filters``' filters, soonest slot first (``when=past``: most recent
    first), as a list.
    """
    models = [booking_model(booking_type)] if booking_type else BOOKING_MODELS
    bookings = [booking for model in models for booking in filtered(assigned_to(tutor, model), now, when=when)]
    return sorted(bookings, key=lambda booking: (booking.slot.starts_at, booking.created_at), reverse=when == PAST)


# Start for a caller who may not start bookings (accounts.submit_booking_report).
NO_START_PERMISSION = {'code': 'PERMISSION_DENIED', 'message': 'You cannot start bookings.'}
ALREADY_STARTED = {'code': 'BOOKING_STARTED', 'message': 'This booking has already started.'}


def start_refusal(booking, now, can_start):
    """
    Why the tutor cannot start ``booking`` now (booking_service.start_booking's
    own refusals, in its order), or None. ``can_start``: whether the caller
    holds accounts.submit_booking_report, which the Start route needs.
    """
    if not can_start:
        return NO_START_PERMISSION
    refusal = {
        BookingStatus.COMPLETED: CompletedNotStartable,
        BookingStatus.RESCHEDULED: RescheduledNotStartable,
        BookingStatus.CANCELLED: CancelledNotStartable,
    }.get(booking.status)
    if refusal is None and booking.started_at is not None:
        return ALREADY_STARTED
    if refusal is None and now < start_opens_at(booking.slot):
        refusal = StartTooEarly
    if refusal is None and now >= booking.slot.ends_at:
        refusal = StartWindowClosed
    return {'code': refusal.code, 'message': refusal.message} if refusal else None


def booking_row(booking, now, can_start=False):
    """
    One booking as its tutor is shown it, in the list and in full alike: with
    where it stands (bookings.lifecycle), when Start opens and whether it may
    be started now (``actions.start``, else ``start_refusal`` says why).
    """
    slot = slot_brief(booking.slot, now)
    refusal = start_refusal(booking, now, can_start)
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'status': booking.status,
        'slot': {field: slot[field] for field in SLOT_FIELDS},
        **{field: getattr(booking.lead, field) for field in STUDENT_FIELDS},
        # The Meet room the tutor teaches it in -- their own link, as the booking keeps it -- or null.
        'tutor_meet_link': booking.tutor_meet_link,
        'activity_state': activity_state(booking, now),
        # When the tutor started it (always the caller: a started booking keeps its tutor), or null.
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'start_opens_at': start_opens_at(booking.slot).isoformat(),
        'actions': {'start': refusal is None},
        'start_refusal': refusal,
        **report_summary(booking, now),
    }


def booking_detail(booking, now, can_start=False):
    """One booking in full: the row, and the time zone its slot is in."""
    return {**booking_row(booking, now, can_start), 'timezone': BOOKING_TIMEZONE_NAME}
