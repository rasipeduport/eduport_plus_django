"""
Rate limits for the password endpoints.

* ``LoginIPThrottle`` -- POST /api/auth/login/ per client address, whatever the
  username. Rate: ``DEFAULT_THROTTLE_RATES['login_ip']``.
* ``PasswordChangeThrottle`` -- slows down guessing the *current* password
  through the change-password endpoint, per user.

Both count in Django's default cache, which is local memory: every gunicorn
worker keeps its own counts, so with N workers an address gets up to N times
the configured rate. That approximation is deliberate -- these limits only
blunt bursts, and nothing on the login path depends on Redis. The real
brute-force defence is the per-account lockout in the database
(accounts.backends), which every worker shares.
"""
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class LoginIPThrottle(SimpleRateThrottle):
    scope = 'login_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class PasswordChangeThrottle(UserRateThrottle):
    scope = 'password_change'
