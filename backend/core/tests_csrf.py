"""
CSRF is enforced on every state-changing endpoint.

The suite's other tests use ``force_authenticate`` (which bypasses the check),
so this module drives a real session through ``APIClient(enforce_csrf_checks=
True)``: without the token every write is refused with 403, with the token
each endpoint proceeds to its own validation or permission answer.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

User = get_user_model()

STRONG = 'Correct-Horse-Battery-9'
CSRF_URL = '/api/auth/csrf/'
LOGIN_URL = '/api/auth/login/'


class CsrfEnforcementTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email='csrf_admin@eduport.com', username='csrf_admin', password=STRONG,
            full_name='CSRF Admin', role='ADMIN',
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(self.client.login(username='csrf_admin', password=STRONG))

    def token(self):
        self.client.get(CSRF_URL)
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def write_endpoints(self):
        # One representative state-changing call per module that used to opt
        # out of CSRF. Bodies are empty on purpose: the point is which answer
        # comes first, the CSRF refusal or the view's own validation.
        return [
            ('patch', f'/api/users/{self.admin.id}/', {}),
            ('post', f'/api/users/{uuid.uuid4()}/status/', {}),
            ('put', '/api/students/', {}),
            ('post', '/api/students/reassign/', {}),
            ('post', '/api/sessions/', {}),
            ('post', '/api/invitations/', {}),
            ('post', '/api/exams/', {}),
            ('post', '/api/homework/', {}),
            ('post', '/api/auth/select-student/', {}),
            ('post', '/api/auth/change-password/', {}),
        ]

    def test_writes_without_a_token_are_refused(self):
        for method, url, body in self.write_endpoints():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, body, format='json')
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertIn('CSRF', str(response.data.get('detail', '')))

    def test_writes_with_a_token_reach_the_view(self):
        token = self.token()
        for method, url, body in self.write_endpoints():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, body, format='json', HTTP_X_CSRFTOKEN=token)
                self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_logout_requires_a_token(self):
        self.assertEqual(self.client.post('/api/auth/logout/').status_code, status.HTTP_403_FORBIDDEN)
        token = self.token()
        self.assertEqual(
            self.client.post('/api/auth/logout/', HTTP_X_CSRFTOKEN=token).status_code,
            status.HTTP_200_OK,
        )

    def test_reads_need_no_token(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/students/').status_code, status.HTTP_200_OK)


class LoginCsrfTests(APITestCase):
    """Login CSRF: the password and Google login POSTs need the token too."""

    def setUp(self):
        User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG,
            full_name='Mentor One', role='MENTOR',
        )
        self.client = APIClient(enforce_csrf_checks=True)

    def test_login_without_token_is_refused_with_json(self):
        response = self.client.post(LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['error'], 'CSRF_FAILED')
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_login_with_token_succeeds(self):
        self.client.get(CSRF_URL)
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post(
            LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json', HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_google_login_without_token_is_refused(self):
        response = self.client.post('/api/auth/google/', {"credential": "x"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['error'], 'CSRF_FAILED')


class BodyTokenTests(APITestCase):
    """
    The SPAs send the token from the JSON body, never from document.cookie
    (unreadable when the API is on another host). Prove that path works and
    that the token handed out by login replaces the rotated one.
    """

    def setUp(self):
        User.objects.create_user(
            email='mentor@eduport.com', username='mentor1', password=STRONG,
            full_name='Mentor One', role='MENTOR',
        )
        self.client = APIClient(enforce_csrf_checks=True)

    def test_token_from_the_body_authorises_login_and_the_login_token_the_next_write(self):
        before = self.client.get(CSRF_URL).data['csrf_token']
        login = self.client.post(
            LOGIN_URL, {"username": "mentor1", "password": STRONG}, format='json', HTTP_X_CSRFTOKEN=before
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        after = login.data['csrf_token']

        # login() rotated the secret: the pre-login token no longer matches.
        stale = self.client.post('/api/auth/logout/', HTTP_X_CSRFTOKEN=before)
        self.assertEqual(stale.status_code, status.HTTP_403_FORBIDDEN)
        fresh = self.client.post('/api/auth/logout/', HTTP_X_CSRFTOKEN=after)
        self.assertEqual(fresh.status_code, status.HTTP_200_OK)
