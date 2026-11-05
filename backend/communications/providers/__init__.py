"""
The WhatsApp provider parent messages go through, chosen by
COMMUNICATIONS_WHATSAPP_PROVIDER:

    none     the default: nothing is sent, messages stay Pending
    console  local development: messages are written to the log only

Meta's WhatsApp Cloud API joins these once Eduport Plus has its own WhatsApp
Business account. A name not listed here is refused, never guessed
(ImproperlyConfigured, and the system check communications.E001).
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .console import ConsoleProvider
from .none import NoneProvider

PROVIDERS = {provider.name: provider for provider in (NoneProvider, ConsoleProvider)}


def get_provider(name=None):
    """The provider named ``name`` -- by default the configured one. ImproperlyConfigured for an unknown name."""
    key = (settings.COMMUNICATIONS_WHATSAPP_PROVIDER if name is None else name or '').strip().lower()
    try:
        return PROVIDERS[key]()
    except KeyError:
        raise ImproperlyConfigured(
            f'Unknown WhatsApp provider {key!r} in COMMUNICATIONS_WHATSAPP_PROVIDER. '
            f'Choose one of: {", ".join(sorted(PROVIDERS))}.'
        ) from None
