"""
A student's time zone (Lead.student_timezone): the IANA zone their booking
page showed the slot times in -- the browser's own -- kept on their lead so
staff see each booking at the student's own time ("Student Time") beside its
Indian time. Display only: every slot is offered, booked and moved in Indian
time (bookings.scheduling), and nothing here changes when a booking is.

- A booking from the Demo or Diagnostic page, or a Demo invitation, carries
  the zone its page used. One the runtime's zone database does not know is
  dropped, never refused: the booking stands without it (``clean``). It is
  written onto a new lead, and onto an existing lead that has none; a later
  booking never replaces a lead's zone (``fill``). The booking keeps the zone
  its own page used in its ``details`` (booking_service), as history.
- A BDE (their own enquiries) or an administrator may set or correct it
  (``correct``); the activity log keeps the old zone and the new, and the
  lead's unsent parent messages are written again with it at once.
- Staff APIs give it as ``student_timezone`` (``of``): the zone, or null when
  it is not known -- a name of its own, apart from the responses'
  ``timezone``, which is the Indian zone the slots are in.
- Parent messages show a booking at the student's own time (``student_time``):
  its start on their zone's clock, named as the Hub's Student Time names it
  ("5:00 PM UAE") -- India's time and "IST" for a lead with no zone.
"""
from zoneinfo import ZoneInfo

from django.db import OperationalError, transaction
from django.utils import timezone

from activity.utils import log_activity
from core.timezones import is_valid_timezone

from .models import Lead
from .scheduling import BOOKING_TIMEZONE_NAME

# Lead.student_timezone's length; the longest IANA identifier is 32.
MAX_LENGTH = 64

# What a parent message calls a student's zone after a time: the names the
# Hub's Student Time reads (frontend/hub/src/lib/timezone.js, TIMEZONE_OPTIONS:
# its `place`, else its `short` label), except India's, which the messages
# have always called IST.
INDIAN_LABEL = 'IST'
ZONE_LABELS = {
    'Asia/Kolkata': INDIAN_LABEL,
    'Asia/Dubai': 'UAE',
    'Asia/Qatar': 'Qatar',
    'Asia/Riyadh': 'KSA',
    'Asia/Kuwait': 'Kuwait',
    'Asia/Bahrain': 'Bahrain',
    'Asia/Muscat': 'Oman',
    'Asia/Singapore': 'Singapore',
    'Europe/London': 'UK',
    'America/New_York': 'New York',
    'America/Chicago': 'Chicago',
    'America/Denver': 'Denver',
    'America/Los_Angeles': 'Los Angeles',
    'Australia/Sydney': 'Sydney',
    'Australia/Perth': 'Perth',
    'Asia/Colombo': 'Sri Lanka',
    'Asia/Kathmandu': 'Nepal',
    'Asia/Dhaka': 'Bangladesh',
}
# The older names (tzdata's backward links) a browser may give for a listed
# zone -- Chrome reports India as Asia/Calcutta -- as the Hub reads them (LISTED_ALIASES).
ZONE_ALIASES = {
    'Asia/Calcutta': 'Asia/Kolkata',
    'Asia/Katmandu': 'Asia/Kathmandu',
    'Asia/Dacca': 'Asia/Dhaka',
    'Singapore': 'Asia/Singapore',
    'GB': 'Europe/London',
    'GB-Eire': 'Europe/London',
    'Europe/Belfast': 'Europe/London',
    'US/Eastern': 'America/New_York',
    'US/Central': 'America/Chicago',
    'US/Mountain': 'America/Denver',
    'US/Pacific': 'America/Los_Angeles',
    'Australia/ACT': 'Australia/Sydney',
    'Australia/Canberra': 'Australia/Sydney',
    'Australia/NSW': 'Australia/Sydney',
    'Australia/West': 'Australia/Perth',
}


class InvalidStudentTimezone(ValueError):
    code = 'INVALID_TIMEZONE'
    message = 'Choose a valid time zone.'


def clean(value):
    """``value`` as a lead keeps it: an IANA zone the runtime knows, else ''."""
    if not isinstance(value, str):
        return ''
    zone = value.strip()
    return zone if len(zone) <= MAX_LENGTH and is_valid_timezone(zone) else ''


def of(lead):
    """``lead``'s zone for a response: the IANA identifier, or None when it is not known."""
    zone = lead.student_timezone
    return zone if zone and is_valid_timezone(zone) else None


