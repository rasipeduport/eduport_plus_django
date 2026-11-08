"""
A BDE's enquiries -- their My Leads: the leads (bookings.models.Lead) the
BDE owns, as the BDE workspace reads and adds them (/api/bde/dashboard/,
/api/bde/enquiries/). The administrators' Leads page reads every lead with
the same rows and status (bookings.lead_admin).

A BDE owns the leads their booking links brought in (the first valid
attribution wins, bookings.booking_service), the ones they add by hand here,
and the ones an administrator gives them (bookings.ownership) -- for as long
as they own them: a lead given to another BDE leaves this BDE's list at once.
Everything below starts from ``own_leads``: a BDE never sees another BDE's
leads, nor leads nobody owns.

A lead's status is not stored: it follows its bookings, Diagnostic and Demo
together (bookings.lead_status).
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from activity.utils import log_activity

from . import redemo_chain, student_timezones
from .demo_invites import invitable
from .lead_intake import LeadExists, create_lead
from .lead_status import status_label, with_status
from .leads import InvalidLeadDetails
from .lifecycle import activity_state
from .models import (
    BOOKING_MODELS, HOLDS_SEAT, MANUAL_LEAD_SOURCES, PUBLIC_FORM_SOURCES, BookingStatus, BookingType, DemoBooking, Lead,
    LeadSource, RedemoCloseReason, ReDemoStatus,
)
from .scheduling import BOOKING_TIMEZONE_NAME, indian_today

# Rows on the dashboard's upcoming bookings table, today's agenda and recent enquiries list.
UPCOMING_ROWS = 8
AGENDA_ROWS = 12
RECENT_ROWS = 5
# Phone searches need this many digits, so "1" does not match every number.
MIN_PHONE_SEARCH_DIGITS = 3


# A lead from the booking pages is shown by the link that brought it to its
# owner, when one did, else as a booking page's; one from a lead form by the
# form; one added by hand by the source picked.
LINK_SOURCES = {BookingType.DEMO: 'DEMO_LINK', BookingType.DIAGNOSTIC: 'DIAGNOSTIC_LINK'}
SOURCE_LABELS = {'DEMO_LINK': 'Demo link', 'DIAGNOSTIC_LINK': 'Diagnostic link', **dict(LeadSource.choices)}
SOURCE_FILTERS = [*LINK_SOURCES.values(), LeadSource.BOOKING_PAGE, *PUBLIC_FORM_SOURCES, *MANUAL_LEAD_SOURCES]


class EnquiryExists(Exception):
    """
    A lead for this phone number and student already exists. ``lead`` is it
    when the caller owns it, and None otherwise: another BDE's lead (or one
    nobody owns) is never named, let alone handed over -- only an
    administrator gives a lead to a BDE.
    """

    def __init__(self, lead=None):
        super().__init__('An enquiry for this phone number and student already exists.')
        self.lead = lead


# ------------------------------------------------------------------ reading

def own_leads(bde):
    return Lead.objects.filter(owner_bde=bde)


def search(leads, text):
    """Leads whose parent's or student's name or parent's email contains ``text``, or whose phone number contains its digits."""
    text = (text or '').strip()
    if not text:
        return leads
    match = Q(parent_name__icontains=text) | Q(student_name__icontains=text) | Q(parent_email__icontains=text)
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
    if key == LeadSource.BOOKING_PAGE:
        # As source_of shows it: a booking page's lead no link of its owner's brought.
        return leads.filter(source=LeadSource.BOOKING_PAGE, owner_link__isnull=True)
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


def enquiry_rows(leads, now, extra=None):
    """The list rows of ``leads`` (from ``listed``, already sliced to a page), each with ``extra(lead)`` beside it."""
    leads = list(leads)
    upcoming = next_bookings([lead.pk for lead in leads], now)
    return [{**_row(lead, upcoming.get(lead.pk)), **(extra(lead) if extra else {})} for lead in leads]


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
        'status': lead.lead_status,
        'status_label': status_label(lead.lead_status),
        'next_booking': booking_brief(next_booking) if next_booking else None,
        # The IANA zone the student books from, for their own time beside the
        # Indian one (bookings.student_timezones); null when not known.
        'student_timezone': student_timezones.of(lead),
        # When the lead became this BDE's: added by hand, or first booked through their link.
        'added_at': lead.owner_assigned_at.isoformat() if lead.owner_assigned_at else None,
    }


