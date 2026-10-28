"""
The booking calendar: which dates and times are bookable, and how full each
slot is. A port of the public booking pages' rules (eduport-plus
lib/google-sheets.ts and lib/constants.ts), computed on every read:

* The window is tomorrow through six days later, in Indian time -- today is
  never bookable. Nothing has to "roll" it forward; it moves with the clock.
* Every active SlotTime of the booking type is offered on every date.
* A slot's status follows its booked count against capacity 3: 0 Available,
  1 Filling Fast, 2 Only a Few Left, 3 Fully Booked. A closed slot is
  Fully Booked.
* A date is Fully Booked only when every slot is; otherwise it takes the most
  urgent bookable status of its slots.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone

from core.timezones import zoned_wall_time_to_utc

from .models import SLOT_CAPACITY, SLOT_MINUTES, BookingSlot, BookingStatus, BookingType, SlotTime

# Every slot time and every date in the calendar is Indian time. Fixed here
# rather than read from settings.TIME_ZONE, which governs everything else.
BOOKING_TIMEZONE_NAME = 'Asia/Kolkata'
BOOKING_TIMEZONE = ZoneInfo(BOOKING_TIMEZONE_NAME)

# Bookable days per booking type (kept separate, as the pages keep them).
WINDOW_DAYS = {
    BookingType.DEMO: 7,
    BookingType.DIAGNOSTIC: 7,
}

AVAILABLE = 'Available'
FILLING_FAST = 'Filling Fast'
ONLY_A_FEW_LEFT = 'Only a Few Left'
FULLY_BOOKED = 'Fully Booked'


def indian_today(now=None):
    return (now or timezone.now()).astimezone(BOOKING_TIMEZONE).date()


def booking_window(booking_type, now=None):
    """The bookable dates, ascending: tomorrow through WINDOW_DAYS days on."""
    first = indian_today(now) + timedelta(days=1)
    return [first + timedelta(days=offset) for offset in range(WINDOW_DAYS[booking_type])]


def status_for_count(count, capacity=SLOT_CAPACITY):
    capacity = min(capacity, SLOT_CAPACITY)
    if count >= capacity:
        return FULLY_BOOKED
    remaining = capacity - count
    if remaining == 1:
        return ONLY_A_FEW_LEFT
    if remaining == 2:
        return FILLING_FAST
    return AVAILABLE


def day_status(statuses):
    valid = [status for status in statuses if status]
    if valid and all(status == FULLY_BOOKED for status in valid):
        return FULLY_BOOKED
    for status in (ONLY_A_FEW_LEFT, FILLING_FAST, AVAILABLE):
        if status in valid:
            return status
    # No slot at all (an empty schedule) is not bookable either.
    return FULLY_BOOKED


def active_times(booking_type):
    return list(
        SlotTime.objects.filter(booking_type=booking_type, is_active=True)
        .order_by('start_time')
        .values_list('start_time', flat=True)
    )


def slot_instants(local_date, local_time):
    """The UTC start of an Indian date and time, and its end an hour later."""
    starts_at = zoned_wall_time_to_utc(local_date.isoformat(), local_time.strftime('%H:%M'), BOOKING_TIMEZONE_NAME)
    return starts_at, starts_at + timedelta(minutes=SLOT_MINUTES)


def calendar(booking_type, now=None):
    """
    The bookable window as the booking API returns it:
    ``[{"date": "2026-10-28", "status": ..., "slots": [{"time": "19:30", "status": ...}]}]``.
    """
    window = booking_window(booking_type, now)
    times = active_times(booking_type)
    slots = {
        (slot.local_date, slot.local_time): slot
        for slot in BookingSlot.objects.filter(booking_type=booking_type, local_date__in=window).annotate(
            booked=Count('bookings', filter=Q(bookings__status=BookingStatus.BOOKED))
        )
    }
    dates = []
    for day in window:
        entries = []
        for start in times:
            slot = slots.get((day, start))
            if slot is None:
                status = status_for_count(0)
            elif slot.closed_at is not None:
                status = FULLY_BOOKED
            else:
                status = status_for_count(slot.booked, slot.capacity)
            entries.append({'time': start.strftime('%H:%M'), 'status': status})
        dates.append({'date': day.isoformat(), 'status': day_status([e['status'] for e in entries]), 'slots': entries})
    return dates
