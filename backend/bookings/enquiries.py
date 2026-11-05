"""
A BDE's enquiries: the leads (bookings.models.Lead) the BDE owns, as the BDE
workspace reads and adds them (/api/bde/dashboard/, /api/bde/enquiries/).

A BDE owns the leads their booking links brought in (the first valid
attribution wins, bookings.booking_service) and the ones they add by hand
here. Everything below starts from ``own_leads``: a BDE never sees another
BDE's leads, nor leads nobody owns.

An enquiry's status is not stored. It follows the lead's bookings, so it is
always what the booking pages last did:

    NEW        no booking yet
    BOOKED     a booking whose slot has not ended
    DONE       booked (or completed), and every booked slot has ended
    CANCELLED  no booking holds a seat, and one at least was cancelled

A rescheduled booking never decides the status: the booking it moved to
does. (A lead left with rescheduled bookings only -- which a reschedule never
leaves, since it books the replacement in the same step -- holds no booking,
so it reads NEW.)

A lead's bookings are its Diagnostic and its Demo bookings together, read from
both booking tables.
"""
import operator
from datetime import timedelta
from functools import reduce

from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, Count, Exists, OuterRef, Q, TextChoices, Value, When
from django.utils import timezone

from activity.utils import log_activity

from .leads import InvalidLeadDetails, normalize_phone, student_name_key
from .models import BOOKING_MODELS, HOLDS_SEAT, MANUAL_LEAD_SOURCES, BookingStatus, BookingType, Lead, LeadSource
from .scheduling import BOOKING_TIMEZONE_NAME

# Rows on the dashboard's upcoming bookings table and recent enquiries list.
UPCOMING_ROWS = 8
RECENT_ROWS = 5
# Phone searches need this many digits, so "1" does not match every number.
MIN_PHONE_SEARCH_DIGITS = 3


class EnquiryStatus(TextChoices):
    NEW = 'NEW', 'New'
    BOOKED = 'BOOKED', 'Booked'
    DONE = 'DONE', 'Booking done'
    CANCELLED = 'CANCELLED', 'Cancelled'


# A lead from the booking pages is shown by the link that brought it to its
# BDE; one added by hand by the source the BDE picked.
LINK_SOURCES = {BookingType.DEMO: 'DEMO_LINK', BookingType.DIAGNOSTIC: 'DIAGNOSTIC_LINK'}
SOURCE_LABELS = {'DEMO_LINK': 'Demo link', 'DIAGNOSTIC_LINK': 'Diagnostic link', **dict(LeadSource.choices)}
SOURCE_FILTERS = [*LINK_SOURCES.values(), *MANUAL_LEAD_SOURCES]


class EnquiryExists(Exception):
    """
    A lead for this phone number and student already exists. ``lead`` is it
    when the caller owns it, and None otherwise: another BDE's lead (or one
    nobody owns) is never named, let alone handed over.
    """

    def __init__(self, lead=None):
        super().__init__('An enquiry for this phone number and student already exists.')
        self.lead = lead


# ------------------------------------------------------------------ reading

def own_leads(bde):
    return Lead.objects.filter(owner_bde=bde)


def _has_booking(**filters):
    """Whether the lead has a booking of either type matching ``filters``, as an expression on leads."""
    return reduce(operator.or_, (Exists(model.objects.filter(lead=OuterRef('pk'), **filters)) for model in BOOKING_MODELS))


def with_status(leads, now):
    """``leads`` annotated with ``enquiry_status`` (EnquiryStatus) as of ``now``."""
    return leads.annotate(enquiry_status=Case(
        When(_has_booking(status=BookingStatus.BOOKED, slot__ends_at__gt=now), then=Value(EnquiryStatus.BOOKED)),
        When(_has_booking(status__in=HOLDS_SEAT), then=Value(EnquiryStatus.DONE)),
        When(_has_booking(status=BookingStatus.CANCELLED), then=Value(EnquiryStatus.CANCELLED)),
        default=Value(EnquiryStatus.NEW),
        output_field=CharField(),
    ))


def search(leads, text):
    """Leads whose parent or student name contains ``text``, or whose phone number contains its digits."""
    text = (text or '').strip()
    if not text:
        return leads
    match = Q(parent_name__icontains=text) | Q(student_name__icontains=text)
    # Stored numbers drop the domestic leading 0 (bookings.leads), so a search does too.
    digits = ''.join(char for char in text if char in '0123456789').lstrip('0')
    if len(digits) >= MIN_PHONE_SEARCH_DIGITS:
        match |= Q(phone_key__contains=digits)
    return leads.filter(match)


