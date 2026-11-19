"""
Whether a parent message may be handed to WhatsApp at all, asked before any
provider is (Phase 2B). Closed by default on every count:

* COMMUNICATIONS_SENDING_ENABLED is off unless switched on;
* the default provider, ``none``, sends nothing, so messages stay Pending;
* only numbers on COMMUNICATIONS_RECIPIENT_ALLOWLIST may receive one, unless
  COMMUNICATIONS_ALLOW_ALL_RECIPIENTS is set on purpose -- an empty list means
  nobody, never everybody -- so the dummy parents in a local database can
  never be messaged.

Allow-list entries are full international numbers, like every recipient
(communications.formatting); one that is not is refused (ImproperlyConfigured).

Invalid WhatsApp settings -- an unknown provider, a malformed allow-list
entry, a timeout outside 1-60 seconds (configuration_problems) -- never stop
the backend: the system check reports them as warnings (communications.checks)
and, while sending is on, every message is held back as MISCONFIGURED until
they are fixed. A malformed allow-list holds nothing back while every number
is allowed on purpose, since it is not read then (blocks_sending).

The dispatcher asks the same questions before it picks anything up: nothing
at all while sending is off, the settings are invalid or the provider sends
nothing (sending_block_for_all), and only messages to allowed numbers
otherwise (allowed_recipients) -- so a message the gate would hold back never
takes an allowed one's place in a batch (communications.sending.due_message_ids).
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import TextChoices

from .formatting import InvalidWhatsAppNumber, whatsapp_number
from .providers import get_provider

# Seconds a provider call may take: long enough for a slow API, short enough
# that a hung one never holds a sender for long.
TIMEOUT_RANGE = range(1, 61)

# The problems configuration_problems() finds, by the system check id that reports each.
PROVIDER_PROBLEM = 'communications.W001'
ALLOWLIST_PROBLEM = 'communications.W002'
TIMEOUT_PROBLEM = 'communications.W003'


class SendBlock(TextChoices):
    """Why a message is not handed to WhatsApp."""
    SENDING_DISABLED = 'SENDING_DISABLED', 'Sending is switched off'
    MISCONFIGURED = 'MISCONFIGURED', 'The WhatsApp settings are invalid'
    NO_PROVIDER = 'NO_PROVIDER', 'No WhatsApp provider is configured'
    INVALID_RECIPIENT = 'INVALID_RECIPIENT', 'Not an international WhatsApp number'
    RECIPIENT_NOT_ALLOWED = 'RECIPIENT_NOT_ALLOWED', 'Not on the recipient allow-list'


def allowlist():
    """The allow-listed numbers, as WhatsApp addresses them. ImproperlyConfigured for an entry that is not one."""
    numbers = set()
    for entry in settings.COMMUNICATIONS_RECIPIENT_ALLOWLIST:
        if not entry.strip():
            continue
        try:
            numbers.add(whatsapp_number(entry))
        except InvalidWhatsAppNumber:
            raise ImproperlyConfigured(
                f'COMMUNICATIONS_RECIPIENT_ALLOWLIST: {entry!r} is not an international number '
                '(+, the country code, then the number without its leading 0).'
            ) from None
    return numbers


def recipient_allowed(phone):
    """Whether ``phone`` may receive messages: on the allow-list, or every number allowed on purpose."""
    if settings.COMMUNICATIONS_ALLOW_ALL_RECIPIENTS:
        return True
    try:
        return whatsapp_number(phone) in allowlist()
    except InvalidWhatsAppNumber:
        return False


def allowed_recipients():
    """
    The numbers messages may go to, as messages keep them -- "+<country code>
    <number>" (bookings.leads.normalize_phone) -- or None when every number
    is allowed on purpose.
    """
    if settings.COMMUNICATIONS_ALLOW_ALL_RECIPIENTS:
        return None
    return {f'+{number}' for number in allowlist()}


def configuration_problems():
    """
    What is wrong with the WhatsApp settings: (check id, the exact problem)
    pairs, none when they are valid. Never raises.
    """
    problems = []
    try:
        get_provider()
    except ImproperlyConfigured as exc:
        problems.append((PROVIDER_PROBLEM, str(exc)))
    try:
        allowlist()
    except ImproperlyConfigured as exc:
        problems.append((ALLOWLIST_PROBLEM, str(exc)))
    timeout = settings.COMMUNICATIONS_PROVIDER_TIMEOUT
    if not isinstance(timeout, int) or timeout not in TIMEOUT_RANGE:
        problems.append((
            TIMEOUT_PROBLEM,
            f'COMMUNICATIONS_PROVIDER_TIMEOUT must be whole seconds from 1 to 60, not {timeout!r}.',
        ))
    return problems


def blocks_sending(check_id):
    """Whether the configuration problem ``check_id`` holds sending back: every one, but the allow-list only while it is read."""
    return not (check_id == ALLOWLIST_PROBLEM and settings.COMMUNICATIONS_ALLOW_ALL_RECIPIENTS)


def sending_problems():
    """The configuration_problems() that hold every message back while sending is on."""
    return [(check_id, problem) for check_id, problem in configuration_problems() if blocks_sending(check_id)]


def sending_block_for_all(provider=None):
    """
    Why no message at all may be handed to ``provider`` (default: the
    configured one) -- a SendBlock -- or None. Never raises for invalid
    settings: they are MISCONFIGURED (sending_problems).
    """
    if not settings.COMMUNICATIONS_SENDING_ENABLED:
        return SendBlock.SENDING_DISABLED
    if sending_problems():
        return SendBlock.MISCONFIGURED
    if not (provider or get_provider()).sends:
        return SendBlock.NO_PROVIDER
    return None


def sending_block(phone, provider=None):
    """Why a message to ``phone`` may not be handed to ``provider`` (default: the configured one) -- a SendBlock -- or None."""
    block = sending_block_for_all(provider)
    if block:
        return block
    try:
        whatsapp_number(phone)
    except InvalidWhatsAppNumber:
        return SendBlock.INVALID_RECIPIENT
    if not recipient_allowed(phone):
        return SendBlock.RECIPIENT_NOT_ALLOWED
    return None
