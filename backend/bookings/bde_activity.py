"""
A BDE's activity (GET /api/bde/activity/): what has happened to their own
leads' bookings, newest first, read from each booking's history
(bookings.BookingEvent, written in the same transaction as each change).

Each event is written out for the BDE field by field: what happened and when,
to which booking and whose, and whether it was the BDE's own doing. Never who
else did it, and never why a booking was cancelled, moved or not confirmed --
who cancelled a booking, and why, stays with the administrators, as the
enquiry's own page keeps it (bookings.enquiries). The parent's answers show
only to whoever may see the lead's communication, and report edits only to
whoever may see its reports. Like the enquiry, the history follows the lead:
a lead given to another BDE takes its bookings' history with it.
"""
from django.db.models import Q

from .enquiries import booking_brief, enquiry_brief
from .models import BookingEvent, BookingEventKind, BookingSlot

# How a booking came to be, as its creation recorded it (booking_service): codes only.
ORIGINS = {'public_booking', 'demo_invite', 'redemo', 'reschedule'}
COMMUNICATION_KINDS = (BookingEventKind.PARENT_CONFIRMED, BookingEventKind.PARENT_NOT_CONFIRMED)
REPORT_KINDS = (BookingEventKind.REPORT_EDITED,)


def own_events(bde, *, show_communication, show_reports):
    """The history of the bookings of the leads ``bde`` owns now, less what the BDE may not see."""
    events = BookingEvent.objects.filter(Q(demo_booking__lead__owner_bde=bde) | Q(diagnostic_booking__lead__owner_bde=bde))
    hidden = (*(() if show_communication else COMMUNICATION_KINDS), *(() if show_reports else REPORT_KINDS))
    return events.exclude(kind__in=hidden) if hidden else events


def for_enquiry(events, lead_id):
    """``events`` of one lead's bookings."""
    return events.filter(Q(demo_booking__lead_id=lead_id) | Q(diagnostic_booking__lead_id=lead_id))


def newest_first(events):
    return events.select_related(
        'demo_booking__slot', 'demo_booking__lead', 'diagnostic_booking__slot', 'diagnostic_booking__lead',
    ).order_by('-created_at', '-id')


def moved_to(events):
    """The slots the reschedules in ``events`` moved their bookings to, by id."""
    ids = {event.data.get('new_slot_id') for event in events if event.kind == BookingEventKind.RESCHEDULED}
    return {str(slot.pk): slot for slot in BookingSlot.objects.filter(pk__in=[i for i in ids if i])}


def _detail(event, slots):
    """What the event may tell the BDE beyond its kind: codes and dates, never a reason or a person."""
    data = event.data or {}
    if event.kind == BookingEventKind.CREATED and data.get('via') in ORIGINS:
        return {'origin': data['via']}
    if event.kind == BookingEventKind.RESCHEDULED:
        slot = slots.get(str(data.get('new_slot_id')))
        return {'to': {'date': slot.local_date.isoformat(), 'time': slot.local_time.strftime('%H:%M')}} if slot else {}
    if event.kind == BookingEventKind.REPORT_EDITED and data.get('version'):
        return {'version': data['version']}
    return {}


def activity_row(event, bde, slots):
    """One event as the BDE's activity shows it."""
    booking = event.demo_booking or event.diagnostic_booking
    return {
        'id': str(event.id),
        'kind': event.kind,
        'kind_label': event.get_kind_display(),
        'at': event.created_at.isoformat(),
        'by_you': event.actor_id is not None and event.actor_id == bde.pk,
        'detail': _detail(event, slots),
        'booking': booking_brief(booking),
        'enquiry': enquiry_brief(booking.lead),
    }
