"""
Settings-time guards, kept out of ``config/settings.py`` so they can be
unit-tested without re-importing the settings module.

Nothing here may import ``django.conf.settings`` -- these functions run *while*
the settings module is still being evaluated.
"""

from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

# Hosts a plain-HTTP development stack is served from. ALLOW_INSECURE_COOKIES
# is only honoured when every browser origin is one of these over http://.
LOCAL_DEV_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})

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


def _is_local_http_origin(origin):
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme == 'http' and (parts.hostname or '') in LOCAL_DEV_HOSTS


def validate_cookie_and_origin_settings(
    *,
    debug,
    session_cookie_secure,
    csrf_cookie_secure,
    allow_insecure_cookies,
    cors_allowed_origins,
    csrf_trusted_origins,
):
    """
    Refuse to boot, when DEBUG is off, with cookies that would travel over
    plain HTTP or with an empty cross-origin allowlist.

    The session and CSRF cookies carry the whole login, so in production they
    must be Secure. The documented local Docker stack runs DEBUG=False over
    plain HTTP on purpose, and opts out *explicitly* with
    ALLOW_INSECURE_COOKIES=True -- a name that cannot be mistaken for a
    production setting. Even then the opt-out is refused unless every SPA
    origin is http://localhost (or a loopback address), so a development .env
    copied onto a real host still fails closed. An empty CORS or CSRF origin
    list means no browser client can ever log in, so it is treated as a
    misconfiguration too.
    """
    if debug:
        return

    if not (session_cookie_secure and csrf_cookie_secure):
        if not allow_insecure_cookies:
            raise ImproperlyConfigured(
                "SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE must both be True when "
                "DEBUG=False so the login cookies are never sent over plain HTTP. "
                "For a LOCAL stack served over http:// only, set "
                "ALLOW_INSECURE_COOKIES=True explicitly; never in production."
            )
        non_local = sorted({
            origin for origin in [*cors_allowed_origins, *csrf_trusted_origins]
            if not _is_local_http_origin(origin)
        })
        if non_local:
            raise ImproperlyConfigured(
                "ALLOW_INSECURE_COOKIES is a local-development switch and is only "
                "honoured when every CORS/CSRF origin is http://localhost or a "
                f"loopback address. Refusing it for: {', '.join(non_local)}. Serve "
                "the site over HTTPS with SESSION_COOKIE_SECURE=True instead."
            )

    if not cors_allowed_origins:
        raise ImproperlyConfigured(
            "CORS_ALLOWED_ORIGINS is empty. The Hub and Learn SPAs call this API "
            "cross-origin, so list their exact origins (scheme + host + port) "
            "before running with DEBUG=False."
        )

    if not csrf_trusted_origins:
        raise ImproperlyConfigured(
            "CSRF_TRUSTED_ORIGINS is empty. Every state-changing request from "
            "the SPAs is CSRF-checked against this list, so set it to the same "
            "origins as CORS_ALLOWED_ORIGINS before running with DEBUG=False."
        )
