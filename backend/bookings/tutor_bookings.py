"""
Bookings as the tutor teaching them sees them (/api/tutor/bookings/): the Demo
and Diagnostic bookings assigned to the tutor now, each with its slot in
Indian time, the child it is for -- name, class, syllabus, school, country
and the time zone they book from -- and the Google Meet room it is taught
in, and nothing more. The
tutor's one write here is Start (booking_service.start_booking), offered by
each booking's ``actions.start``; the tutor is assigned, changed and
unassigned only by the Admin / Coordinator (bookings.booking_service).

What a tutor is shown is written out field by field below, never taken from a
model or from bookings.coordination's rows, so nothing reaches a tutor by
being added elsewhere: not the parent's name or phone as the lead or the
booking holds them, not a booking's ``details`` (the submission, which holds
both), not the BDE or the referral, not who assigned the tutor or when, not
the cancellation's reason or author, nor the lead's own id.

The one exception is a Re-Demo's own words. A Re-Demo (bookings.redemos) is
shown as one, to the tutor teaching it: ``redemo`` says which Re-Demo of the
child's it is, the reason given when it was requested (the BDE's or an
administrator's own words, often what the parent said -- shown as written,
whatever they mention; the request dialog tells whoever writes it that the
tutor will read it), the administrators' remarks for the tutor, and the
Demo it follows -- when it was, who taught it and its report as last saved,
to read only -- but not who asked or scheduled it. Every other booking's
``redemo`` is null. A Demo sent for a Re-Demo reads Completed to the tutor
who taught it: the request is not theirs.

One booking in full (``booking_detail``, the tutor's workspace) carries its
enquiry too (``enquiry_brief``): the original source, the status and when it
came in, and the child's bookings in order, each with when it was booked,
started and cancelled and who taught it -- what the enquiry's journey shows --
under the same rules: nothing of the parent, the lead's id, the BDE or a
Re-Demo request.

The views guard these with accounts.view_assigned_bookings, which only the
TUTOR role may hold. Which bookings are read is the caller's alone: always
``assigned_to(request.user)``, whatever a request says.
"""
from django.db.models import Q

from . import coordination, student_timezones
from .booking_service import (
    CancelledNotStartable,
    CompletedNotStartable,
    RescheduledNotStartable,
    StartTooEarly,
    StartWindowClosed,
)
from .coordination import PAST, UPCOMING, filtered, report_summary, slot_brief
from .enquiries import SOURCE_LABELS, booking_brief, source_of
from .lead_status import LeadStatus, status_label, with_status
from .lifecycle import activity_state, start_opens_at
from .models import BOOKING_MODELS, CONDUCTED, BookingStatus, BookingType, DemoBooking, Lead, booking_model
from .redemo_chain import redemo_number
from .scheduling import BOOKING_TIMEZONE_NAME

ALL = 'all'
# The classes the tutor has taught: the report is in, or due (``taught``).
COMPLETED = 'completed'
# The statuses a tutor filters by, as the rows show them: a Demo sent for a
# Re-Demo reads Completed, so Completed finds it too and Re-Demo required is
# not one of them.
STATUS_FILTERS = {
    BookingStatus.BOOKED: (BookingStatus.BOOKED,),
    BookingStatus.COMPLETED: CONDUCTED,
    BookingStatus.CANCELLED: (BookingStatus.CANCELLED,),
    BookingStatus.RESCHEDULED: (BookingStatus.RESCHEDULED,),
}
# The administrators' list filters a tutor's list reads as well, parsed by
# their own rules (coordination.parse_filters). ``q`` is the tutor's own: the
# student's name alone (``listed``).
SHARED_FILTERS = ('from', 'to', 'report', 'q')

# The child, from the booking's lead -- never the parent.
STUDENT_FIELDS = ('student_name', 'grade', 'syllabus', 'school_name', 'country')
# The slot, in Indian time (coordination.slot_brief), without its own id.
SLOT_FIELDS = ('date', 'time', 'starts_at', 'ends_at', 'started', 'ended')


