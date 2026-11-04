"""
Messages as WhatsApp shows them, and recipients as WhatsApp addresses them.

Templates mark bold the Markdown way, **text**; WhatsApp's bold is *text*.
Nothing else in a template changes: emoji, apostrophes and blank lines go as
written. The template is converted on its own, before any value goes in, and
every value goes in as plain text (whatsapp_value): on one line, and with
WhatsApp's formatting marks -- * _ ~ ` -- shown as look-alike characters
WhatsApp does not format with. So a name or a phone number can never turn on
bold, italics or a quote, nor break the template's own bold around it.

A recipient is a full international number: + and the country code, then the
number without its local leading 0 -- what a lead's phone_key holds
(bookings.leads.normalize_phone). WhatsApp takes the same digits without the
+. No country is ever assumed: Gulf, Indian and every other number carries
its own code, and a number without one is refused, never given India's.
"""
import re

from .rendering import render

BOLD = re.compile(r'\*\*(.+?)\*\*')
# E.164: a country code (never starting 0) and the number, 7 to 15 digits in
# all -- the bounds a lead's phone number is held to.
INTERNATIONAL_NUMBER = re.compile(r'\+([1-9][0-9]{6,14})')
# What people type between digits.
_SEPARATORS = re.compile(r'[\s().-]')
# WhatsApp's formatting marks, as a value shows them: asterisk operator,
# modifier low macron, tilde operator, modifier grave accent.
_VALUE_MARKS = str.maketrans({'*': chr(0x2217), '_': chr(0x02CD), '~': chr(0x223C), '`': chr(0x02CB)})
# Line breaks, tabs and runs of spaces: a value is one line.
_WHITESPACE = re.compile(r'\s+')


class InvalidWhatsAppNumber(ValueError):
    """Not a full international number (+ and the country code)."""


def whatsapp_text(body):
    """A template ``body`` with its Markdown bold (**text**) as WhatsApp's (*text*)."""
    return BOLD.sub(r'*\1*', body)


def whatsapp_value(value):
    """A placeholder value as plain text in WhatsApp: one line, single spaces, no formatting marks."""
    return _WHITESPACE.sub(' ', value).strip().translate(_VALUE_MARKS)


def whatsapp_message(body, values):
    """
    The message a template ``body`` makes with ``values`` (by placeholder
    name), as WhatsApp shows it: the template's bold converted, then each
    value put in as plain text. MissingValues for a value that is empty, or
    nothing but spaces -- never a blank.
    """
    return render(whatsapp_text(body), {name: whatsapp_value(value) for name, value in values.items() if value})


def whatsapp_number(phone):
    """
    ``phone`` -- "+<country code><number>", spaces, dashes or brackets
    allowed -- as the digits WhatsApp addresses it by. InvalidWhatsAppNumber
    for anything else, a number without its country code included.
    """
    match = INTERNATIONAL_NUMBER.fullmatch(_SEPARATORS.sub('', phone or ''))
    if match is None:
        raise InvalidWhatsAppNumber('Not an international number with its country code.')
    return match.group(1)
