"""
Creating and cancelling bookings, closing slots and setting the schedule: the
one place booking rows are written.

create_booking runs in one transaction:

1. The slot row for the date and time is created by its first booking.
   get_or_create inserts in a savepoint; a concurrent request inserting the
   same slot waits on the unique index and, once the first commits, reads
   that row instead -- one row per slot.
2. The slot row is locked (SELECT ... FOR UPDATE), the project's pattern for
   check-then-write. Every booking, cancellation and closure of the slot
   queues behind this lock, so the count read under it is exact.
3. Under the lock the lead is matched; a booking the lead already holds in
   this slot is returned as it is (a repeated submission); a closed or full
   slot is refused; otherwise the lowest free seat (1-3) is taken.

The seats' partial unique index makes a fourth booked row for one slot
impossible even for code that skipped the lock; the lock is what keeps the
count right and concurrent requests off that index. A lock wait longer than
LOCK_TIMEOUT, or a deadlock, answers BookingBusy (CAPACITY_CHECK_UNAVAILABLE)
instead of holding the request.
"""
from dataclasses import dataclass
from datetime import date as date_type, time as time_type, timedelta

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from activity.utils import log_activity

from .attribution import resolve_referral
from .leads import match_lead, normalize_phone
from .models import SLOT_CAPACITY, Booking, BookingSlot, BookingStatus, Lead, ReferralStatus, SlotTime
from .scheduling import booking_window, slot_instants

LOCK_TIMEOUT = '3s'
# lock_not_available, deadlock_detected
BUSY_SQLSTATES = {'55P03', '40P01'}


class BookingError(Exception):
    code = 'BOOKING_FAILED'
    http_status = 400
    message = 'The booking could not be made.'


class DateOutOfWindow(BookingError):
    code = 'DATE_OUT_OF_WINDOW'
    message = 'That date is not available for booking. Please pick another.'


class SlotUnavailable(BookingError):
    code = 'SLOT_UNAVAILABLE'
    http_status = 409
    message = 'That time is not offered. Please choose another time.'


class SlotFull(BookingError):
    code = 'SLOT_FULL'
    http_status = 409
    message = 'This slot is fully booked. Please choose another time.'


class TooManyBookings(BookingError):
    code = 'TOO_MANY_BOOKINGS'
    http_status = 429
    message = 'Too many bookings for this phone number today. Please try again tomorrow.'


class BookingBusy(BookingError):
    code = 'CAPACITY_CHECK_UNAVAILABLE'
    http_status = 503
    message = 'Could not check this slot right now. Please try again.'


@dataclass(frozen=True)
class BookingRequest:
    booking_type: str
    date: date_type
    time: time_type
    parent_name: str
    phone_dial_code: str
    phone_number: str
    student_name: str
    school: str
    student_class: str
    syllabus: str
    country: str = ''
    display_time: str = ''
    # The raw ``ref`` value, whatever its type: bookings.attribution judges it.
    ref: object = None


