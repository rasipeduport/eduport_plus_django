"""
What the Tutor Earnings API accepts, and how it refuses: amounts in rupees to
the paisa, months and dates in India time, reasons and notes -- and
EarningsError, a refusal with its API code, HTTP status and message.
"""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import connection
from django.utils import timezone

# Months, payment dates and "today" are India's.
INDIA = ZoneInfo('Asia/Kolkata')
PAISA = Decimal('0.01')
MAX_AMOUNT = Decimal('9999999999.99')
MAX_RATE = Decimal('99999999.99')
REASON_MAX_LENGTH = 500
NOTES_MAX_LENGTH = 1000
REFERENCE_MAX_LENGTH = 100

INVALID = 'INVALID_INPUT'


class EarningsError(Exception):
    """A refusal with its API code, HTTP status and message; earnings.views answers it as it is."""

    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def response_data(self):
        return {'error': self.message, 'code': self.code, **self.extra}


def rupees(value, field, *, maximum=MAX_AMOUNT, signed=False):
    """
    ``value`` (a number or its text) as an amount of rupees -- a Decimal with
    at most two decimals, above zero (or, ``signed``, other than zero), at
    most ``maximum`` -- else EarningsError(INVALID_INPUT) naming ``field``.
    """
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise EarningsError(INVALID, 'Enter an amount in rupees.', field=field)
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise EarningsError(INVALID, 'Enter the amount as a number of rupees.', field=field) from None
    if not amount.is_finite():
        raise EarningsError(INVALID, 'Enter the amount as a number of rupees.', field=field)
    if amount < 0 and not signed:
        raise EarningsError(INVALID, 'Enter an amount above ₹0.', field=field)
    # Before quantize, which cannot hold more than 28 digits.
    if amount.copy_abs() > maximum:
        raise EarningsError(INVALID, 'That amount is too large.', field=field)
    if amount != amount.quantize(PAISA):
        raise EarningsError(INVALID, 'Amounts go to the paisa at most (two decimals).', field=field)
    amount = amount.quantize(PAISA)
    if amount == 0:
        raise EarningsError(INVALID, 'Enter an amount above ₹0.', field=field)
    return amount


def text(value, field, *, max_length, required, message):
    """``value`` stripped -- blank as '' -- at most ``max_length`` characters, and present when ``required``."""
    if value is not None and not isinstance(value, str):
        raise EarningsError(INVALID, 'This must be text.', field=field)
    value = (value or '').strip()
    if required and not value:
        raise EarningsError(INVALID, message, field=field)
    if len(value) > max_length:
        raise EarningsError(INVALID, f'Keep this within {max_length} characters.', field=field)
    return value


def reason(value, field='reason'):
    """The reason a change is made: required, at most REASON_MAX_LENGTH characters."""
    return text(value, field, max_length=REASON_MAX_LENGTH, required=True, message='Say why this is being done.')


def month_of(moment):
    """The first day of the month ``moment`` falls in, in India time."""
    return timezone.localtime(moment, INDIA).date().replace(day=1)


def india_today():
    return timezone.localtime(timezone.now(), INDIA).date()


def parse_month(value, field='month'):
    """``value`` as 'YYYY-MM': the first day of that month, else EarningsError."""
    try:
        year, month = (int(part) for part in str(value).split('-'))
        # Before year 9999, so the month after it still exists.
        if not 1 <= year <= 9998:
            raise ValueError(year)
        return date(year, month, 1)
    except (TypeError, ValueError, OverflowError):
        raise EarningsError(INVALID, 'Give the month as YYYY-MM.', field=field) from None


def as_uuid(value):
    """``value`` as a UUID, or None when it is not one (a request naming nothing that exists)."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def parse_date(value, field):
    """``value`` as 'YYYY-MM-DD', else EarningsError."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise EarningsError(INVALID, 'Give the date as YYYY-MM-DD.', field=field) from None


def hours_between(start, end):
    """The hours from ``start`` to ``end``, to two decimals."""
    return (Decimal((end - start).total_seconds()) / Decimal(3600)).quantize(PAISA, rounding=ROUND_HALF_UP)


def priced(units, rate):
    """``units`` at ``rate``, to the paisa (half up)."""
    return (units * rate).quantize(PAISA, rounding=ROUND_HALF_UP)


def lock_tutor(tutor_id):
    """
    Take the transaction's lock on ``tutor_id``'s earnings: payments, voids,
    reversals and adjustments of the same tutor queue behind each other, so a
    balance read under it holds until the transaction ends. Inside an atomic block.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [f'tutor-earnings:{tutor_id}'])


def lock_named(name):
    """Take the transaction's lock named ``name`` (the rates, the sync). Inside an atomic block."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [f'tutor-earnings:{name}'])


def try_lock_named(name):
    """Take the transaction's lock named ``name`` if nobody holds it; whether it was taken."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))', [f'tutor-earnings:{name}'])
        return cursor.fetchone()[0]
