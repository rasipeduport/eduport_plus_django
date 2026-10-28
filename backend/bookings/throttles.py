"""
Rate limits for the public booking API, per parent address.

Every call comes from the marketing server, so the address counted is the one
it forwards (bookings.authentication.client_ip). The counts live in Django's
default cache -- local memory, per gunicorn worker -- so with N workers an
address gets up to N times the rate until the cache is Redis. The per-phone
daily limit (settings.BOOKING_PHONE_DAILY_LIMIT) is counted in the database
and is exact.
"""
from rest_framework.throttling import SimpleRateThrottle

from .authentication import client_ip


class _ParentAddressThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': client_ip(request) or self.get_ident(request)}


class BookingCreateThrottle(_ParentAddressThrottle):
    scope = 'public_booking'


class BookingCalendarThrottle(_ParentAddressThrottle):
    scope = 'public_booking_calendar'
