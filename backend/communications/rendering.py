"""
Filling a template from a booking (PRD 3.11): the placeholders each booking
type's templates may use, where each value comes from, how dates and times
read, and what a message still needs before it can go (requirements).

Strict by design. A placeholder with no value never renders as blank text --
render raises MissingValues -- and one no template of the type may use is
refused (UnknownPlaceholders). Every value comes from the booking the message
belongs to: a Demo's message never shows a Diagnostic's details.

The date and time are the booking's start on the student's own clock
(bookings.student_timezones.student_time) -- Indian time, which the slots are
in, for a lead with no zone. The templates write the zone as text after the
time, "{{demo_time}} IST"; for a student in another zone the message names
theirs there instead ("5:00 PM UAE", zoned), and the template's own words
stay as they are.

The sender is the lead's BDE: their name and their mobile number (Team). A
lead with no BDE -- a booking made without a valid BDE link -- signs with the
central contact in COMMUNICATIONS_FALLBACK_SENDER_NAME / _PHONE; a BDE with
no mobile number never falls back to it, so their messages wait instead.
Nothing stands in for a missing contact: the central one is empty until it is
set, a number goes in as written (no country code added), and a message
without its sender waits, naming what it lacks -- the BDE's details
(BDE_CONTACT) or, for a lead with no BDE, the central contact (CENTRAL_CONTACT).
"""
import re

from django.conf import settings
from django.db.models import TextChoices
from django.utils import timezone

from bookings.models import CONDUCTED, BookingStatus, BookingType, ParentConfirmation
from bookings.student_timezones import INDIAN_LABEL, student_time

from .chain import EarlierAcknowledgement, earlier_acknowledgement
from .models import Step

PLACEHOLDER = re.compile(r'\{\{\s*([A-Za-z0-9_]+)\s*\}\}')
# A time placeholder and the zone the template writes after it: the slots'
# own, IST. A student in another zone reads theirs in its place (zoned).
ZONED_TIME = re.compile(r'(\{\{\s*(demo|diagnostic)_time\s*\}\}) IST\b')

_COMMON_VARIABLES = ('parent_name', 'student_name', 'tutor_name', 'meeting_link', 'bde_name', 'bde_phone')
# The placeholders each booking type's templates may use. Diagnostic tests are
# taught in the tutor's Meet room too, so both use meeting_link.
VARIABLES = {
    BookingType.DEMO: ('demo_date', 'demo_time', *_COMMON_VARIABLES),
    BookingType.DIAGNOSTIC: ('diagnostic_date', 'diagnostic_time', *_COMMON_VARIABLES),
}

_DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


class TemplateError(Exception):
    """A template and a booking's values cannot make a message."""


class UnknownPlaceholders(TemplateError):
    def __init__(self, names):
        super().__init__(f'Unknown placeholders: {", ".join(names)}')
        self.names = names


class MissingValues(TemplateError):
    def __init__(self, names):
        super().__init__(f'No value for: {", ".join(names)}')
        self.names = names


def placeholders(body):
    """The placeholder names in ``body``, in the order they first appear."""
    return list(dict.fromkeys(PLACEHOLDER.findall(body)))


def unknown_placeholders(booking_type, body):
    """The placeholders in ``body`` that ``booking_type``'s templates may not use."""
    return [name for name in placeholders(body) if name not in VARIABLES[booking_type]]


def check_placeholders(booking_type, body):
    """Raise UnknownPlaceholders unless every placeholder in ``body`` is one ``booking_type`` may use."""
    unknown = unknown_placeholders(booking_type, body)
    if unknown:
        raise UnknownPlaceholders(unknown)


def format_date(value):
    """A date as the messages show it: Tue, 4 Nov 2026."""
    return f'{_DAYS[value.weekday()]}, {value.day} {_MONTHS[value.month - 1]} {value.year}'


def format_time(value):
    """A time as the messages show it, on the 12-hour clock: 7:30 PM."""
    return f'{value.hour % 12 or 12}:{value.minute:02d} {"AM" if value.hour < 12 else "PM"}'


