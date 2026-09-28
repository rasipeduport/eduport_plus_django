"""
Time-zone helpers shared by the students and sessions apps.

Sessions are stored as absolute UTC instants. Staff schedule using the
*student's* local wall-clock time, so turning that into an instant needs an
explicit IANA zone -- never the browser's zone, which is what previously
decided it. Mirrors ``lib/timezone.ts`` in the Hub.
"""
import re
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Applied when a student has no timezone set. Matches historical behaviour
# (sessions were always entered as IST) and the Hub's DEFAULT_TIMEZONE.
DEFAULT_TIMEZONE = 'Asia/Kolkata'

DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


class TimezoneConversionError(ValueError):
    """A wall-clock time could not be resolved to an instant. The message is
    written for the person scheduling, not for a log."""


def is_valid_timezone(zone):
    """True when the runtime's zone database recognises this IANA identifier."""
    if not zone or not isinstance(zone, str):
        return False
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def zoned_wall_time_to_utc(date_str, time_str, zone):
    """
    Convert a wall-clock ``YYYY-MM-DD`` + ``HH:MM`` read in ``zone`` to the UTC
    instant it names.

    DST leaves two awkward cases, both handled the way the Hub does:

    - **Spring forward** removes an hour, so times inside the gap never occur.
      Rejected, because silently shifting a lesson by an hour is worse than
      making the mentor pick a valid time.
    - **Fall back** repeats an hour, so times inside it occur twice. The earlier
      instant is chosen (PEP 495 ``fold=0``) -- the convention every major date
      library uses.
    """
    if not isinstance(date_str, str) or not DATE_PATTERN.match(date_str):
        raise TimezoneConversionError(f'date must be YYYY-MM-DD, received "{date_str}"')
    if not isinstance(time_str, str) or not TIME_PATTERN.match(time_str):
        raise TimezoneConversionError(f'time must be HH:mm (24-hour), received "{time_str}"')
    if not is_valid_timezone(zone):
        raise TimezoneConversionError(f'unknown time zone "{zone}"')

    try:
        naive = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
    except ValueError:
        raise TimezoneConversionError(f'"{date_str}" is not a real date') from None

    tz = ZoneInfo(zone)
    instant = naive.replace(tzinfo=tz, fold=0).astimezone(dt_timezone.utc)

    # A time inside a spring-forward gap does not read back as itself.
    if instant.astimezone(tz).replace(tzinfo=None) != naive:
        raise TimezoneConversionError(
            f'{date_str} {time_str} does not exist in {zone} — clocks move forward past it'
        )
    return instant
