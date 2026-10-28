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

from .models import Lead

DIAL_CODE_RE = re.compile(r'^\+[1-9][0-9]{0,3}$')
# E.164: at most 15 digits, country code included.
MAX_PHONE_DIGITS = 15
MIN_NATIONAL_DIGITS = 6


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


def match_lead(details):
    """
    The lead for these details, created if new, with its contact details
    updated to the latest submission. Call inside the booking transaction: a
    concurrent request creating the same lead waits on the unique index, and
    get_or_create then reads the committed row.
    """
    dial, national, phone_key = normalize_phone(details['phone_dial_code'], details['phone_number'])
    student_key = name_key(details['student_name'])
    if not student_key:
        raise InvalidLeadDetails('student_name', 'Enter the student name.')
    # NFKC can lengthen text (one ligature becomes several letters), so a name
    # that fits its own column can still overflow the key's.
    if len(student_key) > Lead._meta.get_field('student_name_key').max_length:
        raise InvalidLeadDetails('student_name', 'Enter a shorter student name.')
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
    lead, created = Lead.objects.get_or_create(phone_key=phone_key, student_name_key=student_key, defaults=latest)
    if not created:
        changed = [field for field, value in latest.items() if getattr(lead, field) != value]
        if changed:
            for field in changed:
                setattr(lead, field, latest[field])
            lead.save(update_fields=[*changed, 'updated_at'])
    return lead
