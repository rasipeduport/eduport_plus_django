"""
A tutor's permanent Google Meet link: the one rule for what it may be.

A tutor (accounts.User, role TUTOR) has at most one, ``tutor_meet_link``: the
Meet room their Demo and Diagnostic bookings are taught in. Each booking keeps
its own copy (bookings.models.BookingBase.tutor_meet_link), so a later change
never rewrites the link a past booking was taught in
(bookings.booking_service.set_tutor_meet_link). It has nothing to do with
students.Student.meet_link, the room of an enrolled student's own classes.

Only a Google Meet meeting link is accepted, stored as
``https://meet.google.com/<code>`` with the code in its usual abc-defg-hij
form. Pasted links may leave out the ``https://`` and may carry what a browser
adds after the code (``?authuser=0``, a trailing slash); that is dropped. Any
other address -- another host, ``http://``, a ``meet.google.com/new`` that would
start a new meeting, a lookup or nickname link -- is refused, never guessed at.
The database checks the stored form too (MEET_LINK_DB_PATTERN).
"""
import re

from django.core.exceptions import ValidationError

MEET_LINK_EXAMPLE = 'https://meet.google.com/abc-defg-hij'
MEET_LINK_MAX_LENGTH = 64
# The stored form, as the database checks it (accounts.0016, bookings.0007).
MEET_LINK_DB_PATTERN = r'^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}$'
# What is accepted from a person: the stored form, perhaps without its scheme,
# in any letter case, with a trailing slash or a query string or fragment after it.
# ASCII only: without it, IGNORECASE lets [a-z] match the Kelvin sign and the like.
_ACCEPTED = re.compile(
    r'^(?:https://)?meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})/?(?:[?#]\S*)?$',
    re.IGNORECASE | re.ASCII,
)
# Longer than any link worth reading: refused before it is matched.
_MAX_INPUT = 300

INVALID_MESSAGE = f'Enter a Google Meet link such as {MEET_LINK_EXAMPLE}.'


class InvalidMeetLink(ValueError):
    """The value is not a Google Meet meeting link."""

    def __init__(self, message=INVALID_MESSAGE):
        super().__init__(message)
        self.message = message


def canonical_meet_link(value):
    """
    ``value`` as the stored link (``https://meet.google.com/abc-defg-hij``),
    or None for an empty value (no link). Raises InvalidMeetLink for anything
    that is not a Google Meet meeting link.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidMeetLink('The Meet link must be text.')
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_INPUT:
        raise InvalidMeetLink()
    match = _ACCEPTED.match(text)
    if match is None:
        raise InvalidMeetLink()
    return f'https://meet.google.com/{match.group(1).lower()}'


def validate_meet_link(value):
    """Model-field validator: ``value`` is already a link in its stored form."""
    if value in (None, ''):
        return
    if not isinstance(value, str) or not re.fullmatch(MEET_LINK_DB_PATTERN, value):
        raise ValidationError(INVALID_MESSAGE, code='invalid_meet_link')
