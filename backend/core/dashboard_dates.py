"""
The dashboards' dates. The Admissions, Sales and Academics Dashboards each
count a span of Indian dates (IST, whatever the server's clock zone), read
from the query string the same way, filtered in the database the same way and
drawn in the same trend buckets.

A span is one of:

- ``?from=&to=`` -- a range of Indian dates (YYYY-MM-DD), both ends included,
  the first on or before the last;
- ``?range=all`` -- All Time: every record up to today. There is no first
  date at all: ``date_from`` is None and every filter here leaves the lower
  bound out of the query, rather than standing in an early date for it;
- neither -- the last DEFAULT_DAYS days, today included.

The Hub sends its presets (Today, 7 Days, This Month) as ``from`` and ``to``.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Q

from bookings.scheduling import BOOKING_TIMEZONE, indian_today
from core.timezones import DATE_PATTERN

ALL_TIME = 'all'
# The span a dashboard opened without dates shows: the last seven Indian days, today included.
DEFAULT_DAYS = 7
# The dates a span may name. No record predates the first, and a typo such as
# year 0202 is refused rather than drawn as eighteen centuries of empty buckets.
EARLIEST_DATE = date(2000, 1, 1)
LATEST_DATE = date(2099, 12, 31)
INVALID_MESSAGE = 'Check the dates: YYYY-MM-DD, the first on or before the last, or range=all.'

# A span of up to a month is drawn day by day, up to six months week by week,
# up to two years month by month, longer year by year.
DAILY_DAYS = 31
WEEKLY_DAYS = 186
MONTHLY_DAYS = 731


def _date(params, name, invalid):
    value = (params.get(name) or '').strip()
    if not value:
        return None
    try:
        if not DATE_PATTERN.match(value):
            raise ValueError(value)
        day = date.fromisoformat(value)
    except ValueError:
        invalid.append(name)
        return None
    if not EARLIEST_DATE <= day <= LATEST_DATE:
        invalid.append(name)
        return None
    return day


def read_span(params, now):
    """
    The span a dashboard's query string asks for, as ((date_from, date_to),
    invalid). ``date_from`` is None for All Time; ``date_to`` is always a
    date. ``invalid`` names each parameter that is wrong -- ``range`` unless
    it is ``all`` and alone, a date that is not one, the missing end of a
    range, ``to`` before ``from`` -- and nothing is guessed for it.
    """
    if 'range' in params:
        if params.get('range') != ALL_TIME or params.get('from') or params.get('to'):
            return (None, None), ['range']
        return (None, indian_today(now)), []
    invalid = []
    date_from, date_to = _date(params, 'from', invalid), _date(params, 'to', invalid)
    if invalid:
        return (None, None), invalid
    if date_from is None and date_to is None:
        today = indian_today(now)
        return (today - timedelta(days=DEFAULT_DAYS - 1), today), []
    if date_from is None or date_to is None:
        return (None, None), ['from' if date_from is None else 'to']
    if date_from > date_to:
        return (None, None), ['to']
    return (date_from, date_to), []


def day_start(day):
    """The instant an Indian date begins."""
    return datetime.combine(day, time.min, tzinfo=BOOKING_TIMEZONE)


def indian_date(instant):
    """The Indian date an instant falls on."""
    return instant.astimezone(BOOKING_TIMEZONE).date()


def instant_on_dates(field, date_from, date_to):
    """``field`` (an instant) on the Indian dates ``date_from`` to ``date_to``, inclusive; from the first record when ``date_from`` is None."""
    on_dates = Q(**{f'{field}__lt': day_start(date_to + timedelta(days=1))})
    return on_dates if date_from is None else on_dates & Q(**{f'{field}__gte': day_start(date_from)})


def date_on_dates(field, date_from, date_to):
    """``field`` (a plain date, already an Indian one) from ``date_from`` to ``date_to``, inclusive; from the first when ``date_from`` is None."""
    on_dates = Q(**{f'{field}__lte': date_to})
    return on_dates if date_from is None else on_dates & Q(**{f'{field}__gte': date_from})


def shown_range(date_from, date_to, first=None):
    """
    The span as a dashboard's answer names it. For All Time ``from`` is the
    first date a record counted falls on (``first``), or None when none does.
    """
    start = date_from if date_from is not None else first
    return {'from': start.isoformat() if start else None, 'to': date_to.isoformat(), 'all_time': date_from is None}


def trend_unit(date_from, date_to):
    days = (date_to - date_from).days + 1
    if days <= DAILY_DAYS:
        return 'day'
    if days <= WEEKLY_DAYS:
        return 'week'
    return 'month' if days <= MONTHLY_DAYS else 'year'


def bucket_start(day, unit):
    """The first day of the day, week (from Monday), month or year ``day`` falls in."""
    if unit == 'day':
        return day
    if unit == 'week':
        return day - timedelta(days=day.weekday())
    return day.replace(day=1) if unit == 'month' else day.replace(month=1, day=1)


def _following(start, unit):
    if unit == 'day':
        return start + timedelta(days=1)
    if unit == 'week':
        return start + timedelta(days=7)
    if unit == 'month':
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.replace(year=start.year + 1)


def trend_buckets(date_from, date_to):
    """
    The span cut into buckets, as (unit, [(start, first, last)]): ``start`` is
    the key bucket_start gives each day in it, ``first`` and ``last`` the
    bucket's own dates cut to the span.
    """
    unit = trend_unit(date_from, date_to)
    buckets, start = [], bucket_start(date_from, unit)
    while start <= date_to:
        following = _following(start, unit)
        buckets.append((start, max(start, date_from), min(following - timedelta(days=1), date_to)))
        start = following
    return unit, buckets
