"""
Server-to-server authentication for the public booking API.

Only the marketing site's server calls these endpoints. Its route handlers
send ``Authorization: Bearer <key>`` with a key from BOOKING_SERVICE_API_KEYS
(two may be configured at once, so a key can be rotated). No session is read,
so staff cookies never count here and no CSRF check applies; with no key
configured, every request is refused.
"""
import hmac
import ipaddress
import logging

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)

# A key shorter than this is ignored: a guessable key would open the API.
MIN_KEY_LENGTH = 32
# The parent's address, as the marketing server saw it.
CLIENT_IP_HEADER = 'HTTP_X_BOOKING_CLIENT_IP'


class BookingService:
    """``request.auth`` of a call that presented a valid service key."""


def configured_keys():
    keys = [key.strip() for key in settings.BOOKING_SERVICE_API_KEYS if key and key.strip()]
    usable = [key for key in keys if len(key) >= MIN_KEY_LENGTH]
    if len(usable) < len(keys):
        logger.warning('Ignoring %d booking service key(s) shorter than %d characters.', len(keys) - len(usable), MIN_KEY_LENGTH)
    return usable


class BookingServiceAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b'bearer':
            return None
        if len(parts) != 2 or not any(hmac.compare_digest(parts[1], key.encode()) for key in configured_keys()):
            raise AuthenticationFailed('Invalid service credentials.')
        return AnonymousUser(), BookingService()

    def authenticate_header(self, request):
        return 'Bearer realm="booking-service"'


class IsBookingService(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, BookingService)


def client_ip(request):
    """
    The parent's address as the marketing server reports it, believed only on
    an authenticated service call; any other forwarded header is ignored.
    """
    if not isinstance(request.auth, BookingService):
        return None
    value = request.META.get(CLIENT_IP_HEADER, '').strip()
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None