def enquiry_detail(lead, now, can_cancel=False, show_confirmation=False, can_invite=False):
    """
    One enquiry in full (``lead`` from ``listed``), with every booking it has
    made -- each with its tutor and Meet link (_teaching) and what its owner
    BDE may do with it now (``actions``): cancel it while it is booked when
    ``can_cancel`` (accounts.cancel_booking, Q22), No-show only once its
    scheduled time has passed (D12), send the parent a Demo invitation from a
    Diagnostic whose report is in when ``can_invite``
    (accounts.create_demo_booking, bookings.demo_invites), and with the same
    permission ask for a completed Demo to be taught again (bookings.redemos)
    -- and where it stands as a class, started
    by its tutor and when, or not (``activity_state``, ``started_at``), to read
    only. Each booking's parent confirmation (a ParentConfirmation
    code) is shown to whoever may see the lead's communication
    (``show_confirmation``, accounts.view_own_lead_communications), else null.
    """
    bookings = sorted(
        [
            *lead.diagnostic_bookings.select_related('slot', 'assigned_tutor', 'report'),
            *lead.demo_bookings.select_related('slot', 'assigned_tutor'),
        ],
        key=_soonest,
        reverse=True,
    )
    upcoming = [b for b in bookings if b.status == BookingStatus.BOOKED and b.slot.ends_at > now]
    next_booking = min(upcoming, key=lambda b: (b.slot.starts_at, b.created_at)) if upcoming else None
    zone = student_timezones.of(lead)
    return {
        **_row(lead, next_booking),
        'phone_dial_code': lead.phone_dial_code,
        'phone_number': lead.phone_number,
        'parent_email': lead.parent_email,
        'school_name': lead.school_name,
        'syllabus': lead.syllabus,
        'country': lead.country,
        'created_at': lead.created_at.isoformat(),
        'timezone': BOOKING_TIMEZONE_NAME,
        # What the parent booked and when; who cancelled a booking, and why,
        # stays with the administrators.
        'bookings': [
            _booking_entry(booking, now, can_cancel, show_confirmation, can_invite, zone) for booking in bookings
        ],
    }


def _booking_entry(booking, now, can_cancel, show_confirmation, can_invite, zone):
    redemo = redemo_chain.request_of(booking)
    redemo_state = redemo_chain.state(redemo, now) if redemo is not None else None
    return {
        **booking_brief(booking),
        # The lead's zone: each booking is read in it at its own slot, a moved one at its new slot.
        'student_timezone': zone,
        'status': booking.status,
        'ended': booking.slot.ends_at <= now,
        'activity_state': activity_state(booking, now),
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'booked_at': booking.created_at.isoformat(),
        'cancelled_at': booking.cancelled_at.isoformat() if booking.cancelled_at else None,
        **_teaching(booking),
        'parent_confirmation': booking.parent_confirmation if show_confirmation else None,
        # The Re-Demo it was sent for, or the one it was scheduled for (bookings.redemos).
        'redemo': _redemo(redemo_state, now, can_invite),
        'redemo_from': _redemo_from(booking),
        # A Re-Demo still to come: the Demo messages' wording filled in, for the BDE to send by hand.
        'parent_messages': _parent_messages(booking, now),
        'actions': _booking_actions(booking, now, can_cancel, can_invite, redemo_state is not None),
    }