def filter_source(leads, key):
    """Leads whose source (as SOURCE_LABELS names it) is ``key``, one of SOURCE_FILTERS."""
    for booking_type, link_key in LINK_SOURCES.items():
        if key == link_key:
            return leads.filter(source=LeadSource.BOOKING_PAGE, owner_link__booking_type=booking_type)
    return leads.filter(source=key)


def listed(leads, now):
    """``leads`` ready for enquiry_rows: annotated, newest to their BDE first."""
    return with_status(leads, now).select_related('owner_link').order_by('-owner_assigned_at', '-created_at', 'id')


def next_bookings(lead_ids, now):
    """The earliest booking still to come, of either type, of each of ``lead_ids`` that has one."""
    upcoming = []
    for model in BOOKING_MODELS:
        upcoming.extend(
            model.objects.filter(lead_id__in=lead_ids, status=BookingStatus.BOOKED, slot__ends_at__gt=now)
            .select_related('slot')
        )
    first = {}
    for booking in sorted(upcoming, key=_soonest):
        first.setdefault(booking.lead_id, booking)
    return first


def _soonest(booking):
    return booking.slot.starts_at, booking.created_at


def source_of(lead):
    if lead.source == LeadSource.BOOKING_PAGE and lead.owner_link_id:
        return LINK_SOURCES[lead.owner_link.booking_type]
    return lead.source


def status_label(status, next_booking):
    if status == EnquiryStatus.BOOKED and next_booking is not None:
        return f'{next_booking.get_booking_type_display()} booked'
    return EnquiryStatus(status).label


def booking_brief(booking):
    """When and what a booking is. Slot dates and times are Indian time (bookings.scheduling)."""
    slot = booking.slot
    return {
        'id': str(booking.id),
        'booking_type': booking.booking_type,
        'date': slot.local_date.isoformat(),
        'time': slot.local_time.strftime('%H:%M'),
        'starts_at': slot.starts_at.isoformat(),
    }


def enquiry_rows(leads, now):
    """The list rows of ``leads`` (from ``listed``, already sliced to a page)."""
    leads = list(leads)
    upcoming = next_bookings([lead.pk for lead in leads], now)
    return [_row(lead, upcoming.get(lead.pk)) for lead in leads]


def _row(lead, next_booking):
    source = source_of(lead)
    return {
        'id': str(lead.id),
        'parent_name': lead.parent_name,
        'phone': f'{lead.phone_dial_code} {lead.phone_number}',
        'student_name': lead.student_name,
        'grade': lead.grade,
        'source': source,
        'source_label': SOURCE_LABELS.get(source, source),
        'status': lead.enquiry_status,
        'status_label': status_label(lead.enquiry_status, next_booking),
        'next_booking': booking_brief(next_booking) if next_booking else None,
        # When the lead became this BDE's: added by hand, or first booked through their link.
        'added_at': lead.owner_assigned_at.isoformat() if lead.owner_assigned_at else None,
    }


def enquiry_detail(lead, now, can_cancel=False, show_confirmation=False):
    """
    One enquiry in full (``lead`` from ``listed``), with every booking it has
    made -- each with its tutor and Meet link (_teaching) and what its owner
    BDE may do with it now (``actions``): cancel it while it is booked when
    ``can_cancel`` (accounts.cancel_booking, Q22), No-show only once its slot
    has started (D12). Each booking's parent confirmation (a ParentConfirmation
    code) is shown to whoever may see the lead's communication
    (``show_confirmation``, accounts.view_own_lead_communications), else null.
    """
    bookings = sorted(
        [
            *lead.diagnostic_bookings.select_related('slot', 'assigned_tutor'),
            *lead.demo_bookings.select_related('slot', 'assigned_tutor'),
        ],
        key=_soonest,
        reverse=True,
    )
    upcoming = [b for b in bookings if b.status == BookingStatus.BOOKED and b.slot.ends_at > now]
    next_booking = min(upcoming, key=lambda b: (b.slot.starts_at, b.created_at)) if upcoming else None
    return {
        **_row(lead, next_booking),
        'phone_dial_code': lead.phone_dial_code,
        'phone_number': lead.phone_number,
        'school_name': lead.school_name,
        'syllabus': lead.syllabus,
        'country': lead.country,
        'created_at': lead.created_at.isoformat(),
        'timezone': BOOKING_TIMEZONE_NAME,
        # What the parent booked and when; who cancelled a booking, and why,
        # stays with the administrators.
        'bookings': [
            {
                **booking_brief(booking),
                'status': booking.status,
                'ended': booking.slot.ends_at <= now,
                'booked_at': booking.created_at.isoformat(),
                'cancelled_at': booking.cancelled_at.isoformat() if booking.cancelled_at else None,
                **_teaching(booking),
                'parent_confirmation': booking.parent_confirmation if show_confirmation else None,
                'actions': _booking_actions(booking, now, can_cancel),
            }
            for booking in bookings
        ],
    }


