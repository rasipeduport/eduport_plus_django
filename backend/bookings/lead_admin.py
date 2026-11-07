"""
The administrators' Leads page (/api/leads/): every lead, whatever brought
it in -- a booking page, a lead form on the marketing site, a BDE's enquiry
or an administrator's own entry -- in the rows and with the status a BDE's
My Leads shows (bookings.enquiries, bookings.lead_status), plus who owns it.
Administrators add leads by hand here, and give leads to BDEs through
bookings.ownership.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Q

from accounts.models import RoleChoices, User
from activity.utils import log_activity
from core.timezones import DATE_PATTERN

from . import enquiries
from .lead_intake import create_lead
from .lead_status import with_status
from .leads import InvalidLeadDetails
from .models import MANUAL_LEAD_SOURCES
from .scheduling import BOOKING_TIMEZONE
from .services import owns_booking_links

# The owner filter's value for the leads nobody owns.
UNASSIGNED = 'unassigned'


def _person(user):
    return {'id': str(user.pk), 'full_name': user.full_name or user.email} if user else None


def listed(leads, now):
    """``leads`` ready for lead_rows: annotated, the latest received first."""
    return with_status(leads, now).select_related('owner_link', 'owner_bde', 'created_by').order_by('-created_at', 'id')


def filter_owner(leads, owner):
    """The leads of the account ``owner`` (an id), or those nobody owns (UNASSIGNED)."""
    if owner == UNASSIGNED:
        return leads.filter(owner_bde__isnull=True)
    return leads.filter(owner_bde_id=owner)


def received_dates(params):
    """
    ``from`` and ``to`` from a query string -- the Indian dates (YYYY-MM-DD) a
    lead came in on, inclusive -- as ((date_from, date_to), invalid): either is
    None when unset, and ``invalid`` names each parameter that is not a date,
    and ``to`` when it comes before ``from``. Nothing is guessed for either.
    """
    dates, invalid = {}, []
    for name in ('from', 'to'):
        value = (params.get(name) or '').strip()
        if not value:
            dates[name] = None
            continue
        try:
            if not DATE_PATTERN.match(value):
                raise ValueError(value)
            dates[name] = date.fromisoformat(value)
        except ValueError:
            dates[name] = None
            invalid.append(name)
    if dates['from'] and dates['to'] and dates['from'] > dates['to']:
        invalid.append('to')
    return (dates['from'], dates['to']), invalid


def received_between(leads, date_from=None, date_to=None):
    """
    ``leads`` that came in on the Indian dates ``date_from`` to ``date_to``,
    inclusive -- the day in India, whatever the server's clock zone -- either
    end left open when None.
    """
    if date_from:
        leads = leads.filter(created_at__gte=datetime.combine(date_from, time.min, tzinfo=BOOKING_TIMEZONE))
    if date_to:
        leads = leads.filter(created_at__lt=datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=BOOKING_TIMEZONE))
    return leads


def _ownership(lead):
    return {'owner': _person(lead.owner_bde), 'created_at': lead.created_at.isoformat()}


def lead_rows(leads, now):
    """The list rows of ``leads`` (from ``listed``, already sliced to a page): a BDE's row, its owner and when it came in."""
    return enquiries.enquiry_rows(leads, now, extra=_ownership)


def lead_detail(lead, now, show_confirmation=False):
    """
    One lead in full (``lead`` from ``listed``): what its owner BDE sees of
    it, with its bookings -- to read here; they are managed on the Bookings
    page -- and who owns it, who added it by hand, and the campaign a lead
    form's lead came from.
    """
    return {
        **enquiries.enquiry_detail(lead, now, show_confirmation=show_confirmation),
        'owner': _person(lead.owner_bde),
        'added_by': _person(lead.created_by),
        'source_details': lead.source_details,
    }


def bde_options():
    """
    The accounts an administrator may filter leads by, and of them those a
    lead may be given to now (``assignable``: active BDEs): every BDE account,
    and anyone else who still owns a lead -- a BDE since deactivated or moved
    to another role, whose leads are to be reassigned.
    """
    accounts = (
        User.objects.filter(Q(role=RoleChoices.BDE) | Q(owned_leads__isnull=False))
        .distinct()
        .order_by('full_name', 'email', 'id')
    )
    return [{**_person(account), 'assignable': owns_booking_links(account)} for account in accounts]


def add_lead(admin, details, request=None):
    """
    A lead an administrator adds by hand (``details``: validated
    bookings.serializers.LeadCreateSerializer input), owned by nobody until
    they assign it. Raises InvalidLeadDetails, or lead_intake.LeadExists when
    the phone number and student already make a lead.
    """
    if details['source'] not in MANUAL_LEAD_SOURCES:
        raise InvalidLeadDetails('source', 'Choose how this lead reached Eduport Plus.')
    lead = create_lead(details, source=details['source'], created_by=admin)
    # Ids and choices only, as for every lead: no names or phone numbers in the log.
    log_activity(
        action='lead.create',
        entity_type='lead',
        entity_id=lead.id,
        entity_label=f'{lead.grade} lead',
        context={'source': lead.source, 'grade': lead.grade, 'via': 'admin_leads'},
        request=request,
        actor=admin,
    )
    return lead
