"""
Matching a booking to its lead: one lead per phone number and student name.

The pages send the phone as a dial code picked from a list plus the digits the
parent typed (ASCII 0-9 only, as the pages' input keeps; other scripts'
digits would make a key that matches nothing and cannot be dialled). Every
country the pages offer uses a leading 0 only as a
domestic trunk prefix (and +1 a leading 1), so dropping it makes "0501234567"
and "501234567" the same number. A parent who retypes the country code inside
the number gets a separate lead: a false split, never a wrong merge.
"""
import re
import unicodedata

from . import student_timezones
from .models import Lead

DIAL_CODE_RE = re.compile(r'^\+[1-9][0-9]{0,3}$')
# E.164: at most 15 digits, country code included.
MAX_PHONE_DIGITS = 15
MIN_NATIONAL_DIGITS = 6
# What a lead keeps once it has it: a student's syllabus is never silently
# replaced by a later booking's (the Demo page offers CBSE only). An enquiry
# added without one takes the first syllabus a booking submits.
KEPT_ON_RESUBMISSION = frozenset({'syllabus'})
# The country the booking pages send when the browser's time zone names none
# of theirs (eduport-plus lib/countries.ts): no country at all.
UNDETECTED_COUNTRY = 'Undetected'


class InvalidLeadDetails(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def normalize_phone(dial_code, number):
    """(dial code, national digits, "+<dial><national>") or InvalidLeadDetails."""
    dial = (dial_code or '').strip()
    if not DIAL_CODE_RE.match(dial):
        raise InvalidLeadDetails('phone', 'Enter a valid country code.')
    national = re.sub(r'[^0-9]', '', number or '').lstrip('0')
    if dial == '+1' and len(national) == 11 and national.startswith('1'):
        national = national[1:]
    if len(national) < MIN_NATIONAL_DIGITS or len(dial) - 1 + len(national) > MAX_PHONE_DIGITS:
        raise InvalidLeadDetails('phone', 'Enter a valid phone number.')
    return dial, national, f'{dial}{national}'


def name_key(name):
    """
    A student name compared case- and punctuation-insensitively. Combining
    marks (Indic vowel signs, accents) are part of the name: as separators,
    रानी and रेनु would both read "र न" and two children would share a lead.
    """
    text = unicodedata.normalize('NFKC', name or '').casefold()
    kept = ''.join(char if char.isalnum() or unicodedata.category(char).startswith('M') else ' ' for char in text)
    return ' '.join(kept.split())


def student_name_key(name):
    """``name_key(name)`` as a lead stores it, or InvalidLeadDetails when it is empty or too long."""
    key = name_key(name)
    if not key:
        raise InvalidLeadDetails('student_name', 'Enter the student name.')
    # NFKC can lengthen text (one ligature becomes several letters), so a name
    # that fits its own column can still overflow the key's.
    if len(key) > Lead._meta.get_field('student_name_key').max_length:
        raise InvalidLeadDetails('student_name', 'Enter a shorter student name.')
    return key


def known_country(value):
    """True for a country a lead may keep: neither blank nor the pages' UNDETECTED_COUNTRY."""
    value = (value or '').strip()
    return bool(value) and value.casefold() != UNDETECTED_COUNTRY.casefold()


def _kept(field, current, submitted):
    """Whether a lead keeps ``current`` for ``field`` over a later submission's ``submitted``."""
    if field == 'country':
        # The pages' country is the one the browser's time zone suggests: it
        # never replaces a country the lead has, and "Undetected" is none.
        return known_country(current) or not known_country(submitted)
    return field in KEPT_ON_RESUBMISSION and bool(current)


def match_lead(details):
    """
    The lead for these details, created if new, with its contact details
    updated to the latest submission -- all but a syllabus it already has,
    which a later submission never overwrites, and a country it already has,
    which the booking pages' country (suggested by the browser's time zone, or
    "Undetected") never replaces (the booking keeps what was submitted, in its
    ``details``). A lead with no student time zone takes the submission's, and
    one with a zone keeps it (bookings.student_timezones). Call inside the
    booking transaction: a concurrent request creating the same lead waits on
    the unique index, and get_or_create then reads the committed row.
    """
    dial, national, phone_key = normalize_phone(details['phone_dial_code'], details['phone_number'])
    student_key = student_name_key(details['student_name'])
    latest = {
        'parent_name': details['parent_name'],
        'phone_dial_code': dial,
        'phone_number': national,
        'student_name': details['student_name'],
        'school_name': details['school'],
        'grade': details['student_class'],
        'syllabus': details['syllabus'],
        'country': details.get('country') or '',
    }
    zone = student_timezones.clean(details.get('student_timezone'))
    lead, created = Lead.objects.get_or_create(
        phone_key=phone_key, student_name_key=student_key, defaults={**latest, 'student_timezone': zone},
    )
    if not created:
        changed = [
            field for field, value in latest.items()
            if getattr(lead, field) != value and not _kept(field, getattr(lead, field), value)
        ]
        if changed:
            for field in changed:
                setattr(lead, field, latest[field])
            lead.save(update_fields=[*changed, 'updated_at'])
        if not lead.student_timezone and student_timezones.fill(lead.pk, zone):
            lead.student_timezone = zone
    return lead