def sender_contact(lead):
    """(name, phone) the messages of ``lead``'s bookings sign with; None for what is missing."""
    if lead.owner_bde_id:
        return _text(lead.owner_bde.full_name), _text(lead.owner_bde.mobile_number)
    return _text(settings.COMMUNICATIONS_FALLBACK_SENDER_NAME), _text(settings.COMMUNICATIONS_FALLBACK_SENDER_PHONE)


def booking_values(booking):
    """
    Every placeholder value of ``booking``'s type, read from ``booking``; None
    where it has none. Its date and time are its start on the student's clock;
    a student outside India's zone also gets their zone's name, as
    demo_timezone / diagnostic_timezone -- no template's placeholder, but what
    zoned() writes in place of the templates' "IST".
    """
    prefix = 'demo' if booking.booking_type == BookingType.DEMO else 'diagnostic'
    lead = booking.lead
    tutor = booking.assigned_tutor
    bde_name, bde_phone = sender_contact(lead)
    starts, zone = student_time(booking.slot.starts_at, lead)
    values = {
        f'{prefix}_date': format_date(starts.date()),
        f'{prefix}_time': format_time(starts.time()),
        'parent_name': _text(lead.parent_name),
        'student_name': _text(lead.student_name),
        'tutor_name': _text(tutor.full_name) if tutor else None,
        'meeting_link': _text(booking.tutor_meet_link),
        'bde_name': bde_name,
        'bde_phone': bde_phone,
    }
    if zone != INDIAN_LABEL:
        values[f'{prefix}_timezone'] = zone
    return values


def zoned(body, values):
    """
    ``body`` with the "IST" its template writes after the time made the
    student's zone -- a placeholder for ``values``' demo_timezone /
    diagnostic_timezone -- where ``values`` has one. Without one (a student in
    India, a lead with no zone, a message written before zones were kept) the
    template's own "IST" stays, so those read exactly as they always have.
    """
    def zone(match):
        name = f'{match.group(2)}_timezone'
        return f'{match.group(1)} {{{{{name}}}}}' if values.get(name) else match.group(0)

    return ZONED_TIME.sub(zone, body)


def message_values(body, values):
    """The ``values`` a message written from ``body`` uses, by name -- the student's zone among them -- to keep with it."""
    return {name: values[name] for name in placeholders(zoned(body, values))}


def render(body, values):
    """
    ``body`` with every placeholder replaced from ``values``, its time in the
    student's zone (zoned). Raises MissingValues rather than leave one blank.
    """
    body = zoned(body, values)
    missing = [name for name in placeholders(body) if not values.get(name)]
    if missing:
        raise MissingValues(missing)
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], body)


class Requirement(TextChoices):
    """Something a message needs before it can go; while one is unmet it is Waiting."""
    TEMPLATE_VALID = 'TEMPLATE_VALID', 'Template'
    PARENT_CONFIRMED = 'PARENT_CONFIRMED', 'Parent confirmation'
    # Still to come, and not yet started by its tutor: the messages before the
    # class go only while both hold (booking_service.start_booking).
    BOOKING_ACTIVE = 'BOOKING_ACTIVE', 'Booking still upcoming and not started'
    BOOKING_COMPLETED = 'BOOKING_COMPLETED', 'Booking completed'
    TUTOR_ASSIGNED = 'TUTOR_ASSIGNED', 'Tutor assigned'
    MEET_LINK = 'MEET_LINK', 'Tutor Meet link'
    BDE_CONTACT = 'BDE_CONTACT', "BDE's name and mobile number"
    # What a lead with no BDE signs with instead (sender_contact): while it is
    # not set, its messages wait for it by that name, not a BDE's.
    CENTRAL_CONTACT = 'CENTRAL_CONTACT', 'Central contact (this lead has no BDE)'
    LEAD_DETAILS = 'LEAD_DETAILS', 'Parent and student details'
    # A rescheduled booking's acknowledgement goes only once the one of the
    # bookings it replaced is known not to have been accepted: never while it
    # is being sent, and never while its outcome is unknown (for someone to
    # check). One accepted closes this acknowledgement instead (planner).
    EARLIER_ACKNOWLEDGEMENT = 'EARLIER_ACKNOWLEDGEMENT', "Earlier booking's acknowledgement not accepted"


