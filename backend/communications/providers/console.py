"""
A provider for local development: each message is written to the log, as
WhatsApp would show it, and nobody is contacted. It reports Sent -- the log
line is the send -- and never Delivered or Read, which it cannot know. The
recipient shows by its last four digits only.
"""
import logging

from ..models import MessageStatus
from .base import SendResult, WhatsAppProvider

logger = logging.getLogger(__name__)


def masked(number):
    """``number`` with all but its last four digits hidden."""
    return f'+{"*" * max(len(number) - 4, 0)}{number[-4:]}'


class ConsoleProvider(WhatsAppProvider):
    name = 'console'
    statuses = frozenset({MessageStatus.SENT})

    def send(self, message, timeout):
        logger.info(
            'WhatsApp (console, not sent) to %s -- %s, message %s:\n%s',
            masked(message.to), message.template_key, message.message_id, message.text,
        )
        return SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id=f'console-{message.message_id}')
