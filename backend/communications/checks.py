"""
System checks on the WhatsApp settings: a misconfiguration stops `migrate`
(and so the container) instead of surfacing at the first send.
"""
from django.conf import settings
from django.core.checks import Error
from django.core.exceptions import ImproperlyConfigured

from .providers import get_provider
from .safety import allowlist

# Seconds a provider call may take: long enough for a slow API, short enough
# that a hung one never holds a sender for long.
TIMEOUT_RANGE = range(1, 61)


def check_whatsapp_settings(app_configs=None, **kwargs):
    errors = []
    try:
        get_provider()
    except ImproperlyConfigured as exc:
        errors.append(Error(str(exc), id='communications.E001'))
    try:
        allowlist()
    except ImproperlyConfigured as exc:
        errors.append(Error(str(exc), id='communications.E002'))
    timeout = settings.COMMUNICATIONS_PROVIDER_TIMEOUT
    if not isinstance(timeout, int) or timeout not in TIMEOUT_RANGE:
        errors.append(Error(
            f'COMMUNICATIONS_PROVIDER_TIMEOUT must be whole seconds from 1 to 60, not {timeout!r}.',
            id='communications.E003',
        ))
    return errors