def _redemo(redemo_state, now, can_manage=False):
    """
    A Demo's Re-Demo request as its owner BDE sees it: where it stands, why
    and by whom it was asked for, and the Demo an administrator scheduled for
    it, with its tutor and status -- what the BDE tells the parent -- and,
    closed, when and why. Never the administrators' remarks. ``actions``: the
    BDE may close it while nothing is booked for it, and reopen it, with
    accounts.create_demo_booking (``can_manage``), the permission they ask
    for one with.
    """
    if redemo_state is None:
        return None
    redemo, booking = redemo_state.redemo, redemo_state.booking
    tutor = booking.assigned_tutor if booking is not None else None
    return {
        'id': str(redemo.id),
        'status': redemo_state.status,
        'status_label': ReDemoStatus(redemo_state.status).label,
        'requested_at': redemo.requested_at.isoformat(),
        'requested_by': {'full_name': redemo.requested_by.full_name or redemo.requested_by.email},
        'reason': redemo.reason,
        'tutor': {'full_name': tutor.full_name or tutor.email} if tutor is not None else None,
        'booking': {**booking_brief(booking), 'status': booking.status} if booking is not None else None,
        'closed': {
            'at': redemo.closed_at.isoformat(),
            'reason': {'code': redemo.close_reason_code, 'label': RedemoCloseReason(redemo.close_reason_code).label},
        } if redemo.closed_at else None,
        'actions': {
            'close': can_manage and redemo_state.status == ReDemoStatus.AWAITING_SCHEDULING,
            'reopen': can_manage and redemo_state.status == ReDemoStatus.CLOSED,
        },
    }


def _parent_messages(booking, now):
    """A Re-Demo's parent messages to send by hand (communications.redemo_messages), or None."""
    if not getattr(booking, 'redemo_for_id', None):
        return None
    # The communications app reads bookings; imported here so neither loads the other first.
    from communications.redemo_messages import redemo_messages

    return redemo_messages(booking, now)


def _redemo_from(booking):
    """The Re-Demo request ``booking`` was scheduled for, named by its id and the Demo it teaches again, or None."""
    redemo = getattr(booking, 'redemo_for', None)
    if redemo is None:
        return None
    return {'id': str(redemo.id), 'demo_booking_id': str(redemo.demo_booking_id)}


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


def _booking_actions(booking, now, can_cancel, can_invite=False, has_redemo=False):
    cancel = can_cancel and booking.status == BookingStatus.BOOKED
    return {
        'cancel': cancel,
        'no_show': cancel and booking.slot.starts_at <= now,
        'demo_invite': can_invite and invitable(booking, now),
        # A completed Demo of their own lead, to be taught again: an administrator then schedules it.
        # Once per Demo: one whose request was closed is reopened instead (``redemo.actions``).
        'request_redemo': (
            can_invite and isinstance(booking, DemoBooking) and booking.status == BookingStatus.COMPLETED
            and not has_redemo
        ),
    }


def dashboard(bde, now=None):
    """
    The BDE dashboard: their enquiries and their enquiries' bookings, counted
    and listed. Today's agenda is every booking of theirs on today's Indian
    date (the date the slots are booked in, whatever the server's clock zone)
    that holds its seat -- still to come, under way, completed or missed;
    cancelled and moved ones are not on it (a moved booking's replacement is,
    on its own date) -- soonest first.
    """
    now = now or timezone.now()
    today = indian_today(now)
    leads = own_leads(bde)
    upcoming_now = Q(status=BookingStatus.BOOKED, slot__ends_at__gt=now)
    on_today = Q(status__in=HOLDS_SEAT, slot__local_date=today)
    counts, upcoming, agenda = {}, [], []
    for model in BOOKING_MODELS:
        bookings = model.objects.filter(lead__owner_bde=bde)
        counts[model.BOOKING_TYPE] = bookings.aggregate(
            total=Count('pk', filter=Q(status__in=HOLDS_SEAT)),
            upcoming=Count('pk', filter=upcoming_now),
            today=Count('pk', filter=on_today),
        )
        upcoming.extend(
            bookings.filter(upcoming_now).select_related('slot', 'lead').order_by('slot__starts_at', 'created_at')[:UPCOMING_ROWS]
        )
        agenda.extend(
            bookings.filter(on_today).select_related('slot', 'lead', 'assigned_tutor')
            .order_by('slot__starts_at', 'created_at')[:AGENDA_ROWS]
        )
    upcoming.sort(key=_soonest)
    agenda.sort(key=_soonest)
    demo, diagnostic = counts[BookingType.DEMO], counts[BookingType.DIAGNOSTIC]
    return {
        'timezone': BOOKING_TIMEZONE_NAME,
        'enquiries': {
            'total': leads.count(),
            'last_7_days': leads.filter(owner_assigned_at__gte=now - timedelta(days=7)).count(),
        },
        'bookings': {
            BookingType.DEMO: {'total': demo['total'], 'upcoming': demo['upcoming']},
            BookingType.DIAGNOSTIC: {'total': diagnostic['total'], 'upcoming': diagnostic['upcoming']},
        },
        'upcoming': {
            'total': demo['upcoming'] + diagnostic['upcoming'],
            'rows': [
                {
                    **booking_brief(booking),
                    'student_timezone': student_timezones.of(booking.lead),
                    'enquiry': enquiry_brief(booking.lead),
                }
                for booking in upcoming[:UPCOMING_ROWS]
            ],
        },
        'agenda': {
            'date': today.isoformat(),
            'total': demo['today'] + diagnostic['today'],
            'rows': [_agenda_row(booking, now) for booking in agenda[:AGENDA_ROWS]],
        },
        'recent_enquiries': enquiry_rows(listed(leads, now)[:RECENT_ROWS], now),
    }


