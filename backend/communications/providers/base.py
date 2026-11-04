"""
What every WhatsApp provider looks like (Phase 2B). WhatsApp is the only
channel parent messages go through; a provider is one way of handing a message
to it, chosen by COMMUNICATIONS_WHATSAPP_PROVIDER (communications.providers).

A provider says whether it reaches anyone at all (``sends``) and which
delivery states it can report (``statuses``): no other state is ever recorded
for its messages. Whether a message may be handed to it -- sending switched
on, a recipient allowed -- is decided before it is asked
(communications.safety). The intended production provider is Meta's WhatsApp
Cloud API, added once Eduport Plus has its own WhatsApp Business account and
approved templates; the webhook methods below are its future status reports.
"""
from dataclasses import dataclass, field

from ..models import MessageStatus

# What a provider may answer when it takes a message: queued with it, or sent.
ACCEPTED_STATUSES = (MessageStatus.QUEUED, MessageStatus.SENT)


class ProviderError(Exception):
    """A provider used in a way it cannot be."""


class ProviderNotConfigured(ProviderError):
    """The ``none`` provider asked to send: no WhatsApp provider is configured."""


@dataclass(frozen=True)
class OutgoingMessage:
    """One message as a provider receives it."""
    # Ours (communications.Message): the client reference, for a provider that takes one.
    message_id: str
    # The parent's international number, digits only (formatting.whatsapp_number).
    to: str
    # The message in WhatsApp's formatting (formatting.whatsapp_message).
    text: str
    template_key: str
    # Placeholder values, for a provider that sends approved templates rather than text.
    variables: dict = field(default_factory=dict)
    # This provider's approved template for the version (MessageTemplateVersion.provider_refs).
    provider_ref: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SendResult:
    """What a provider did with one message: accepted it, or failed with a code."""
    accepted: bool
    # When accepted: QUEUED or SENT, as the provider reports it.
    status: str = ''
    provider_message_id: str = ''
    error_code: str = ''
    error_message: str = ''
    # When not accepted: whether trying again later may work.
    retryable: bool = False

    def __post_init__(self):
        if self.accepted and self.status not in ACCEPTED_STATUSES:
            raise ValueError('An accepted message is Queued or Sent.')
        if not self.accepted and (self.status or not self.error_code):
            raise ValueError('A failed send has an error code and no status.')


@dataclass(frozen=True)
class StatusUpdate:
    """One delivery state a provider reported for a message, in its webhook (communications.status_updates)."""
    provider_message_id: str
    status: str
    provider_status: str = ''
    occurred_at: object = None
    error_code: str = ''
    error_message: str = ''
    # For a failure: whether it is about the moment (True) or the message (False); None when unknown.
    error_temporary: object = None
    # What tells a repeated report from a new one.
    event_key: str = ''


class WhatsAppProvider:
    name = ''
    # Whether send() reaches anyone; a provider that does not leaves messages Pending.
    sends = True
    # The MessageStatus values it can report.
    statuses = frozenset()

    def send(self, message, timeout):
        """Hand ``message`` (an OutgoingMessage) to WhatsApp, waiting ``timeout`` seconds at most. Returns a SendResult."""
        raise NotImplementedError

    def verify_webhook(self, request):
        """Whether ``request`` really comes from this provider (its signature). None is trusted by default."""
        return False

    def parse_webhook(self, payload):
        """The StatusUpdates in a verified webhook's parsed body, and how many entries were skipped."""
        raise NotImplementedError

    def reports(self, status):
        """Whether this provider can report ``status`` (a MessageStatus)."""
        return status in self.statuses