def create_booking(request, now=None):
    """
    Book ``request``; returns (booking, created). ``created`` is False for a
    repeated submission, which gets the booking it already made. Raises a
    BookingError subclass, or leads.InvalidLeadDetails.
    """
    now = now or timezone.now()
    if request.date not in booking_window(request.booking_type, now):
        raise DateOutOfWindow()
    if not SlotTime.objects.filter(booking_type=request.booking_type, start_time=request.time, is_active=True).exists():
        raise SlotUnavailable()
    _dial, _national, phone_key = normalize_phone(request.phone_dial_code, request.phone_number)
    referral = resolve_referral(request.ref, request.booking_type)

    try:
        with transaction.atomic():
            _set_lock_timeout()
            slot = _locked_slot(request.booking_type, request.date, request.time)
            lead = match_lead(_lead_details(request))

            existing = slot.bookings.filter(lead=lead, status=BookingStatus.BOOKED).first()
            if existing is not None:
                return existing, False
            if slot.closed_at is not None:
                raise SlotFull()
            taken = set(slot.bookings.filter(status=BookingStatus.BOOKED).values_list('seat', flat=True))
            free = [seat for seat in range(1, min(slot.capacity, SLOT_CAPACITY) + 1) if seat not in taken]
            if not free:
                raise SlotFull()
            since = timezone.now() - timedelta(days=1)
            if Booking.objects.filter(lead__phone_key=phone_key, created_at__gte=since).count() >= settings.BOOKING_PHONE_DAILY_LIMIT:
                raise TooManyBookings()

            if referral.status == ReferralStatus.ATTRIBUTED:
                # First valid attribution wins: only a lead nobody owns yet
                # takes this BDE, whatever request commits second.
                Lead.objects.filter(pk=lead.pk, owner_bde__isnull=True).update(
                    owner_bde=referral.bde, owner_link=referral.link, owner_assigned_at=timezone.now(),
                )
            booking = Booking.objects.create(
                booking_type=request.booking_type,
                lead=lead,
                slot=slot,
                seat=free[0],
                referral_status=referral.status,
                referral_link=referral.link,
                attributed_bde=referral.bde,
                details=_submitted(request),
            )
            owner_id = Lead.objects.filter(pk=lead.pk).values_list('owner_bde_id', flat=True).get()
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise

    log_activity(
        action='booking.create',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(slot),
        # Ids and outcomes only: no names, phone numbers or tokens.
        context={
            'booking_type': booking.booking_type,
            'slot_starts_at': slot.starts_at.isoformat(),
            'referral_status': booking.referral_status,
            'attributed_bde_id': _str_or_none(booking.attributed_bde_id),
            'lead_id': str(booking.lead_id),
            'lead_owner_id': _str_or_none(owner_id),
            'via': 'public_booking',
        },
    )
    return booking, True


def cancel_booking(booking, actor=None, reason=''):
    """Cancel ``booking`` (kept as a record; its seat is freed). Returns (booking, changed)."""
    with transaction.atomic():
        _set_lock_timeout()
        # The slot lock first, the same order create_booking takes them in.
        BookingSlot.objects.select_for_update().filter(pk=booking.slot_id).first()
        booking = Booking.objects.select_for_update().select_related('slot').get(pk=booking.pk)
        if booking.status == BookingStatus.CANCELLED:
            return booking, False
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = actor
        booking.cancel_reason = reason or ''
        booking.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancel_reason', 'updated_at'])
    log_activity(
        action='booking.cancel',
        entity_type='booking',
        entity_id=booking.id,
        entity_label=slot_label(booking.slot),
        context={'booking_type': booking.booking_type, 'reason': booking.cancel_reason},
        actor=actor,
    )
    return booking, True


def close_slot(booking_type, local_date, local_time, actor=None, reason=''):
    """Close one slot: it shows as Fully Booked and takes no new booking. Returns (slot, changed)."""
    with transaction.atomic():
        _set_lock_timeout()
        slot = _locked_slot(booking_type, local_date, local_time)
        if slot.closed_at is not None:
            return slot, False
        slot.closed_at = timezone.now()
        slot.closed_by = actor
        slot.close_reason = reason or ''
        slot.save(update_fields=['closed_at', 'closed_by', 'close_reason'])
    _log_slot(slot, 'booking_slot.close', actor, slot.close_reason)
    return slot, True


def reopen_slot(booking_type, local_date, local_time, actor=None):
    """Reopen a closed slot. Returns (slot or None, changed)."""
    with transaction.atomic():
        _set_lock_timeout()
        slot = (
            BookingSlot.objects.select_for_update()
            .filter(booking_type=booking_type, local_date=local_date, local_time=local_time)
            .first()
        )
        if slot is None or slot.closed_at is None:
            return slot, False
        slot.closed_at = None
        slot.closed_by = None
        slot.close_reason = ''
        slot.save(update_fields=['closed_at', 'closed_by', 'close_reason'])
    _log_slot(slot, 'booking_slot.reopen', actor, '')
    return slot, True