def student_time(instant, lead):
    """
    ``instant`` -- a booking's start -- on the clock of ``lead``'s zone, as
    parent messages show it: (that zone's date and time, the zone's label).
    India's, labelled IST, for a lead with no zone or one the runtime does not
    know. Daylight saving included, as the zone database has it then.
    """
    zone = of(lead) or BOOKING_TIMEZONE_NAME
    return instant.astimezone(ZoneInfo(zone)), zone_label(zone, instant)


def zone_label(zone, at):
    """
    What a message calls ``zone`` -- an IANA zone the runtime knows -- after a
    time at the instant ``at``, as the Hub's studentTimezoneLabel reads it: its
    listed name under any of its names ("UAE", "New York", "IST" for India);
    any other zone's IANA city ("Europe/Berlin" -> "Berlin"); for one that
    names no place (Etc/GMT+5, UTC), its offset then ("GMT-5").
    """
    listed = ZONE_LABELS.get(ZONE_ALIASES.get(zone, zone))
    if listed:
        return listed
    if zone.lower().startswith('etc/') or '/' not in zone:
        return _gmt_offset(at.astimezone(ZoneInfo(zone)).utcoffset())
    return zone.rsplit('/', 1)[1].replace('_', ' ')


def _gmt_offset(offset):
    """A UTC offset as the Hub's Intl names it: GMT, GMT+4, GMT-5, GMT+5:30."""
    minutes = int(offset.total_seconds()) // 60
    if not minutes:
        return 'GMT'
    hours, rest = divmod(abs(minutes), 60)
    return f'GMT{"+" if minutes > 0 else "-"}{hours}' + (f':{rest:02d}' if rest else '')


def fill(lead_id, zone):
    """
    Give the lead ``lead_id`` the zone ``zone`` (``clean``'s) when it has none,
    and never replace one it has: a single conditional update, so a booking
    racing a staff correction -- or another booking -- never overwrites it.
    True when it was written.
    """
    if not zone:
        return False
    return bool(
        Lead.objects.filter(pk=lead_id, student_timezone='').update(student_timezone=zone, updated_at=timezone.now())
    )


def correct(lead_id, value, *, actor, via, owner_bde=None, request=None, now=None):
    """
    Set lead ``lead_id``'s zone to ``value`` -- an IANA zone the runtime knows,
    or None / '' to clear it -- for a BDE (``owner_bde``: only their own lead,
    checked again under the lead's lock) or an administrator correcting it;
    holding the permission is the caller's check. Returns (lead, changed):
    ``changed`` is False when it already was that zone, and nothing is
    written. A change is logged with the old zone and the new, and the
    lead's unsent parent messages are written again with it as of ``now``,
    in the same transaction (communications.planner.lead_timezone_changed). Raises
    InvalidStudentTimezone, Lead.DoesNotExist (also for another BDE's lead),
    or booking_service.BookingBusy when the lead or one of those messages
    stays locked past the booking lock timeout.
    """
    # booking_service imports this module for the bookings' zones, and the
    # planner does through communications.rendering for the messages' times.
    from communications import planner

    from .booking_service import BUSY_SQLSTATES, BookingBusy, _set_lock_timeout

    zone = value.strip() if isinstance(value, str) else value
    if zone in (None, ''):
        zone = ''
    elif not isinstance(zone, str) or clean(zone) != zone:
        raise InvalidStudentTimezone()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            # Under the lead's lock: the owner is the one now, and the zone
            # logged as old is the one replaced.
            lead = Lead.objects.select_for_update(no_key=True).get(pk=lead_id)
            if owner_bde is not None and lead.owner_bde_id != owner_bde.pk:
                raise Lead.DoesNotExist()
            old = lead.student_timezone
            if old == zone:
                return lead, False
            lead.student_timezone = zone
            lead.save(update_fields=['student_timezone', 'updated_at'])
            # Its messages still to go show the bookings at the student's time:
            # what the Hub shows as ready is what the parent would read.
            planner.lead_timezone_changed(lead, now or timezone.now())
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    # The zones and the way only: no names or phone numbers in a log every administrator reads.
    log_activity(
        action='lead.update_student_timezone',
        entity_type='lead',
        entity_id=lead.id,
        entity_label=f'{lead.grade} lead',
        changes={'student_timezone': {'old': old or None, 'new': zone or None}},
        context={'via': via},
        request=request,
        actor=actor,
    )
    return lead, True
