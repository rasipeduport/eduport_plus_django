"""
The parent messages for a Re-Demo, as its BDE sends them by hand
(bookings.redemos): a Re-Demo has no communication plan, so nothing here is
written, queued or sent -- the Hub opens WhatsApp with the text filled in and
the BDE sends it, or not.

The text is the Demo templates' own wording, as the planned messages of an
ordinary Demo use it: the confirmation request (asking the parent to confirm
the time) and the confirmed message (the tutor, the time and the Meet link),
each in its latest version (MessageTemplate.current_version), filled from the
Re-Demo's booking exactly as a planned message is (rendering.booking_values):
its date and time on the student's own clock, named by their zone ("5:00 PM
UAE"), India's time and IST for a student with no zone. A value the booking
lacks -- no tutor, no Meet link, no BDE contact -- leaves that message out,
naming what it needs, rather than sending a blank.
"""
from bookings.models import BookingStatus, BookingType

from .formatting import whatsapp_message
from .models import MessageTemplate, Step
from .rendering import MissingValues, booking_values

# The two messages a BDE sends for a Re-Demo, in the order they go.
MESSAGES = (
    ('confirmation_request', Step.CONFIRMATION_REQUEST),
    ('confirmed', Step.PARENT_CONFIRMATION),
)


def redemo_messages(booking, now):
    """
    The messages ``booking`` -- a Re-Demo, read with its slot, lead, lead's BDE
    and tutor -- may be sent by hand now, by name: each ``{"text", "missing"}``
    (``text`` null with the values it lacks). None for any other booking, and
    for one no longer to come: cancelled, moved, completed, started or past
    its start.
    """
    if not getattr(booking, 'redemo_for_id', None):
        return None
    if booking.status != BookingStatus.BOOKED or booking.started_at is not None or booking.slot.starts_at <= now:
        return None
    values = booking_values(booking)
    templates = {
        template.step: template
        for template in MessageTemplate.objects.filter(booking_type=BookingType.DEMO, step__in=[s for _, s in MESSAGES])
    }
    found = {}
    for name, step in MESSAGES:
        template = templates.get(step)
        version = template.current_version() if template is not None else None
        if version is None:
            found[name] = {'text': None, 'missing': ['template']}
            continue
        try:
            found[name] = {'text': whatsapp_message(version.body, values), 'missing': []}
        except MissingValues as exc:
            found[name] = {'text': None, 'missing': list(exc.names)}
    return found