def set_slots_closed(booking_type, local_date, times, closed, actor=None, reason=''):
    """
    Close (``closed=True``) or reopen several slots of one date together: all
    of them, or -- when a slot stays locked past LOCK_TIMEOUT -- none
    (BookingBusy). Bookings are never touched: a closed slot keeps the ones it
    holds, and a reopened one takes new ones only while seats remain. Slots
    are locked in time order, so two such changes cannot deadlock. Returns the
    times whose state changed.
    """
    changed = []
    try:
        with transaction.atomic():
            for start in sorted(set(times)):
                if closed:
                    _slot, did_change = close_slot(booking_type, local_date, start, actor=actor, reason=reason)
                else:
                    _slot, did_change = reopen_slot(booking_type, local_date, start, actor=actor)
                if did_change:
                    changed.append(start)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise
    return changed


def set_schedule(booking_type, times, actor=None, via='model'):
    """
    Make ``times`` exactly the active times of ``booking_type``: listed times
    are created or reactivated, the others deactivated (never deleted, so
    bookings made at a retired time keep their slot). Returns (added, removed).
    """
    wanted = set(times)
    with transaction.atomic():
        current = {entry.start_time: entry for entry in SlotTime.objects.select_for_update().filter(booking_type=booking_type)}
        added = sorted(t for t in wanted if t not in current or not current[t].is_active)
        removed = sorted(t for t, entry in current.items() if entry.is_active and t not in wanted)
        for start in added:
            SlotTime.objects.update_or_create(booking_type=booking_type, start_time=start, defaults={'is_active': True})
        SlotTime.objects.filter(booking_type=booking_type, start_time__in=removed).update(is_active=False, updated_at=timezone.now())
    if added or removed:
        log_activity(
            action='booking_schedule.update',
            entity_type='booking_schedule',
            entity_id=booking_type,
            entity_label=f'{booking_type.title()} schedule',
            changes={'times': {
                'old': sorted(_hhmm(t) for t, entry in current.items() if entry.is_active),
                'new': sorted(_hhmm(t) for t in wanted),
            }},
            context={'added': [_hhmm(t) for t in added], 'removed': [_hhmm(t) for t in removed], 'via': via},
            actor=actor,
        )
    return added, removed


def slot_label(slot):
    """'Demo · 28 Oct 2026, 19:30 IST' -- what the activity log names a slot by."""
    return f'{slot.get_booking_type_display()} · {slot.local_date:%d %b %Y}, {_hhmm(slot.local_time)} IST'


# ---------------------------------------------------------------- helpers

def _set_lock_timeout():
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")


def _locked_slot(booking_type, local_date, local_time):
    starts_at, ends_at = slot_instants(local_date, local_time)
    slot, _created = BookingSlot.objects.get_or_create(
        booking_type=booking_type,
        local_date=local_date,
        local_time=local_time,
        defaults={'starts_at': starts_at, 'ends_at': ends_at},
    )
    return BookingSlot.objects.select_for_update().get(pk=slot.pk)


def _lead_details(request):
    return {
        'parent_name': request.parent_name,
        'phone_dial_code': request.phone_dial_code,
        'phone_number': request.phone_number,
        'student_name': request.student_name,
        'school': request.school,
        'student_class': request.student_class,
        'syllabus': request.syllabus,
        'country': request.country,
    }


def _submitted(request):
    return {
        'parent_name': request.parent_name,
        'phone': f'{request.phone_dial_code} {request.phone_number}',
        'student_name': request.student_name,
        'school': request.school,
        'student_class': request.student_class,
        'syllabus': request.syllabus,
        'country': request.country,
        'display_time': request.display_time,
    }


def _log_slot(slot, action, actor, reason):
    log_activity(
        action=action,
        entity_type='booking_slot',
        entity_id=slot.id,
        entity_label=slot_label(slot),
        context={'booking_type': slot.booking_type, 'reason': reason} if reason else {'booking_type': slot.booking_type},
        actor=actor,
    )


def _hhmm(value):
    return value.strftime('%H:%M')


def _str_or_none(value):
    return str(value) if value else None
