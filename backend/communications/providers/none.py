"""
The default provider: no WhatsApp provider is configured, so nothing is sent.
Messages stay Pending -- ready for the BDE to send by hand -- until one is.
"""
from .base import ProviderNotConfigured, WhatsAppProvider


class NoneProvider(WhatsAppProvider):
    name = 'none'
    sends = False
    statuses = frozenset()

    def send(self, message, timeout):
        # Never reached: communications.safety stops a message before a
        # provider that does not send. Refuse loudly if it ever is.
        raise ProviderNotConfigured('No WhatsApp provider is configured; nothing can be sent.')