def _teaching(booking):
    """
    Who teaches a booking that holds its seat (booked or completed), and the
    Meet room it is taught in -- the tutor's name only, and the booking's own
    copy of their link, or null when they have none -- to read, never to
    change. A cancelled or moved booking shows neither.
    """
    if booking.status not in HOLDS_SEAT or booking.assigned_tutor is None:
        return {'tutor': None, 'tutor_meet_link': None}
    tutor = booking.assigned_tutor
    return {'tutor': {'full_name': tutor.full_name or tutor.username}, 'tutor_meet_link': booking.tutor_meet_link}


def _booking_actions(booking, now, can_cancel):
    cancel = can_cancel and booking.status == BookingStatus.BOOKED
    return {'cancel': cancel, 'no_show': cancel and booking.slot.starts_at <= now}


def dashboard(bde, now=None):
    """The BDE dashboard: their enquiries and their enquiries' bookings, counted and listed."""
    now = now or timezone.now()
    leads = own_leads(bde)
    upcoming_now = Q(status=BookingStatus.BOOKED, slot__ends_at__gt=now)
    counts, upcoming = {}, []
    for model in BOOKING_MODELS:
        bookings = model.objects.filter(lead__owner_bde=bde)
        counts[model.BOOKING_TYPE] = bookings.aggregate(
            total=Count('pk', filter=Q(status__in=HOLDS_SEAT)),
            upcoming=Count('pk', filter=upcoming_now),
        )
        upcoming.extend(
            bookings.filter(upcoming_now).select_related('slot', 'lead').order_by('slot__starts_at', 'created_at')[:UPCOMING_ROWS]
        )
    upcoming.sort(key=_soonest)
    return {
        'timezone': BOOKING_TIMEZONE_NAME,
        'enquiries': {
            'total': leads.count(),
            'last_7_days': leads.filter(owner_assigned_at__gte=now - timedelta(days=7)).count(),
        },
        'bookings': {
            BookingType.DEMO: counts[BookingType.DEMO],
            BookingType.DIAGNOSTIC: counts[BookingType.DIAGNOSTIC],
        },
        'upcoming': {
            'total': counts[BookingType.DEMO]['upcoming'] + counts[BookingType.DIAGNOSTIC]['upcoming'],
            'rows': [
                {
                    **booking_brief(booking),
                    'enquiry': {
                        'id': str(booking.lead.id),
                        'parent_name': booking.lead.parent_name,
                        'student_name': booking.lead.student_name,
                        'grade': booking.lead.grade,
                    },
                }
                for booking in upcoming[:UPCOMING_ROWS]
            ],
        },
        'recent_enquiries': enquiry_rows(listed(leads, now)[:RECENT_ROWS], now),
    }


# ------------------------------------------------------------------ adding

def add_enquiry(bde, details, request=None):
    """
    A lead ``bde`` adds by hand, owned by them from the start. ``details`` is
    validated input (bookings.serializers.EnquiryCreateSerializer). Raises
    InvalidLeadDetails, or EnquiryExists when the phone number and student
    already make a lead -- whoever owns it. A parent who later books through
    the pages lands on this lead (bookings.leads.match_lead) and it stays this
    BDE's: ownership is never overwritten.
    """
    dial, national, phone_key = normalize_phone(details['phone_dial_code'], details['phone_number'])
    student_key = student_name_key(details['student_name'])
    if details['source'] not in MANUAL_LEAD_SOURCES:
        raise InvalidLeadDetails('source', 'Choose how this enquiry reached you.')

    existing = _existing(phone_key, student_key)
    if existing is not None:
        raise EnquiryExists(existing if existing.owner_bde_id == bde.pk else None)

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
        source=details['source'],
        owner_bde=bde,
        owner_assigned_at=timezone.now(),
    )
    try:
        # A savepoint of its own: a booking for the same child committing
        # first fails this insert on the unique index, and the request stays usable.
        with transaction.atomic():
            lead.save(force_insert=True)
    except IntegrityError:
        existing = _existing(phone_key, student_key)
        if existing is None:
            raise
        raise EnquiryExists(existing if existing.owner_bde_id == bde.pk else None)

    # Ids and choices only, as for bookings: no names or phone numbers in a log
    # every administrator reads.
    log_activity(
        action='enquiry.create',
        entity_type='lead',
        entity_id=lead.id,
        entity_label=f'{lead.grade} enquiry',
        context={'source': lead.source, 'grade': lead.grade, 'via': 'bde_workspace'},
        request=request,
        actor=bde,
    )
    return lead


def _existing(phone_key, student_key):
    return Lead.objects.filter(phone_key=phone_key, student_name_key=student_key).only('pk', 'owner_bde_id').first()
