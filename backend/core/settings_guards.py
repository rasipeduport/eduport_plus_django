"""
Settings-time guards, kept out of ``config/settings.py`` so they can be
unit-tested without re-importing the settings module.

Nothing here may import ``django.conf.settings`` -- these functions run *while*
the settings module is still being evaluated.
"""

from django.core.exceptions import ImproperlyConfigured

# Django's ``startproject`` marks its throwaway key with this prefix. A key that
# still carries it has never been rotated, so it must never reach production.
INSECURE_SECRET_KEY_PREFIX = 'django-insecure-'

# The length of a freshly generated Django key, and the threshold Django's own
# ``security.W009`` deploy check uses.
MIN_SECRET_KEY_LENGTH = 50


def validate_production_settings(*, debug, secret_key, allowed_hosts):
    """
    Refuse to boot with a development-grade configuration when DEBUG is off.

    Raising here (rather than warning) is deliberate: a container that cannot
    start is a visible, recoverable failure, whereas one that starts with the
    fallback secret key and an empty host allowlist is a silent one.
    """
    if debug:
        return

    if not secret_key or secret_key.startswith(INSECURE_SECRET_KEY_PREFIX):
        raise ImproperlyConfigured(
            "SECRET_KEY is unset or still the insecure development fallback. "
            "Set a unique SECRET_KEY in the environment before running with "
            "DEBUG=False. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )

    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise ImproperlyConfigured(
            f"SECRET_KEY is only {len(secret_key)} characters long; at least "
            f"{MIN_SECRET_KEY_LENGTH} are required when DEBUG=False."
        )

    if not allowed_hosts:
        raise ImproperlyConfigured(
            "ALLOWED_HOSTS is empty. Set it to the comma-separated hostnames "
            "this deployment serves (e.g. ALLOWED_HOSTS=api.example.com) before "
            "running with DEBUG=False."
        )


def mock_auth_enabled(*, debug, env_flag):
    """
    Whether the ``mock:`` login shortcut is available.

    Mock auth skips Google token verification entirely and logs in as whatever
    email the caller puts in the credential string, so it is gated on DEBUG *as
    well as* its own flag. Setting ALLOW_MOCK_AUTH=True in a production
    environment therefore cannot turn it on -- the answer is False whenever
    DEBUG is off, whatever the environment says.
    """
    return bool(debug) and bool(env_flag)
