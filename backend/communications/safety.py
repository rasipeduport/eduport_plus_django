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
(communications.formatting); one that is not is refused (ImproperlyConfigured,
and the system check communications.E002).

The dispatcher asks the same questions before it picks anything up: nothing
at all while sending is off or the provider sends nothing
(sending_block_for_all), and only messages to allowed numbers otherwise
(allowed_recipients) -- so a message the gate would hold back never takes an
allowed one's place in a batch (communications.sending.due_message_ids).
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import TextChoices

from .formatting import InvalidWhatsAppNumber, whatsapp_number
from .providers import get_provider


class SendBlock(TextChoices):
    """Why a message is not handed to WhatsApp."""
    SENDING_DISABLED = 'SENDING_DISABLED', 'Sending is switched off'
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


def sending_block_for_all(provider=None):
    """Why no message at all may be handed to ``provider`` (default: the configured one) -- a SendBlock -- or None."""
    if not settings.COMMUNICATIONS_SENDING_ENABLED:
        return SendBlock.SENDING_DISABLED
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