# What each step needs whatever its wording says: the confirmed message never
# goes without the parent's confirmation, a tutor, their Meet link and the
# BDE's name and phone; nothing before the class goes once the booking's
# scheduled time has come or its tutor has started it, whichever is first.
_STEP_GATES = {
    Step.ACKNOWLEDGEMENT: (Requirement.BOOKING_ACTIVE,),
    Step.CONFIRMATION_REQUEST: (Requirement.BOOKING_ACTIVE,),
    Step.PARENT_CONFIRMATION: (Requirement.PARENT_CONFIRMED, Requirement.BOOKING_ACTIVE),
    Step.AFTER_ACTIVITY: (Requirement.BOOKING_COMPLETED,),
}
_STEP_VALUES = {
    Step.PARENT_CONFIRMATION: ('tutor_name', 'meeting_link', 'bde_name', 'bde_phone'),
}
# Which requirement a missing value is; the date and time are always there.
_VALUE_REQUIREMENTS = {
    'tutor_name': Requirement.TUTOR_ASSIGNED,
    'meeting_link': Requirement.MEET_LINK,
    'bde_name': Requirement.BDE_CONTACT,
    'bde_phone': Requirement.BDE_CONTACT,
    'parent_name': Requirement.LEAD_DETAILS,
    'student_name': Requirement.LEAD_DETAILS,
}


def requirements(booking, step, body, now=None):
    """
    What a ``step`` message of ``booking`` written from ``body`` needs, in the
    order to show them: a list of (Requirement, met). It can go once all are met.
    """
    now = now or timezone.now()
    values = booking_values(booking)
    gates = {
        Requirement.PARENT_CONFIRMED: booking.parent_confirmation == ParentConfirmation.CONFIRMED,
        Requirement.BOOKING_ACTIVE: (
            booking.status == BookingStatus.BOOKED and booking.started_at is None and booking.slot.starts_at > now
        ),
        # A Demo sent for a Re-Demo was still taught: its after-activity message stands.
        Requirement.BOOKING_COMPLETED: booking.status in CONDUCTED,
    }
    result = [] if not unknown_placeholders(booking.booking_type, body) else [(Requirement.TEMPLATE_VALID, False)]
    result += [(gate, gates[gate]) for gate in _STEP_GATES[step]]
    if step == Step.ACKNOWLEDGEMENT and booking.rescheduled_from_id:
        earlier = earlier_acknowledgement(booking)
        result.append((Requirement.EARLIER_ACKNOWLEDGEMENT,
                       earlier in (EarlierAcknowledgement.NONE, EarlierAcknowledgement.NOT_ACCEPTED)))
    needed = {}
    for name in (*_STEP_VALUES.get(step, ()), *placeholders(body)):
        if name in _VALUE_REQUIREMENTS:
            needed.setdefault(_VALUE_REQUIREMENTS[name], []).append(name)
    # The sender's details are the lead's BDE's, or the central contact's for a lead with no BDE.
    sender = Requirement.BDE_CONTACT if booking.lead.owner_bde_id else Requirement.CENTRAL_CONTACT
    for requirement in (Requirement.TUTOR_ASSIGNED, Requirement.MEET_LINK, Requirement.BDE_CONTACT,
                        Requirement.LEAD_DETAILS):
        if requirement in needed:
            met = all(values.get(name) for name in needed[requirement])
            result.append((sender if requirement == Requirement.BDE_CONTACT else requirement, met))
    return result


def is_ready(checks):
    """Whether every requirement in ``checks`` (from requirements()) is met."""
    return all(met for _requirement, met in checks)


def _text(value):
    """``value`` stripped, or None when there is nothing in it."""
    value = (value or '').strip()
    return value or None
