"""
Leads coming in other than by a booking (a booking page's lead is matched or
made as it books, bookings.leads.match_lead): from the marketing site's lead
forms -- the main website's and the landing page's -- and by hand, as a BDE's
enquiry (bookings.enquiries) or an administrator's lead (bookings.lead_admin).

Whichever way it arrives, a child has one lead per phone number and student
name (bookings.leads), held by the unique index:

- A lead form's submission for a child who already has a lead makes nothing
  and changes nothing: it answers that lead. A retried or repeated submission
  therefore never makes a second lead, and nothing the public sends overwrites
  what is on file.
- A lead added by hand for a child who already has one is refused
  (LeadExists), and the caller decides what to do.

A lead form's lead belongs to nobody until an administrator assigns it a BDE
(bookings.ownership); there is no other way it gets an owner.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from activity.utils import log_activity

from .leads import normalize_phone, student_name_key
from .models import PUBLIC_FORM_SOURCES, Lead

# The utm_* parameters a lead form forwards from its page's URL, all optional.
UTM_FIELDS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')


class LeadExists(Exception):
    """A lead for this phone number and student already exists: ``lead`` (its id and owner only)."""

    def __init__(self, lead):
        super().__init__('A lead for this phone number and student already exists.')
        self.lead = lead


class TooManyLeads(Exception):
    """This phone number already made settings.LEAD_PHONE_DAILY_LIMIT leads through the lead forms today."""


def existing_lead(phone_key, student_key):
    return Lead.objects.filter(phone_key=phone_key, student_name_key=student_key).only('pk', 'owner_bde_id').first()


def create_lead(details, *, source, created_by=None, owner=None, source_details=None):
    """
    A new lead from validated ``details`` -- parent_name, phone_dial_code,
    phone_number, student_name and grade; school_name, syllabus, country,
    parent_email and student_timezone when known. ``owner`` (a BDE adding
    their own enquiry) owns it from the start. Raises
    bookings.leads.InvalidLeadDetails, or LeadExists when the phone number and
    student already make a lead.
    """
    dial, national, phone_key = normalize_phone(details['phone_dial_code'], details['phone_number'])
    student_key = student_name_key(details['student_name'])
    existing = existing_lead(phone_key, student_key)
    if existing is not None:
        raise LeadExists(existing)

    lead = Lead(
        parent_name=details['parent_name'],
        phone_dial_code=dial,
        phone_number=national,
        phone_key=phone_key,
        student_name=details['student_name'],
        student_name_key=student_key,
        school_name=details.get('school_name') or '',
        grade=details['grade'],
        syllabus=details.get('syllabus') or '',
        country=details.get('country') or '',
        parent_email=details.get('parent_email') or '',
        student_timezone=details.get('student_timezone') or '',
        source=source,
        source_details=source_details or {},
        created_by=created_by,
        owner_bde=owner,
        owner_assigned_at=timezone.now() if owner is not None else None,
    )
    try:
        # A savepoint of its own: a lead for the same child committing first
        # (a booking, another submission) fails this insert on the unique
        # index, and the request stays usable.
        with transaction.atomic():
            lead.save(force_insert=True)
    except IntegrityError:
        existing = existing_lead(phone_key, student_key)
        if existing is None:
            raise
        raise LeadExists(existing)
    return lead


def record_form_lead(details, *, source, utm=None, now=None):
    """
    A lead form's submission (``source``: WEBSITE or LANDING_PAGE), as
    (lead, created). The child's existing lead, untouched, when there is one
    -- even past the daily limit, so a retry is always answered alike;
    otherwise a new lead nobody owns, with the form's utm_* parameters.
    Raises InvalidLeadDetails, or TooManyLeads when this phone number already
    made settings.LEAD_PHONE_DAILY_LIMIT leads through the forms in the last day.
    """
    if source not in PUBLIC_FORM_SOURCES:
        raise ValueError(f'Not a lead form source: {source}')
    now = now or timezone.now()
    _dial, _national, phone_key = normalize_phone(details['phone_dial_code'], details['phone_number'])
    existing = existing_lead(phone_key, student_name_key(details['student_name']))
    if existing is not None:
        return existing, False
    made_today = Lead.objects.filter(
        phone_key=phone_key, source__in=PUBLIC_FORM_SOURCES, created_at__gte=now - timedelta(days=1),
    ).count()
    if made_today >= settings.LEAD_PHONE_DAILY_LIMIT:
        raise TooManyLeads()

    source_details = {field: value for field, value in (utm or {}).items() if field in UTM_FIELDS and value}
    try:
        lead = create_lead(details, source=source, source_details=source_details)
    except LeadExists as exc:
        return exc.lead, False

    # Ids and choices only: no names, phone numbers or campaign values in a
    # log every administrator reads.
    log_activity(
        action='lead.create',
        entity_type='lead',
        entity_id=lead.id,
        entity_label=f'{lead.grade} lead',
        context={'source': lead.source, 'grade': lead.grade, 'via': 'lead_form'},
    )
    return lead, True