def enquiry_brief(lead):
    """Whose booking it is, as the dashboard's rows name it."""
    return {'id': str(lead.id), 'parent_name': lead.parent_name, 'student_name': lead.student_name, 'grade': lead.grade}


def booking_list_row(booking, now, show_confirmation=False):
    """
    One of the BDE's bookings as their Demo and Diagnostic Bookings lists show
    it, written out field by field so nothing reaches the BDE by being added
    elsewhere: when and what it is, where it stands as a class (read-only),
    when it was booked, who teaches it -- the tutor's name only; the Meet room is
    the enquiry page's to show -- the parent's answer to the confirmation request
    for whoever may see the lead's communication (``show_confirmation``),
    whether it is a scheduled Re-Demo, and whose booking it is, with the
    zone the student books from. Never who cancelled or moved it, or why:
    that stays with the administrators.
    """
    return {
        **booking_brief(booking),
        'student_timezone': student_timezones.of(booking.lead),
        'status': booking.status,
        'activity_state': activity_state(booking, now),
        'started_at': booking.started_at.isoformat() if booking.started_at else None,
        'booked_at': booking.created_at.isoformat(),
        'tutor': _teaching(booking)['tutor'],
        'parent_confirmation': booking.parent_confirmation if show_confirmation else None,
        'redemo': getattr(booking, 'redemo_for_id', None) is not None,
        'enquiry': enquiry_brief(booking.lead),
    }


def _agenda_row(booking, now):
    """
    One of today's bookings on the agenda: when and what it is, where it
    stands as a class (read-only, as the enquiry shows it), whose it is and who
    teaches it -- the tutor's name only, never their Meet link, which the
    enquiry's page shows.
    """
    return {
        **booking_brief(booking),
        'student_timezone': student_timezones.of(booking.lead),
        'status': booking.status,
        'activity_state': activity_state(booking, now),
        'tutor': _teaching(booking)['tutor'],
        'enquiry': enquiry_brief(booking.lead),
    }


# ------------------------------------------------------------------ adding

def add_enquiry(bde, details, request=None):
    """
    A lead ``bde`` adds by hand, owned by them from the start. ``details`` is
    validated input (bookings.serializers.EnquiryCreateSerializer). Raises
    InvalidLeadDetails, or EnquiryExists when the phone number and student
    already make a lead -- whoever owns it. A parent who later books through
    the pages lands on this lead (bookings.leads.match_lead) and it stays this
    BDE's: a booking never changes the owner, only an administrator does.
    """
    if details['source'] not in MANUAL_LEAD_SOURCES:
        raise InvalidLeadDetails('source', 'Choose how this enquiry reached you.')
    try:
        lead = create_lead(details, source=details['source'], created_by=bde, owner=bde)
    except LeadExists as exc:
        raise EnquiryExists(exc.lead if exc.lead.owner_bde_id == bde.pk else None)

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