def parse_filters(params):
    """
    The list filters from a query string, as (filters, invalid): ``invalid``
    names every parameter whose value is not one the list knows. No other
    parameter is read -- a ``tutor`` one, say, never is.

        type      DEMO | DIAGNOSTIC
        when      upcoming (the default: the slot has not ended) | past | all
                  | completed (the classes taught: the report is in, or due)
        status    BOOKED | COMPLETED | CANCELLED | RESCHEDULED (as the rows show it)
        from, to  YYYY-MM-DD (the slot's Indian date, inclusive)
        report    submitted | missing | due (as the administrators' list reads it)
        q         the student's name -- never the parent's name or phone, which
                  a tutor is not shown
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
        if when in (UPCOMING, PAST, COMPLETED):
            filters['when'] = when
        elif when == ALL:
            filters['when'] = None
        else:
            invalid.append('when')
    status = (params.get('status') or '').strip().upper()
    if status:
        if status in STATUS_FILTERS:
            filters['status'] = status
        else:
            invalid.append('status')
    shared, refused = coordination.parse_filters({name: params.get(name) for name in SHARED_FILTERS})
    filters.update(shared)
    invalid.extend(refused)
    return filters, invalid


def assigned_to(tutor, model):
    """
    The bookings of ``model``'s type (a booking table) ``tutor`` is assigned
    now, whatever their status (a cancelled, rescheduled or completed booking
    keeps its tutor), and no others: one reassigned or unassigned is no longer
    theirs. Each comes with its report, if it has one (reports app).
    """
    bookings = model.objects.filter(assigned_tutor=tutor).select_related('slot', 'lead', 'report')
    if model is DemoBooking:
        bookings = bookings.select_related(
            'redemo_for__demo_booking__slot', 'redemo_for__demo_booking__assigned_tutor',
            'redemo_for__demo_booking__redemo_for', 'redemo_for__demo_booking__report',
        )
    return bookings


def taught(now):
    """
    The classes the tutor has taught as of ``now``: completed with their
    report, or started by the tutor with the slot over and the report still
    due (coordination.report_summary's report_due).
    """
    return Q(status__in=CONDUCTED) | Q(status=BookingStatus.BOOKED, started_at__isnull=False, slot__ends_at__lte=now)


def listed(tutor, now, booking_type=None, when=UPCOMING, status=None, q=None, **filters):
    """
    ``tutor``'s bookings of both types (or of ``booking_type``) narrowed by
    ``parse_filters``' filters, soonest slot first (``when=past`` or
    ``completed``: most recent first), as a list. ``q`` finds the student by
    name only, never the parent: the administrators' search reads the parent's
    name and phone too (coordination.filtered), so it is not used.
    """
    models = [booking_model(booking_type)] if booking_type else BOOKING_MODELS
    bookings = []
    for model in models:
        rows = assigned_to(tutor, model)
        if status:
            rows = rows.filter(status__in=STATUS_FILTERS[status])
        if when == COMPLETED:
            rows = rows.filter(taught(now))
        if q:
            rows = rows.filter(lead__student_name__icontains=q)
        bookings.extend(filtered(rows, now, when=None if when == COMPLETED else when, **filters))
    return sorted(
        bookings, key=lambda booking: (booking.slot.starts_at, booking.created_at), reverse=when in (PAST, COMPLETED),
    )


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
        BookingStatus.REDEMO_REQUIRED: CompletedNotStartable,
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
        # A Demo sent for a Re-Demo reads Completed: the request is not the tutor's.
        'status': BookingStatus.COMPLETED if booking.status in CONDUCTED else booking.status,
        'slot': {field: slot[field] for field in SLOT_FIELDS},
        **{field: getattr(booking.lead, field) for field in STUDENT_FIELDS},
        # The zone the child books from, for their own time of the slot
        # (bookings.student_timezones); null when not known.
        'student_timezone': student_timezones.of(booking.lead),
        # The Meet room the tutor teaches it in -- their own link, as the booking keeps it -- or null.
        'tutor_meet_link': booking.tutor_meet_link,
        'activity_state': activity_state(booking, now),
        # When the tutor started it (always the caller: a started booking keeps its tutor), or null.
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'start_opens_at': start_opens_at(booking.slot).isoformat(),
        'actions': {'start': refusal is None},
        'start_refusal': refusal,
        **report_summary(booking, now),
        'redemo': redemo_brief(booking, now),
    }


def redemo_brief(booking, now):
    """
    What the tutor of a Re-Demo is told about it, or None for any other
    booking: which Re-Demo of the child's it is, the request's reason, the
    administrators' remarks and the Demo it follows -- its slot, its tutor's
    name and its report as last saved (the fields its tutor wrote and its
    version, reports.payloads.report_body), to read only.
    """
    # The reports app reads bookings; imported here so neither loads the other first.
    from reports.payloads import report_body

    redemo = getattr(booking, 'redemo_for', None)
    if redemo is None:
        return None
    original = redemo.demo_booking
    slot = slot_brief(original.slot, now)
    tutor = original.assigned_tutor
    report = getattr(original, 'report', None)
    return {
        'number': redemo_number(redemo),
        'reason': redemo.reason,
        'admin_remarks': redemo.admin_remarks,
        'original': {
            'slot': {field: slot[field] for field in SLOT_FIELDS},
            'tutor': {'full_name': tutor.full_name or tutor.email} if tutor is not None else None,
            'report': report_body(report) if report is not None else None,
        },
    }


def booking_detail(booking, now, can_start=False):
    """One booking in full: the row, the time zone its slot is in, and the enquiry it belongs to (``enquiry_brief``)."""
    return {
        **booking_row(booking, now, can_start),
        'timezone': BOOKING_TIMEZONE_NAME,
        'enquiry': enquiry_brief(booking.lead, now),
    }


def enquiry_brief(lead, now):
    """
    The enquiry a booking belongs to, as its tutor's workspace shows it: how it
    first reached Eduport Plus (its original source, bookings.enquiries), where
    it stands now (bookings.lead_status) and when it came in, the booking still
    to come, and the child's Demo and Diagnostic bookings in order -- the
    enquiry's journey. Each booking says only its type, slot, status and when
    it was booked, started and cancelled, and for a class that was taught who
    taught it. Not the parent, the lead's id, the BDE or the link's owner, a
    cancellation's reason or author, another booking's Meet room or report,
    nor a Re-Demo request: as in the rows, a Demo sent for a Re-Demo reads
    Completed, so a Re-Demo reads as the Demo it is.
    """
    lead = with_status(Lead.objects.filter(pk=lead.pk), now).select_related('owner_link').get()
    bookings = sorted(
        [
            *lead.diagnostic_bookings.select_related('slot', 'assigned_tutor'),
            *lead.demo_bookings.select_related('slot', 'assigned_tutor'),
        ],
        key=lambda booking: (booking.slot.starts_at, booking.created_at),
    )
    upcoming = [booking for booking in bookings if booking.status == BookingStatus.BOOKED and booking.slot.ends_at > now]
    status = LeadStatus.DEMO_COMPLETED if lead.lead_status == LeadStatus.DEMO_REDEMO_REQUIRED else lead.lead_status
    source = source_of(lead)
    return {
        'source_label': SOURCE_LABELS.get(source, source),
        'status': status,
        'status_label': status_label(status),
        'created_at': lead.created_at.isoformat(),
        'next_booking': booking_brief(upcoming[0]) if upcoming else None,
        'bookings': [_journey_entry(booking) for booking in bookings],
    }


def _journey_entry(booking):
    """One of the enquiry's bookings on its journey (``enquiry_brief``)."""
    conducted = booking.status in CONDUCTED
    tutor = booking.assigned_tutor if conducted else None
    return {
        **booking_brief(booking),
        'status': BookingStatus.COMPLETED if conducted else booking.status,
        'booked_at': booking.created_at.isoformat(),
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'cancelled_at': booking.cancelled_at.isoformat() if booking.cancelled_at else None,
        'tutor': {'full_name': tutor.full_name or tutor.email} if tutor is not None else None,
    }
