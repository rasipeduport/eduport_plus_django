"""
Authentication tests: username model rules, password login, the database
lockout shared by the API and the Django admin, rate limits, logout, password
change, the forced first-login change, session lifetime, existing sessions and
deactivation, and the settings guards.
"""
import threading
from collections import Counter
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, authenticate, get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework.throttling import SimpleRateThrottle

from accounts.views import LOGIN_FAILED_RESPONSE, SESSION_BACKEND
from activity.models import ActivityLog
from core.settings_guards import validate_cookie_and_origin_settings
from core.students import EP_STUDENT_COOKIE
from invitations.models import Invitation, InvitationRoleChoices, InvitationStatusChoices

User = get_user_model()

CSRF_URL = '/api/auth/csrf/'
LOGIN_URL = '/api/auth/login/'
GOOGLE_URL = '/api/auth/google/'
LOGOUT_URL = '/api/auth/logout/'
ME_URL = '/api/auth/me/'
CHANGE_URL = '/api/auth/change-password/'
STAFF_ONLY_URL = '/api/students/'
ADMIN_LOGIN_URL = '/admin/login/'

# The path every session issued before the lockout backend recorded.
LEGACY_BACKEND = 'django.contrib.auth.backends.ModelBackend'
SESSION_LIFETIME = 400 * 24 * 60 * 60

STRONG = 'Correct-Horse-Battery-9'
STRONGER = 'Another-Long-Secret-42'

# Admin pages reference static files; the manifest storage would demand a
# collectstatic run, so tests that render them use the plain storage.
PLAIN_STORAGES = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def failure_reasons(user):
    return [
        row.context.get('reason')
        for row in ActivityLog.objects.filter(action='user.sign_in_failed', actor=user).order_by('created_at')
    ]


def throttle_rates(**rates):
    """
    Temporarily change DRF throttle rates. ``override_settings`` is not enough:
    ``SimpleRateThrottle.THROTTLE_RATES`` binds the settings dict at import
    time, so the dict itself is patched in place (and restored afterwards).
    """
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, rates)


class UsernameModelTests(APITestCase):
    def test_username_is_derived_from_the_email_local_part(self):
        user = User.objects.create_user(email='Jane.Doe@Example.com', password=STRONG, full_name='Jane')
        self.assertEqual(user.username, 'jane.doe')
        # normalize_email lower-cases the domain only.
        self.assertEqual(user.email, 'Jane.Doe@example.com')

    def test_derived_usernames_never_collide(self):
        User.objects.create_user(email='jane.doe@one.com', password=STRONG, full_name='Jane One')
        second = User.objects.create_user(email='jane.doe@two.com', password=STRONG, full_name='Jane Two')
        third = User.objects.create_user(email='jane.doe@three.com', password=STRONG, full_name='Jane Three')
        self.assertEqual(second.username, 'jane.doe2')
        self.assertEqual(third.username, 'jane.doe3')

    def test_unusable_local_part_falls_back(self):
        user = User.objects.create_user(email='!!!@example.com', password=STRONG, full_name='Odd')
        self.assertEqual(user.username, 'user')

    def test_explicit_username_is_normalised_to_lower_case(self):
        user = User.objects.create_user(
            email='rasi@eduport.com', username='Rasi_Eduport', password=STRONG, full_name='Rasi'
        )
        self.assertEqual(user.username, 'rasi_eduport')
        user.username = 'RASI_EDUPORT'
        user.save()
        self.assertEqual(User.objects.get(pk=user.pk).username, 'rasi_eduport')

    def test_natural_key_lookup_is_case_insensitive(self):
        user = User.objects.create_user(email='mentor@eduport.com', username='mentor1', password=STRONG, full_name='M')
        self.assertEqual(User.objects.get_by_natural_key('MENTOR1'), user)

    def test_duplicate_username_is_refused(self):
        User.objects.create_user(email='a@eduport.com', username='same', password=STRONG, full_name='A')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email='b@eduport.com', username='SAME', password=STRONG, full_name='B')

    def test_no_password_means_unusable_password(self):
        user = User.objects.create_user(email='google@eduport.com', full_name='G')
        self.assertFalse(user.has_usable_password())

    def test_full_clean_normalises_before_the_uniqueness_check(self):
        User.objects.create_user(email='a@eduport.com', username='rasi', password=STRONG, full_name='A')
        other = User.objects.create_user(email='b@eduport.com', username='other', password=STRONG, full_name='B')
        other.username = 'RASI'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            other.full_clean()
        self.assertIn('username', ctx.exception.message_dict)

    def test_create_superuser_uses_the_createsuperuser_keywords(self):
        root = User.objects.create_superuser(
            username='Root', email='root@eduport.com', full_name='Root', password=STRONG
        )
        self.assertEqual(root.username, 'root')
        self.assertTrue(root.is_staff)
        self.assertTrue(root.is_superuser)
        self.assertEqual(root.role, 'ADMIN')
        self.assertFalse(root.must_change_password)


class PasswordLoginTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG,
            full_name='Mentor One', role='MENTOR',
        )
        self.inactive = User.objects.create_user(
            email='gone@eduport.com', username='gone', password=STRONG,
            full_name='Gone', role='TUTOR', is_active=False,
        )
        self.google_only = User.objects.create_user(
            email='parent@gmail.com', username='parent', full_name='Parent', role='STUDENT',
        )
        # A student account that somehow holds a usable password.
        self.student = User.objects.create_user(
            email='kid@gmail.com', username='kid', password=STRONG, full_name='Kid', role='STUDENT',
        )
        self.locked = User.objects.create_user(
            email='locked@eduport.com', username='locked', password=STRONG, full_name='Locked',
            role='MENTOR', failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=10),
        )

    def login(self, username, password, client=None):
        return (client or self.client).post(
            LOGIN_URL, {"username": username, "password": password}, format='json'
        )

    def test_login_success(self):
        response = self.login('mentor1', STRONG)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'authenticated')
        self.assertEqual(response.data['user']['username'], 'mentor1')
        self.assertFalse(response.data['must_change_password'])
        self.assertIn('permissions', response.data['user'])
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(self.client.session[BACKEND_SESSION_KEY], SESSION_BACKEND)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.filter(actor=self.user, action='user.sign_in').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.context.get('method'), 'password')
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_login_is_case_insensitive_on_the_username(self):
        self.assertEqual(self.login('  MENTOR1 ', STRONG).status_code, status.HTTP_200_OK)

    def test_login_rotates_the_session_key(self):
        self.client.get(CSRF_URL)
        before = self.client.session.session_key
        self.login('mentor1', STRONG)
        self.assertNotEqual(self.client.session.session_key, before)

    def test_every_failure_looks_the_same(self):
        attempts = [
            ('mentor1', 'wrong-password-here'),   # wrong password
            ('nobody', STRONG),                   # unknown username
            ('gone', STRONG),                     # inactive account
            ('parent', STRONG),                   # Google-only account
            ('kid', STRONG),                      # student account, right password
            ('locked', STRONG),                   # locked account, right password
        ]
        for username, password in attempts:
            with self.subTest(username=username):
                response = self.login(username, password)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json(), LOGIN_FAILED_RESPONSE)
                self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_failed_attempts_are_audited_for_existing_accounts_only(self):
        self.login('mentor1', 'wrong-password-here')
        self.login('gone', STRONG)
        self.login('nobody', STRONG)
        failed = ActivityLog.objects.filter(action='user.sign_in_failed')
        self.assertEqual(failed.count(), 2)
        reasons = {row.actor_email: row.context.get('reason') for row in failed}
        self.assertEqual(reasons, {'mentor@eduport.com': 'invalid_password', 'gone@eduport.com': 'inactive'})

    def test_missing_or_malformed_fields(self):
        for body in ({}, {"username": "mentor1"}, {"password": STRONG}, {"username": ["x"], "password": STRONG}):
            with self.subTest(body=body):
                response = self.client.post(LOGIN_URL, body, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'INVALID_INPUT')

    def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(self):
        self.assertEqual((settings.LOGIN_MAX_FAILURES, settings.LOGIN_LOCKOUT_SECONDS), (5, 15 * 60))
        for attempt in range(1, 5):
            self.assertEqual(self.login('mentor1', 'bad').json(), LOGIN_FAILED_RESPONSE)
            self.user.refresh_from_db()
            self.assertEqual(self.user.failed_login_count, attempt)
            self.assertIsNone(self.user.locked_until)

        before = timezone.now()
        self.assertEqual(self.login('mentor1', 'bad').json(), LOGIN_FAILED_RESPONSE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 5)
        expected = before + timedelta(minutes=15)
        self.assertTrue(expected - timedelta(seconds=5) <= self.user.locked_until <= expected + timedelta(seconds=5))

        # The right password does not help while locked, and the answer is the
        # same generic one: the lock itself is not revealed.
        response = self.login('mentor1', STRONG)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), LOGIN_FAILED_RESPONSE)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(failure_reasons(self.user), ['invalid_password'] * 5 + ['locked'])
        # Attempts while locked neither count nor extend the lock.
        locked_until = self.user.locked_until
        self.user.refresh_from_db()
        self.assertEqual((self.user.failed_login_count, self.user.locked_until), (5, locked_until))

    def test_an_expired_lock_lets_the_right_password_in_and_resets(self):
        User.objects.filter(pk=self.user.pk).update(
            failed_login_count=5, locked_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.login('mentor1', STRONG).status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual((self.user.failed_login_count, self.user.locked_until), (0, None))

    def test_a_wrong_password_after_an_expired_lock_starts_a_fresh_count(self):
        User.objects.filter(pk=self.user.pk).update(
            failed_login_count=5, locked_until=timezone.now() - timedelta(seconds=1)
        )
        self.login('mentor1', 'bad')
        self.user.refresh_from_db()
        self.assertEqual((self.user.failed_login_count, self.user.locked_until), (1, None))

    def test_success_resets_the_failure_counter(self):
        for _ in range(4):
            self.login('mentor1', 'bad')
        self.assertEqual(self.login('mentor1', STRONG).status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)
        self.client.post(LOGOUT_URL)
        for _ in range(4):
            self.login('mentor1', 'bad')
        # Four more failures after the reset: still not locked.
        self.assertEqual(self.login('mentor1', STRONG).status_code, status.HTTP_200_OK)

    def test_unknown_usernames_write_nothing(self):
        users_before = User.objects.count()
        with CaptureQueriesContext(connection) as queries:
            for _ in range(6):
                response = self.login('nobody', 'bad')
                self.assertEqual(response.json(), LOGIN_FAILED_RESPONSE)
        writes = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [])
        self.assertEqual(User.objects.count(), users_before)
        self.assertFalse(User.objects.filter(username='nobody').exists())
        self.assertFalse(ActivityLog.objects.filter(action='user.sign_in_failed').exists())

    def test_the_check_holds_the_account_row(self):
        # Concurrent attempts serialise on the row (see ConcurrentLockoutTests);
        # NO KEY so inserts that merely reference the account do not wait.
        with CaptureQueriesContext(connection) as queries:
            self.login('mentor1', 'bad')
        self.assertTrue(any('FOR NO KEY UPDATE' in q['sql'] for q in queries))

    def test_student_accounts_cannot_use_password_login(self):
        response = self.login('kid', STRONG)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), LOGIN_FAILED_RESPONSE)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(failure_reasons(self.student), ['student_account'])
        self.assertFalse(ActivityLog.objects.filter(actor=self.student, action='user.sign_in').exists())

    def test_per_ip_throttle(self):
        with throttle_rates(login_ip='3/min'):
            for _ in range(3):
                self.assertEqual(self.login('mentor1', 'bad').status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(self.login('mentor1', STRONG).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_spoofed_forwarded_for_does_not_reset_the_ip_throttle(self):
        # NUM_PROXIES defaults to 0: the header is ignored, the socket address
        # counts, so rotating X-Forwarded-For buys no extra attempts.
        with throttle_rates(login_ip='3/min'):
            for i in range(3):
                response = self.client.post(
                    LOGIN_URL, {"username": "mentor1", "password": "bad"}, format='json',
                    HTTP_X_FORWARDED_FOR=f'10.0.0.{i}',
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response = self.client.post(
                LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json',
                HTTP_X_FORWARDED_FOR='10.0.0.99',
            )
            self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_audit_ip_ignores_a_spoofed_forwarded_for(self):
        self.client.post(
            LOGIN_URL, {"username": "mentor1", "password": "bad"}, format='json',
            HTTP_X_FORWARDED_FOR='6.6.6.6',
        )
        row = ActivityLog.objects.get(action='user.sign_in_failed', actor=self.user)
        self.assertEqual(row.context.get('ip'), '127.0.0.1')

    def test_audit_ip_uses_the_proxy_appended_entry_when_configured(self):
        conf = dict(settings.REST_FRAMEWORK, NUM_PROXIES=1)
        with override_settings(REST_FRAMEWORK=conf):
            self.client.post(
                LOGIN_URL, {"username": "mentor1", "password": "bad"}, format='json',
                HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7',
            )
        row = ActivityLog.objects.get(action='user.sign_in_failed', actor=self.user)
        self.assertEqual(row.context.get('ip'), '203.0.113.7')

    @override_settings(LOGIN_MAX_FAILURES=3)
    def test_unicode_variants_share_one_lockout_and_are_audited(self):
        # Fullwidth and mathematical-bold spellings NFKC-normalise to
        # "mentor1", so they must hit the same failure counter and audit row.
        for variant in ('ｍｅｎｔｏｒ１', '𝐦𝐞𝐧𝐭𝐨𝐫𝟏', 'Mentor1'):
            self.login(variant, 'bad')
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 3)
        self.assertIsNotNone(self.user.locked_until)
        self.assertEqual(self.login('mentor1', STRONG).json(), LOGIN_FAILED_RESPONSE)
        self.assertEqual(failure_reasons(self.user), ['invalid_password'] * 3 + ['locked'])

    def test_unicode_variant_of_the_username_can_sign_in(self):
        self.assertEqual(self.login('ｍｅｎｔｏｒ１', STRONG).status_code, status.HTTP_200_OK)

    def test_logout_clears_the_session_and_persona_cookie(self):
        self.login('mentor1', STRONG)
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.cookies[EP_STUDENT_COOKIE]['max-age'], 0)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(ActivityLog.objects.filter(actor=self.user, action='user.sign_out').exists())

    def test_logout_invalidates_the_session_server_side(self):
        self.login('mentor1', STRONG)
        session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        # Replaying the old cookie from another client gets nowhere.
        replay = APIClient()
        replay.cookies[settings.SESSION_COOKIE_NAME] = session_key
        self.assertEqual(replay.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_logout_needs_a_session(self):
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_me_reports_identity_and_access_and_refreshes_the_csrf_cookie(self):
        self.login('mentor1', STRONG)
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user = response.data['user']
        for key in ('username', 'permissions', 'groups', 'must_change_password', 'is_superuser', 'last_login'):
            self.assertIn(key, user)
        # Every effective permission: here the Mentor role group's.
        self.assertIn('accounts.view_mentored_students', user['permissions'])
        self.assertNotIn('accounts.view_all_students', user['permissions'])
        self.assertFalse(response.data['must_change_password'])
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)

    def test_me_sets_the_csrf_cookie_even_when_anonymous(self):
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)

    def test_csrf_endpoint_sets_the_cookie_and_returns_the_token(self):
        response = self.client.get(CSRF_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)
        self.assertTrue(response.data['csrf_token'])

    def test_login_and_me_return_a_csrf_token(self):
        self.assertTrue(self.login('mentor1', STRONG).data['csrf_token'])
        self.assertTrue(self.client.get(ME_URL).data['csrf_token'])


class PasswordChangeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG,
            full_name='Mentor One', role='MENTOR',
        )
        self.assertTrue(self.client.login(username='mentor1', password=STRONG))

    def change(self, current, new, client=None):
        return (client or self.client).post(
            CHANGE_URL, {"current_password": current, "new_password": new}, format='json'
        )

    def test_requires_the_current_password(self):
        response = self.change('not-the-password', STRONGER)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'INVALID_CURRENT_PASSWORD')
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(STRONG))

    def test_rejects_reusing_the_current_password(self):
        response = self.change(STRONG, STRONG)
        self.assertEqual(response.data['error'], 'PASSWORD_REUSED')

    def test_the_policy_is_only_a_minimum_length(self):
        # Shorter than 8 characters is refused, with the reason.
        for short in ('short', '1234567'):
            with self.subTest(short=short):
                response = self.change(STRONG, short)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'PASSWORD_POLICY')
                self.assertTrue(response.data['details'])
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password(STRONG))
        # Nothing else is checked: all digits, a common word and the user's own
        # name are all accepted once they are 8 characters long.
        current = STRONG
        for simple in ('12345678', 'password', 'Mentor One'):
            with self.subTest(simple=simple):
                response = self.change(current, simple)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                current = simple
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password('Mentor One'))

    def test_missing_fields(self):
        response = self.client.post(CHANGE_URL, {"new_password": STRONGER}, format='json')
        self.assertEqual(response.data['error'], 'INVALID_INPUT')

    def test_success_keeps_this_session_and_clears_the_flag(self):
        User.objects.filter(pk=self.user.pk).update(must_change_password=True)
        response = self.change(STRONG, STRONGER)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONGER))
        self.assertFalse(self.user.must_change_password)
        self.assertIsNotNone(self.user.password_changed_at)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)
        self.assertTrue(ActivityLog.objects.filter(actor=self.user, action='user.password_change').exists())

    def test_other_sessions_are_signed_out(self):
        other = APIClient()
        self.assertTrue(other.login(username='mentor1', password=STRONG))
        self.assertEqual(other.get(ME_URL).status_code, status.HTTP_200_OK)
        self.assertEqual(self.change(STRONG, STRONGER).status_code, status.HTTP_200_OK)
        self.assertEqual(other.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_requires_a_session(self):
        self.assertEqual(self.change(STRONG, STRONGER, client=APIClient()).status_code, status.HTTP_403_FORBIDDEN)

    def test_is_throttled_per_user(self):
        with throttle_rates(password_change='2/hour'):
            self.change('wrong', STRONGER)
            self.change('wrong', STRONGER)
            self.assertEqual(self.change('wrong', STRONGER).status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class ForcedPasswordChangeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='new.mentor@eduport.com', username='new.mentor', password=STRONG,
            full_name='New Mentor', role='MENTOR', must_change_password=True,
        )

    def test_temporary_password_blocks_everything_but_the_change_flow(self):
        response = self.client.post(LOGIN_URL, {"username": "new.mentor", "password": STRONG}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['must_change_password'])

        blocked = self.client.get(STAFF_ONLY_URL)
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.json()['error'], 'PASSWORD_CHANGE_REQUIRED')

        me = self.client.get(ME_URL)
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertTrue(me.data['must_change_password'])

        changed = self.client.post(
            CHANGE_URL, {"current_password": STRONG, "new_password": STRONGER}, format='json'
        )
        self.assertEqual(changed.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(STAFF_ONLY_URL).status_code, status.HTTP_200_OK)

    def test_logout_is_allowed_while_flagged(self):
        self.client.post(LOGIN_URL, {"username": "new.mentor", "password": STRONG}, format='json')
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)

    @override_settings(STORAGES=PLAIN_STORAGES)
    def test_the_django_admin_is_refused_until_the_password_is_changed(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True, is_superuser=True)
        browser = Client()
        signed_in = browser.post(ADMIN_LOGIN_URL, {'username': 'new.mentor', 'password': STRONG, 'next': '/admin/'})
        self.assertEqual(signed_in.status_code, 302)
        for path in ('/admin/', '/admin/accounts/user/', f'/admin/accounts/user/{self.user.pk}/change/',
                     '/admin/password_change/'):
            with self.subTest(path=path):
                self.assertEqual(browser.get(path).status_code, status.HTTP_403_FORBIDDEN)

        changed = browser.post(
            CHANGE_URL, {"current_password": STRONG, "new_password": STRONGER}, content_type='application/json'
        )
        self.assertEqual(changed.status_code, status.HTTP_200_OK)
        self.assertEqual(browser.get('/admin/').status_code, status.HTTP_200_OK)

    @override_settings(STORAGES=PLAIN_STORAGES)
    def test_admin_sign_out_is_allowed_while_flagged(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        browser = Client()
        browser.post(ADMIN_LOGIN_URL, {'username': 'new.mentor', 'password': STRONG, 'next': '/admin/'})
        self.assertEqual(browser.post('/admin/logout/').status_code, status.HTTP_200_OK)
        self.assertEqual(browser.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)


class SessionLifetimeTests(APITestCase):
    """No time limit of our own: a session ends on logout, deactivation or a password change."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG,
            full_name='Mentor One', role='MENTOR',
        )

    def api_login(self):
        response = self.client.post(LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response

    def test_no_custom_fixed_timeout_remains(self):
        import accounts.middleware
        self.assertFalse(hasattr(accounts.middleware, 'AbsoluteSessionTimeoutMiddleware'))
        self.assertFalse([m for m in settings.MIDDLEWARE if 'Timeout' in m])
        self.assertFalse(hasattr(settings, 'SESSION_ABSOLUTE_TIMEOUT_SECONDS'))
        self.assertFalse(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertFalse(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        # The longest lifetime browsers honour, i.e. no limit of our own.
        self.assertEqual(settings.SESSION_COOKIE_AGE, SESSION_LIFETIME)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')

    def test_login_issues_a_400_day_session(self):
        before = timezone.now()
        response = self.api_login()
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie['max-age'], SESSION_LIFETIME)
        session = Session.objects.get(session_key=cookie.value)
        self.assertGreaterEqual(session.expire_date, before + timedelta(seconds=SESSION_LIFETIME))

    def test_requests_do_not_resave_the_session(self):
        session_key = self.api_login().cookies[settings.SESSION_COOKIE_NAME].value
        expire_date = Session.objects.get(session_key=session_key).expire_date
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(Session.objects.get(session_key=session_key).expire_date, expire_date)


class ExistingSessionTests(APITestCase):
    """
    Every session issued before the lockout backend recorded Django's
    ModelBackend path, students' included. They must keep working, and
    deactivation must still end any session, whichever backend it records.
    """

    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user(email='kid@gmail.com', full_name='Kid', role='STUDENT')
        self.mentor = User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG, full_name='Mentor', role='MENTOR',
        )
        self.admin = User.objects.create_user(
            email='admin@eduport.com', username='admin1', password=STRONG, full_name='Admin', role='ADMIN',
        )

    def test_a_legacy_student_session_survives(self):
        self.client.force_login(self.student, backend=LEGACY_BACKEND)
        self.assertEqual(self.client.session[BACKEND_SESSION_KEY], LEGACY_BACKEND)
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'STUDENT')
        self.assertIn('student_profiles', response.data)

    def test_a_legacy_staff_session_survives(self):
        self.client.force_login(self.mentor, backend=LEGACY_BACKEND)
        self.assertEqual(self.client.get(STAFF_ONLY_URL).status_code, status.HTTP_200_OK)

    def test_google_sign_in_still_works_and_records_the_lockout_backend(self):
        Invitation.objects.create(
            email=self.student.email, role=InvitationRoleChoices.STUDENT, status=InvitationStatusChoices.ACCEPTED,
        )
        claims = {"email": self.student.email, "name": "Kid", "picture": None}
        with patch('accounts.views.verify_google_token', return_value=claims):
            response = self.client.post(GOOGLE_URL, {"credential": "stub-google-id-token"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'authenticated')
        self.assertTrue(response.data['csrf_token'])
        self.assertEqual(self.client.session[BACKEND_SESSION_KEY], SESSION_BACKEND)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['max-age'], SESSION_LIFETIME)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)

    def test_deactivation_ends_an_existing_session(self):
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        for backend in (SESSION_BACKEND, LEGACY_BACKEND):
            with self.subTest(backend=backend):
                User.objects.filter(pk=self.mentor.pk).update(is_active=True, deactivated_at=None)
                staff = APIClient()
                staff.force_login(self.mentor, backend=backend)
                self.assertEqual(staff.get(STAFF_ONLY_URL).status_code, status.HTTP_200_OK)

                response = admin_client.post(f'/api/team/{self.mentor.pk}/deactivate/', {}, format='json')
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(staff.get(STAFF_ONLY_URL).status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(staff.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)

    def test_an_inactive_student_session_is_refused(self):
        self.client.force_login(self.student, backend=LEGACY_BACKEND)
        User.objects.filter(pk=self.student.pk).update(is_active=False)
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)


class RedisIndependenceTests(APITestCase):
    """Nothing on the sign-in path talks to Redis; it serves Celery only."""

    def test_the_cache_is_local_memory(self):
        from django.core.cache import caches
        from django.core.cache.backends.locmem import LocMemCache
        self.assertIsInstance(caches['default'], LocMemCache)
        self.assertFalse(hasattr(settings, 'CACHE_URL'))

    def test_sign_in_works_while_redis_is_unreachable(self):
        cache.clear()
        User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG, full_name='Mentor', role='MENTOR',
        )
        refused = AssertionError('Redis was contacted')
        with patch('redis.connection.AbstractConnection.connect', side_effect=refused) as connect:
            bad = self.client.post(LOGIN_URL, {"username": "mentor1", "password": "bad"}, format='json')
            self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
            good = self.client.post(LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json')
            self.assertEqual(good.status_code, status.HTTP_200_OK)
            self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_200_OK)
            self.assertEqual(self.client.post(LOGOUT_URL).status_code, status.HTTP_200_OK)
        connect.assert_not_called()


class SettingsGuardTests(SimpleTestCase):
    def guard(self, **overrides):
        kwargs = dict(
            debug=False,
            session_cookie_secure=True,
            csrf_cookie_secure=True,
            allow_insecure_cookies=False,
            cors_allowed_origins=['https://hub.example.com'],
            csrf_trusted_origins=['https://hub.example.com'],
        )
        kwargs.update(overrides)
        return validate_cookie_and_origin_settings(**kwargs)

    def test_production_configuration_passes(self):
        self.guard()

    def test_debug_skips_every_check(self):
        self.guard(debug=True, session_cookie_secure=False, cors_allowed_origins=[], csrf_trusted_origins=[])

    def test_insecure_cookies_fail_closed(self):
        with self.assertRaises(ImproperlyConfigured):
            self.guard(session_cookie_secure=False)
        with self.assertRaises(ImproperlyConfigured):
            self.guard(csrf_cookie_secure=False)

    def test_insecure_cookies_need_the_explicit_opt_out(self):
        self.guard(
            session_cookie_secure=False, csrf_cookie_secure=False, allow_insecure_cookies=True,
            cors_allowed_origins=['http://localhost:3000', 'http://127.0.0.1:3001'],
            csrf_trusted_origins=['http://localhost:3000'],
        )

    def test_opt_out_is_refused_for_non_local_origins(self):
        # A development .env copied onto a real host must still fail closed.
        for origins in (['https://hub.example.com'], ['http://192.168.1.20:3000'], ['http://hub.example.com']):
            with self.subTest(origins=origins):
                with self.assertRaises(ImproperlyConfigured):
                    self.guard(
                        session_cookie_secure=False, csrf_cookie_secure=False, allow_insecure_cookies=True,
                        cors_allowed_origins=origins, csrf_trusted_origins=origins,
                    )

    def test_opt_out_is_irrelevant_once_cookies_are_secure(self):
        self.guard(allow_insecure_cookies=True)

    def test_empty_origin_lists_fail_closed(self):
        with self.assertRaises(ImproperlyConfigured):
            self.guard(cors_allowed_origins=[])
        with self.assertRaises(ImproperlyConfigured):
            self.guard(csrf_trusted_origins=[])


class DjangoAdminPasswordTests(APITestCase):
    """The Django admin must hash passwords; it used to save the raw text."""

    def setUp(self):
        self.root = User.objects.create_superuser(
            username='root', email='root@eduport.com', full_name='Root', password=STRONG
        )
        self.target = User.objects.create_user(
            email='tutor@eduport.com', username='tutor1', password=STRONG, full_name='Tutor One', role='TUTOR'
        )
        from django.test import Client
        self.admin_client = Client()
        self.admin_client.force_login(self.root)

    def test_change_form_password_is_read_only(self):
        from django.contrib.auth.forms import ReadOnlyPasswordHashField
        from accounts.admin import UserAdmin
        self.assertIsInstance(UserAdmin.form.base_fields['password'], ReadOnlyPasswordHashField)

    def test_set_password_view_stores_a_hash(self):
        from django.urls import reverse
        url = reverse('admin:auth_user_password_change', args=[self.target.pk])
        response = self.admin_client.post(url, {'password1': STRONGER, 'password2': STRONGER, 'usable_password': 'true'})
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(self.target.check_password(STRONGER))

    def test_add_view_hashes_and_flags_a_temporary_password(self):
        from django.urls import reverse
        response = self.admin_client.post(reverse('admin:accounts_user_add'), {
            'username': 'New.Mentor', 'email': 'new.mentor@eduport.com', 'full_name': 'New Mentor',
            'role': 'MENTOR', 'usable_password': 'true', 'password1': STRONGER, 'password2': STRONGER,
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context.get('errors'))
        created = User.objects.get(username='new.mentor')
        self.assertTrue(created.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(created.must_change_password)
        self.assertFalse(created.is_staff)

    def test_the_add_view_whitelists_students_only(self):
        # A student added here still gets the invitation Learn's Google sign-in
        # looks for; staff are no longer invited, so a mentor gets none.
        from django.urls import reverse
        for username, role in (('added.mentor', 'MENTOR'), ('added.parent', 'STUDENT')):
            response = self.admin_client.post(reverse('admin:accounts_user_add'), {
                'username': username, 'email': f'{username}@eduport.com', 'full_name': username.title(),
                'role': role, 'usable_password': 'true', 'password1': STRONGER, 'password2': STRONGER,
            })
            self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context.get('errors'))
        self.assertFalse(Invitation.objects.filter(email='added.mentor@eduport.com').exists())
        whitelist = Invitation.objects.get(email='added.parent@eduport.com')
        self.assertEqual((whitelist.role, whitelist.status), (InvitationRoleChoices.STUDENT, InvitationStatusChoices.ACCEPTED))


def admin_change_form_data(response):
    """POST data that resubmits an admin change form exactly as it was rendered."""
    from django.forms import CheckboxInput
    form = response.context['adminform'].form
    data = {}
    for name, field in form.fields.items():
        if field.disabled:
            continue
        value = form[name].value()
        widget = getattr(field.widget, 'widget', field.widget)  # RelatedFieldWidgetWrapper
        if hasattr(widget, 'decompress'):
            for index, part in enumerate(widget.decompress(value)):
                data[f'{name}_{index}'] = '' if part is None else part
        elif isinstance(widget, CheckboxInput):
            if value:
                data[name] = 'on'
        elif isinstance(value, (list, tuple)):
            data[name] = list(value)
        else:
            data[name] = '' if value is None else value
    return data


@override_settings(STORAGES=PLAIN_STORAGES)
class DjangoAdminStaffEmailTests(APITestCase):
    """The admin's user forms apply the Team API's staff email rule (accounts.team.staff_email_conflict)."""

    INVITED = 'That email has a student invitation. Withdraw the invitation first.'
    TAKEN = 'That email already belongs to an account.'

    def setUp(self):
        self.root = User.objects.create_superuser(
            username='root', email='root@eduport.com', full_name='Root', password=STRONG
        )
        self.mentor = User.objects.create_user(
            email='mentor1@eduport.com', username='mentor1', password=STRONG, full_name='Mentor One', role='MENTOR'
        )
        User.objects.create_user(
            email='tutor1@eduport.com', username='tutor1', password=STRONG, full_name='Tutor One', role='TUTOR'
        )
        self.parent = User.objects.create_user(
            email='parent@gmail.com', username='parent', full_name='Parent', role='STUDENT'
        )
        Invitation.objects.create(
            email='kid.parent@gmail.com', role=InvitationRoleChoices.STUDENT, status=InvitationStatusChoices.PENDING,
            extra_data={'student_code': 'EP900', 'full_name': 'Kid'},
        )
        Invitation.objects.create(
            email='onboarded.parent@gmail.com', role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.ACCEPTED,
        )
        self.browser = Client()
        self.browser.force_login(self.root)

    def change_email(self, account, email):
        url = f'/admin/accounts/user/{account.pk}/change/'
        data = admin_change_form_data(self.browser.get(url))
        data['email'] = email
        return self.browser.post(url, data)

    def add(self, username, role, email):
        return self.browser.post('/admin/accounts/user/add/', {
            'username': username, 'email': email, 'full_name': username.title(), 'role': role,
            'usable_password': 'true', 'password1': STRONGER, 'password2': STRONGER,
        })

    @staticmethod
    def email_errors(response):
        return response.context['adminform'].form.errors.get('email', [])

    def test_a_staff_email_cannot_take_a_student_invitation(self):
        for address in ('Kid.Parent@gmail.com', 'onboarded.parent@gmail.com'):
            with self.subTest(address=address):
                response = self.change_email(self.mentor, address)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.email_errors(response), [self.INVITED])
        self.assertEqual(User.objects.get(pk=self.mentor.pk).email, 'mentor1@eduport.com')

    def test_staff_emails_stay_unique_whatever_the_letter_case(self):
        for address in ('tutor1@eduport.com', 'Tutor1@Eduport.com', 'PARENT@gmail.com'):
            with self.subTest(address=address):
                response = self.change_email(self.mentor, address)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.email_errors(response), [self.TAKEN], 'one clear error')
        self.assertEqual(User.objects.get(pk=self.mentor.pk).email, 'mentor1@eduport.com')

    def test_a_valid_staff_email_change_keeps_the_username_and_password(self):
        response = self.change_email(self.mentor, 'mentor.new@eduport.com')
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and self.email_errors(response))
        mentor = User.objects.get(pk=self.mentor.pk)
        self.assertEqual((mentor.email, mentor.username), ('mentor.new@eduport.com', 'mentor1'))
        self.assertTrue(mentor.check_password(STRONG))
        # Its own address in other letter case is no conflict.
        self.assertEqual(self.change_email(mentor, 'Mentor.New@Eduport.com').status_code, 302)
        login = APIClient().post(LOGIN_URL, {'username': 'mentor1', 'password': STRONG}, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_student_accounts_are_edited_as_before(self):
        # The rule is for staff: a parent account may still take an invited address.
        response = self.change_email(self.parent, 'kid.parent@gmail.com')
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and self.email_errors(response))
        self.assertEqual(User.objects.get(pk=self.parent.pk).email, 'kid.parent@gmail.com')

    def test_new_staff_accounts_follow_the_same_rule(self):
        for email, error in (('kid.parent@gmail.com', self.INVITED), ('Tutor1@Eduport.com', self.TAKEN)):
            with self.subTest(email=email):
                refused = self.add('new.mentor', 'MENTOR', email)
                self.assertEqual(refused.status_code, 200)
                self.assertEqual(self.email_errors(refused), [error])
        self.assertFalse(User.objects.filter(username='new.mentor').exists())
        self.assertEqual(self.add('new.mentor', 'MENTOR', 'new.mentor@eduport.com').status_code, 302)
        # A student account may still be added on an invited address.
        self.assertEqual(self.add('new.parent', 'STUDENT', 'kid.parent@gmail.com').status_code, 302)


@override_settings(STORAGES=PLAIN_STORAGES)
class DjangoAdminLoginTests(APITestCase):
    """The Django admin login shares the lockout and the failure audit with the API."""

    def setUp(self):
        cache.clear()
        self.root = User.objects.create_superuser(
            username='root', email='root@eduport.com', full_name='Root', password=STRONG
        )
        self.browser = Client()

    def admin_login(self, username, password):
        return self.browser.post(ADMIN_LOGIN_URL, {'username': username, 'password': password, 'next': '/admin/'})

    def api_login(self, username, password):
        return APIClient().post(LOGIN_URL, {"username": username, "password": password}, format='json')

    def test_admin_failures_lock_the_api_too(self):
        for _ in range(5):
            # A refused admin login re-renders the form (200); success redirects.
            self.assertEqual(self.admin_login('root', 'bad').status_code, 200)
        self.root.refresh_from_db()
        self.assertIsNotNone(self.root.locked_until)
        self.assertEqual(self.api_login('root', STRONG).json(), LOGIN_FAILED_RESPONSE)
        self.assertEqual(self.admin_login('root', STRONG).status_code, 200)
        self.assertEqual(self.browser.get('/admin/').status_code, 302)
        rows = ActivityLog.objects.filter(action='user.sign_in_failed', actor=self.root).order_by('created_at')
        self.assertEqual([r.context['path'] for r in rows], [ADMIN_LOGIN_URL] * 5 + [LOGIN_URL, ADMIN_LOGIN_URL])

    def test_api_failures_lock_the_admin_too(self):
        for _ in range(5):
            self.api_login('root', 'bad')
        self.assertEqual(self.admin_login('root', STRONG).status_code, 200)
        self.assertEqual(self.browser.get('/admin/').status_code, 302)

    def test_admin_success_resets_the_count(self):
        for _ in range(4):
            self.admin_login('root', 'bad')
        self.assertEqual(self.admin_login('root', STRONG).status_code, 302)
        self.root.refresh_from_db()
        self.assertEqual(self.root.failed_login_count, 0)
        self.assertEqual(self.browser.get('/admin/').status_code, 200)

    def test_model_backend_is_never_asked_to_check_a_password(self):
        self.assertEqual(settings.AUTHENTICATION_BACKENDS, [SESSION_BACKEND, LEGACY_BACKEND])
        User.objects.filter(pk=self.root.pk).update(
            failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=5)
        )
        with patch('django.contrib.auth.backends.ModelBackend.authenticate') as legacy:
            self.assertIsNone(authenticate(None, username='root', password=STRONG))
            self.assertIsNone(authenticate(None, username='root', password='bad'))
            self.assertIsNone(authenticate(None, username='nobody', password=STRONG))
        legacy.assert_not_called()

    def test_ordinary_staff_do_not_get_the_admin(self):
        mentor = User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG, full_name='Mentor', role='MENTOR',
        )
        self.assertFalse(mentor.is_staff)
        self.assertEqual(self.admin_login('mentor1', STRONG).status_code, 200)
        self.assertEqual(self.browser.get('/admin/').status_code, 302)

    def test_an_administrator_unlocks_an_account_and_it_is_audited(self):
        target = User.objects.create_user(
            email='tutor@eduport.com', username='tutor1', password=STRONG, full_name='Tutor', role='TUTOR',
            failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=10),
        )
        locked_until = User.objects.get(pk=target.pk).locked_until
        self.assertEqual(self.api_login('tutor1', STRONG).json(), LOGIN_FAILED_RESPONSE)

        self.browser.force_login(self.root)
        url = f'/admin/accounts/user/{target.pk}/change/'
        page = self.browser.get(url)
        self.assertContains(page, 'name="failed_login_count"')
        self.assertContains(page, 'name="locked_until_0"')
        data = admin_change_form_data(page)
        data.update({'failed_login_count': 0, 'locked_until_0': '', 'locked_until_1': ''})
        saved = self.browser.post(url, data)
        self.assertEqual(saved.status_code, 302, getattr(saved, 'context', None) and saved.context['adminform'].form.errors)

        target.refresh_from_db()
        self.assertEqual((target.failed_login_count, target.locked_until), (0, None))
        row = ActivityLog.objects.get(action='user.unlock')
        self.assertEqual(row.actor, self.root)
        self.assertEqual(row.entity_id, str(target.pk))
        self.assertEqual(row.changes['failed_login_count'], {'old': 5, 'new': 0})
        self.assertEqual(row.changes['locked_until'], {'old': locked_until.isoformat(), 'new': None})
        self.assertEqual(self.api_login('tutor1', STRONG).status_code, status.HTTP_200_OK)


class ConcurrentLockoutTests(TransactionTestCase):
    """Parallel wrong passwords cannot slip extra guesses past the threshold."""

    def test_parallel_attempts_at_the_threshold_get_one_real_check(self):
        user = User.objects.create_user(
            email='racer@eduport.com', username='racer', password=STRONG, full_name='Racer', role='MENTOR',
            failed_login_count=settings.LOGIN_MAX_FAILURES - 1,
        )
        workers = 6
        start = threading.Barrier(workers)

        def attempt():
            try:
                start.wait()
                authenticate(None, username='racer', password='wrong-guess')
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        user.refresh_from_db()
        self.assertEqual(user.failed_login_count, settings.LOGIN_MAX_FAILURES)
        self.assertIsNotNone(user.locked_until)
        # One attempt reached the threshold; every other one found the lock.
        self.assertEqual(Counter(failure_reasons(user)), Counter({'invalid_password': 1, 'locked': workers - 1}))


class StaffFlagMigrationTests(APITestCase):
    def test_reset_keeps_is_staff_for_superusers_only(self):
        import importlib
        from django.apps import apps as global_apps
        legacy = User.objects.create_user(
            email='legacy@eduport.com', password=STRONG, full_name='Legacy', role='MENTOR', is_staff=True
        )
        root = User.objects.create_superuser(username='root', email='r@eduport.com', full_name='R', password=STRONG)
        migration = importlib.import_module('accounts.migrations.0005_reset_non_superuser_is_staff')
        migration.reset_is_staff(global_apps, None)
        legacy.refresh_from_db()
        root.refresh_from_db()
        self.assertFalse(legacy.is_staff)
        self.assertTrue(root.is_staff)


class SessionCleanupTaskTests(APITestCase):
    def test_beat_schedule_points_at_the_registered_task(self):
        from accounts.tasks import clear_expired_sessions
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE['clear-expired-sessions']['task'], clear_expired_sessions.name
        )

    def test_task_deletes_only_expired_sessions(self):
        from datetime import timedelta
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from accounts.tasks import clear_expired_sessions
        Session.objects.create(session_key='expired' * 4, session_data='', expire_date=timezone.now() - timedelta(days=1))
        Session.objects.create(session_key='current' * 4, session_data='', expire_date=timezone.now() + timedelta(days=1))
        clear_expired_sessions()
        self.assertEqual(list(Session.objects.values_list('session_key', flat=True)), ['current' * 4])
