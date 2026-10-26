"""
Team Management API tests (accounts/team.py): who may call it, staff-only
targets, creation with a temporary password and the forced change, details and
role changes, activation, password reset, the approved permission catalogue,
the escalation guards and the audit trail.
"""
import json
import threading
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from invitations.models import Invitation, InvitationRoleChoices, InvitationStatusChoices
from students.models import StatusChoices, Student

User = get_user_model()

TEAM_URL = '/api/team/'
CATALOGUE_URL = '/api/team/permissions/'
CSRF_URL = '/api/auth/csrf/'
LOGIN_URL = '/api/auth/login/'
GOOGLE_URL = '/api/auth/google/'
ME_URL = '/api/auth/me/'
CHANGE_URL = '/api/auth/change-password/'
STUDENTS_URL = '/api/students/'

STRONG = 'Correct-Horse-Battery-9'
TEMPORARY = 'Temporary-Pass-2026!'
NEW_TEMPORARY = 'Fresh-Start-Secret-77'

# Many accounts are created per test; the real hasher is covered by tests_auth.
FAST_HASHING = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def member_url(account, suffix=''):
    return f'{TEAM_URL}{account.pk}/{suffix}'


def view_team_permission():
    return Permission.objects.get(content_type__app_label='accounts', codename='view_team')


def call(client, method, url, body=None):
    if method == 'get':
        return client.get(url)
    return getattr(client, method)(url, body or {}, format='json')


def every_endpoint(account):
    """(method, url, body) for each Team endpoint aimed at ``account``."""
    return [
        ('get', member_url(account), None),
        ('patch', member_url(account), {'full_name': 'Changed'}),
        ('post', member_url(account, 'deactivate/'), {}),
        ('post', member_url(account, 'reactivate/'), {}),
        ('post', member_url(account, 'reset-password/'), {'temporary_password': NEW_TEMPORARY}),
        ('put', member_url(account, 'permissions/'), {'permissions': ['accounts.view_team']}),
    ]


@FAST_HASHING
class TeamTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.root = User.objects.create_superuser(
            username='root', email='root@eduport.com', full_name='Root', password=STRONG
        )
        self.admin = self.make('admin1', 'ADMIN')
        self.other_admin = self.make('admin2', 'ADMIN')
        self.mentor = self.make('mentor1', 'MENTOR')
        self.tutor = self.make('tutor1', 'TUTOR')
        self.parent = self.make('parent', 'STUDENT')
        self.client.force_authenticate(self.admin)

    def make(self, username, role, **extra):
        return User.objects.create_user(
            email=f'{username}@eduport.com', username=username, password=STRONG,
            full_name=username.title(), role=role, **extra,
        )

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def create_payload(self, **overrides):
        payload = {
            'username': 'new.mentor', 'email': 'new.mentor@eduport.com', 'full_name': 'New Mentor',
            'role': 'MENTOR', 'temporary_password': TEMPORARY,
        }
        payload.update(overrides)
        return payload

    def assert_refused(self, response, http_status, error):
        self.assertEqual((response.status_code, response.json().get('error')), (http_status, error))

    def assert_no_secret_logged(self, *secrets):
        for row in ActivityLog.objects.all():
            blob = json.dumps([row.changes, row.context])
            for secret in secrets:
                self.assertNotIn(secret, blob)


class TeamAccessTests(TeamTestCase):
    def test_only_team_managers_get_in(self):
        self.assertEqual(APIClient().get(TEAM_URL).status_code, status.HTTP_403_FORBIDDEN)
        calls = [('get', TEAM_URL, None), ('post', TEAM_URL, self.create_payload()), ('get', CATALOGUE_URL, None)]
        calls += every_endpoint(self.tutor)
        for caller in (self.mentor, self.parent):
            client = self.as_user(caller)
            for method, url, body in calls:
                with self.subTest(caller=caller.username, method=method, url=url):
                    self.assertEqual(call(client, method, url, body).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(username='new.mentor').exists())
        for manager in (self.admin, self.root):
            self.assertEqual(self.as_user(manager).get(TEAM_URL).status_code, status.HTTP_200_OK)

    def test_the_directory_lists_staff_only(self):
        usernames = {row['username'] for row in self.client.get(TEAM_URL).json()}
        self.assertEqual(usernames, {'root', 'admin1', 'admin2', 'mentor1', 'tutor1'})

    def test_filters_and_search(self):
        self.assertEqual([r['username'] for r in self.client.get(TEAM_URL, {'role': 'mentor'}).json()], ['mentor1'])
        User.objects.filter(pk=self.tutor.pk).update(is_active=False, deactivated_at=timezone.now())
        self.assertEqual([r['username'] for r in self.client.get(TEAM_URL, {'status': 'deactivated'}).json()], ['tutor1'])
        self.assertNotIn('tutor1', [r['username'] for r in self.client.get(TEAM_URL, {'status': 'active'}).json()])
        self.assertEqual([r['username'] for r in self.client.get(TEAM_URL, {'q': 'TUTOR'}).json()], ['tutor1'])
        for params in ({'role': 'student'}, {'status': 'gone'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(TEAM_URL, params).status_code, status.HTTP_400_BAD_REQUEST)

    def test_paging_is_opt_in(self):
        body = self.client.get(TEAM_URL, {'page': 1, 'page_size': 2}).json()
        self.assertEqual((body['count'], body['page'], body['page_size'], len(body['results'])), (5, 1, 2, 2))

    def test_responses_never_carry_password_hashes(self):
        for url in (TEAM_URL, member_url(self.mentor)):
            content = self.client.get(url).content.decode()
            for account in User.objects.all():
                self.assertNotIn(account.password, content)
        member = self.client.get(member_url(self.mentor)).json()
        self.assertNotIn('password', member)
        self.assertTrue(member['has_password'])

    def test_student_accounts_are_not_found_and_stay_untouched(self):
        before = User.objects.get(pk=self.parent.pk)
        for manager in (self.admin, self.root):
            client = self.as_user(manager)
            for method, url, body in every_endpoint(self.parent):
                with self.subTest(manager=manager.username, method=method, url=url):
                    self.assert_refused(call(client, method, url, body), status.HTTP_404_NOT_FOUND, 'NOT_FOUND')
        after = User.objects.get(pk=self.parent.pk)
        for field in ('password', 'role', 'is_active', 'full_name', 'username', 'must_change_password'):
            self.assertEqual(getattr(after, field), getattr(before, field))
        self.assertFalse(after.user_permissions.exists())

    def test_view_team_grants_read_only_access(self):
        self.mentor.user_permissions.add(view_team_permission())
        holder = self.as_user(User.objects.get(pk=self.mentor.pk))
        listing = holder.get(TEAM_URL)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        for hidden in ('must_change_password', 'has_password', 'locked_until', 'permissions',
                       'deactivation_reason', 'last_login', 'is_superuser', 'invited_by'):
            self.assertNotIn(hidden, listing.json()[0])
        self.assertEqual(holder.get(member_url(self.tutor)).status_code, status.HTTP_200_OK)
        for method, url, body in [('post', TEAM_URL, self.create_payload()), ('get', CATALOGUE_URL, None)] + every_endpoint(self.tutor)[1:]:
            with self.subTest(method=method, url=url):
                self.assertEqual(call(holder, method, url, body).status_code, status.HTTP_403_FORBIDDEN)

    def test_a_student_holding_view_team_still_gets_nothing(self):
        self.parent.user_permissions.add(view_team_permission())
        self.assertEqual(self.as_user(User.objects.get(pk=self.parent.pk)).get(TEAM_URL).status_code, 403)


class TeamCreateTests(TeamTestCase):
    def test_an_admin_creates_a_mentor_holding_a_temporary_password(self):
        response = self.client.post(TEAM_URL, self.create_payload(email='New.Mentor@Eduport.com'), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn(TEMPORARY, response.content.decode())
        body = response.json()
        self.assertNotIn('temporary_password', body)
        self.assertEqual((body['username'], body['email'], body['role']), ('new.mentor', 'new.mentor@eduport.com', 'MENTOR'))
        self.assertTrue(body['must_change_password'])
        self.assertTrue(body['has_password'])

        created = User.objects.get(username='new.mentor')
        self.assertTrue(created.check_password(TEMPORARY))
        self.assertTrue(created.must_change_password)
        self.assertFalse(created.is_staff or created.is_superuser)
        self.assertEqual(created.invited_by, self.admin)
        self.assertFalse(created.user_permissions.exists())

        row = ActivityLog.objects.get(action='staff.create')
        self.assertEqual((row.actor, row.entity_id, row.context['role']), (self.admin, str(created.pk), 'MENTOR'))
        self.assert_no_secret_logged(TEMPORARY)

    def test_the_temporary_password_must_be_changed_before_anything_else(self):
        self.client.post(TEAM_URL, self.create_payload(), format='json')
        browser = APIClient()
        login = browser.post(LOGIN_URL, {'username': 'new.mentor', 'password': TEMPORARY}, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertTrue(login.json()['must_change_password'])
        self.assert_refused(browser.get(STUDENTS_URL), status.HTTP_403_FORBIDDEN, 'PASSWORD_CHANGE_REQUIRED')
        changed = browser.post(
            CHANGE_URL, {'current_password': TEMPORARY, 'new_password': 'My-Own-Secret-Phrase-1'}, format='json'
        )
        self.assertEqual(changed.status_code, status.HTTP_200_OK)
        self.assertEqual(browser.get(STUDENTS_URL).status_code, status.HTTP_200_OK)

    def test_new_accounts_cannot_sign_in_with_google(self):
        self.client.post(TEAM_URL, self.create_payload(), format='json')
        claims = {'email': 'new.mentor@eduport.com', 'name': 'New Mentor', 'picture': None}
        with patch('accounts.views.verify_google_token', return_value=claims):
            response = APIClient().post(GOOGLE_URL, {'credential': 'stub-google-id-token'}, format='json')
        self.assert_refused(response, status.HTTP_403_FORBIDDEN, 'ACCESS_RESTRICTED')

    def test_a_legacy_staff_invitation_does_not_block_team(self):
        # Staff invitations are retired. One left over from before -- pending or
        # expired -- no longer stands in the way, and is left exactly as it was.
        pending = Invitation.objects.create(
            email='new.mentor@eduport.com', role=InvitationRoleChoices.MENTOR,
            status=InvitationStatusChoices.PENDING, extra_data={'full_name': 'New Mentor'},
        )
        expired = Invitation.objects.create(
            email='new.tutor@eduport.com', role=InvitationRoleChoices.TUTOR, status=InvitationStatusChoices.EXPIRED,
        )
        for payload in (
            self.create_payload(),
            self.create_payload(username='new.tutor', email='New.Tutor@eduport.com', role='TUTOR'),
        ):
            with self.subTest(email=payload['email']):
                response = self.client.post(TEAM_URL, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        for invitation, state in ((pending, InvitationStatusChoices.PENDING), (expired, InvitationStatusChoices.EXPIRED)):
            invitation.refresh_from_db()
            self.assertEqual(invitation.status, state)
        # ...and the leftover invitation never lets the new account in through Google.
        claims = {'email': 'new.mentor@eduport.com', 'name': 'New Mentor', 'picture': None}
        with patch('accounts.views.verify_google_token', return_value=claims):
            response = APIClient().post(GOOGLE_URL, {'credential': 'stub-google-id-token'}, format='json')
        self.assert_refused(response, status.HTTP_403_FORBIDDEN, 'GOOGLE_SIGN_IN_STUDENTS_ONLY')

    def test_invalid_requests_create_nothing(self):
        Invitation.objects.create(
            email='parent.of.kid@gmail.com', role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING, extra_data={'student_code': 'EP001', 'full_name': 'Kid'},
        )
        cases = [
            ({'temporary_password': 'short'}, 'PASSWORD_POLICY'),
            ({'temporary_password': '1234567'}, 'PASSWORD_POLICY'),
            ({'username': 'MENTOR1'}, 'USERNAME_TAKEN'),
            ({'username': 'bad name!'}, 'INVALID_INPUT'),
            ({'email': 'Mentor1@Eduport.com'}, 'EMAIL_IN_USE'),
            # A staff account would block a parent's student invitation for good.
            ({'email': 'Parent.Of.Kid@gmail.com'}, 'EMAIL_IN_USE'),
            ({'email': 'not-an-email'}, 'INVALID_INPUT'),
            ({'role': 'STUDENT'}, 'INVALID_ROLE'),
            ({'role': 'OWNER'}, 'INVALID_ROLE'),
            ({'full_name': '   '}, 'INVALID_INPUT'),
            ({'mobile_number': '1' * 21}, 'INVALID_INPUT'),
            ({'is_superuser': True}, 'UNKNOWN_FIELDS'),
            ({'is_staff': True}, 'UNKNOWN_FIELDS'),
            ({'groups': [1]}, 'UNKNOWN_FIELDS'),
            ({'password': TEMPORARY}, 'UNKNOWN_FIELDS'),
        ]
        before = User.objects.count()
        for overrides, error in cases:
            with self.subTest(overrides=overrides):
                response = self.client.post(TEAM_URL, self.create_payload(**overrides), format='json')
                self.assert_refused(response, status.HTTP_400_BAD_REQUEST, error)
        for missing in ('username', 'email', 'full_name', 'role', 'temporary_password'):
            with self.subTest(missing=missing):
                payload = self.create_payload()
                del payload[missing]
                self.assert_refused(self.client.post(TEAM_URL, payload, format='json'), 400, 'INVALID_INPUT')
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(ActivityLog.objects.filter(action='staff.create').exists())

    def test_password_policy_errors_explain_without_echoing(self):
        response = self.client.post(TEAM_URL, self.create_payload(temporary_password='short'), format='json')
        self.assertTrue(response.json()['details'])
        self.assertNotIn('"short"', response.content.decode())

    def test_only_superusers_create_admins(self):
        refused = self.client.post(TEAM_URL, self.create_payload(role='ADMIN'), format='json')
        self.assert_refused(refused, status.HTTP_403_FORBIDDEN, 'SUPERUSER_REQUIRED')
        self.assertFalse(User.objects.filter(username='new.mentor').exists())
        created = self.as_user(self.root).post(TEAM_URL, self.create_payload(role='admin'), format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        account = User.objects.get(username='new.mentor')
        self.assertEqual(account.role, 'ADMIN')
        self.assertFalse(account.is_staff or account.is_superuser)


class TeamUpdateTests(TeamTestCase):
    def test_details_are_updated_and_audited(self):
        response = self.client.patch(
            member_url(self.mentor),
            {'full_name': 'Mentor Prime', 'mobile_number': '+911234567890', 'username': 'Mentor.Prime'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mentor.refresh_from_db()
        self.assertEqual(
            (self.mentor.full_name, self.mentor.mobile_number, self.mentor.username),
            ('Mentor Prime', '+911234567890', 'mentor.prime'),
        )
        row = ActivityLog.objects.get(action='user.update_details')
        self.assertEqual(row.actor, self.admin)
        self.assertEqual(row.changes['username'], {'old': 'mentor1', 'new': 'mentor.prime'})
        self.assertEqual(row.changes['full_name'], {'old': 'Mentor1', 'new': 'Mentor Prime'})
        self.assertFalse(ActivityLog.objects.filter(action='user.role_change').exists())
        # The renamed account signs in under its new username.
        login = APIClient().post(LOGIN_URL, {'username': 'mentor.prime', 'password': STRONG}, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_usernames_stay_unique_and_empty_updates_are_refused(self):
        self.assert_refused(self.client.patch(member_url(self.mentor), {'username': 'TUTOR1'}, format='json'),
                            400, 'USERNAME_TAKEN')
        self.assert_refused(self.client.patch(member_url(self.mentor), {}, format='json'), 400, 'INVALID_INPUT')

    def test_flags_and_passwords_cannot_be_set_here(self):
        for field, value in (
            ('is_superuser', True), ('is_staff', True), ('is_active', False),
            ('groups', [1]), ('user_permissions', [1]), ('must_change_password', False),
            ('password', STRONG), ('locked_until', None), ('failed_login_count', 0),
        ):
            with self.subTest(field=field):
                response = self.client.patch(member_url(self.mentor), {field: value}, format='json')
                self.assert_refused(response, status.HTTP_400_BAD_REQUEST, 'UNKNOWN_FIELDS')
        self.mentor.refresh_from_db()
        self.assertEqual(self.mentor.email, 'mentor1@eduport.com')
        self.assertFalse(self.mentor.is_superuser or self.mentor.is_staff)
        self.assertTrue(self.mentor.is_active)

    def change_email(self, account, email, client=None):
        return (client or self.client).patch(member_url(account), {'email': email}, format='json')

    def test_an_email_change_keeps_the_username_password_and_session(self):
        browser = APIClient()
        login = {'username': 'mentor1', 'password': STRONG}
        self.assertEqual(browser.post(LOGIN_URL, login, format='json').status_code, status.HTTP_200_OK)

        response = self.change_email(self.mentor, '  Mentor.New@Eduport.COM ')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['email'], 'mentor.new@eduport.com')
        mentor = User.objects.get(pk=self.mentor.pk)
        self.assertEqual((mentor.email, mentor.username), ('mentor.new@eduport.com', 'mentor1'))
        self.assertTrue(mentor.check_password(STRONG))
        self.assertFalse(mentor.must_change_password)

        # The session already open stays open; the unchanged username still signs in.
        self.assertEqual(browser.get(ME_URL).status_code, status.HTTP_200_OK)
        self.assertEqual(APIClient().post(LOGIN_URL, login, format='json').status_code, status.HTTP_200_OK)
        row = ActivityLog.objects.get(action='user.update_details', entity_id=str(mentor.pk))
        self.assertEqual(row.changes, {'email': {'old': 'mentor1@eduport.com', 'new': 'mentor.new@eduport.com'}})

    def test_an_email_change_is_checked_like_a_new_account(self):
        Invitation.objects.create(
            email='kid.parent@gmail.com', role=InvitationRoleChoices.STUDENT, status=InvitationStatusChoices.PENDING,
            extra_data={'student_code': 'EP777', 'full_name': 'Kid'},
        )
        Invitation.objects.create(
            email='onboarded.parent@gmail.com', role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.ACCEPTED,
        )
        cases = [
            ('', 'INVALID_INPUT'),
            ('not-an-email', 'INVALID_INPUT'),
            ('a' * 250 + '@eduport.com', 'INVALID_INPUT'),
            (42, 'INVALID_INPUT'),
            ('Tutor1@Eduport.com', 'EMAIL_IN_USE'),          # another staff account, any case
            ('parent@eduport.com', 'EMAIL_IN_USE'),          # a student (parent) account
            ('Kid.Parent@gmail.com', 'EMAIL_IN_USE'),        # a pending student invitation
            ('onboarded.parent@gmail.com', 'EMAIL_IN_USE'),  # an accepted one
        ]
        for value, error in cases:
            with self.subTest(value=value):
                response = self.change_email(self.mentor, value)
                self.assert_refused(response, status.HTTP_400_BAD_REQUEST, error)
                if error == 'INVALID_INPUT':
                    self.assertEqual(response.json()['fields'], ['email'])
        self.assertEqual(User.objects.get(pk=self.mentor.pk).email, 'mentor1@eduport.com')
        self.assertFalse(ActivityLog.objects.filter(action='user.update_details').exists())

    def test_the_own_address_in_other_letter_case_is_no_conflict(self):
        response = self.change_email(self.mentor, 'MENTOR1@Eduport.com')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.get(pk=self.mentor.pk).email, 'mentor1@eduport.com')
        self.assertFalse(ActivityLog.objects.filter(action='user.update_details').exists())

    def test_a_legacy_staff_invitation_neither_blocks_nor_opens_google(self):
        # Left over from Google-era staff onboarding: a pending staff invitation
        # for the new address, and the accepted one for the old address.
        pending = Invitation.objects.create(
            email='old.invite@eduport.com', role=InvitationRoleChoices.MENTOR,
            status=InvitationStatusChoices.PENDING, extra_data={'full_name': 'Old Invite'},
        )
        Invitation.objects.create(
            email='mentor1@eduport.com', role=InvitationRoleChoices.MENTOR, status=InvitationStatusChoices.ACCEPTED,
        )
        self.assertEqual(self.change_email(self.mentor, 'old.invite@eduport.com').status_code, status.HTTP_200_OK)
        pending.refresh_from_db()
        self.assertEqual((pending.status, pending.role), (InvitationStatusChoices.PENDING, InvitationRoleChoices.MENTOR))

        for address in ('old.invite@eduport.com', 'mentor1@eduport.com'):
            with self.subTest(address=address):
                claims = {'email': address, 'name': 'Someone', 'picture': None}
                with patch('accounts.views.verify_google_token', return_value=claims):
                    response = APIClient().post(GOOGLE_URL, {'credential': 'stub-google-id-token'}, format='json')
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # No second account for either address, and the mentor is still the one account.
        self.assertEqual(
            list(User.objects.filter(email__in=['old.invite@eduport.com', 'mentor1@eduport.com']).values_list('pk', flat=True)),
            [self.mentor.pk],
        )

    def test_who_may_change_an_email(self):
        holder = self.make('reader', 'MENTOR')
        holder.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='view_team'))
        refused = [
            (self.as_user(self.mentor), self.tutor, status.HTTP_403_FORBIDDEN),
            (self.as_user(User.objects.get(pk=holder.pk)), self.tutor, status.HTTP_403_FORBIDDEN),
            (APIClient(), self.tutor, status.HTTP_403_FORBIDDEN),
            (self.client, self.admin, status.HTTP_403_FORBIDDEN),        # their own account
            (self.client, self.other_admin, status.HTTP_403_FORBIDDEN),  # an admin: superusers only
            (self.client, self.parent, status.HTTP_404_NOT_FOUND),       # not a staff account
        ]
        for client, account, http_status in refused:
            with self.subTest(account=account.username, status=http_status):
                before = User.objects.get(pk=account.pk).email
                self.assertEqual(self.change_email(account, 'someone.new@eduport.com', client).status_code, http_status)
                self.assertEqual(User.objects.get(pk=account.pk).email, before)
        allowed = self.change_email(self.other_admin, 'admin2.new@eduport.com', self.as_user(self.root))
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.get(pk=self.other_admin.pk).email, 'admin2.new@eduport.com')

    def test_a_mentor_becomes_a_tutor_and_it_is_audited(self):
        response = self.client.patch(member_url(self.mentor), {'role': 'tutor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mentor.refresh_from_db()
        self.assertEqual(self.mentor.role, 'TUTOR')
        row = ActivityLog.objects.get(action='user.role_change')
        self.assertEqual(row.changes, {'role': {'old': 'MENTOR', 'new': 'TUTOR'}})

    def test_nobody_becomes_a_student(self):
        self.assert_refused(self.client.patch(member_url(self.mentor), {'role': 'STUDENT'}, format='json'),
                            400, 'INVALID_ROLE')
        self.mentor.refresh_from_db()
        self.assertEqual(self.mentor.role, 'MENTOR')

    def test_a_role_change_waits_for_the_handover(self):
        Student.objects.create(
            profile=self.parent, student_code='TM001', full_name='Kid',
            mentor=self.mentor, tutor=self.tutor, status=StatusChoices.ACTIVE,
        )
        response = self.client.patch(member_url(self.mentor), {'role': 'TUTOR'}, format='json')
        self.assert_refused(response, status.HTTP_409_CONFLICT, 'HANDOVER_REQUIRED')
        self.mentor.refresh_from_db()
        self.assertEqual(self.mentor.role, 'MENTOR')

    def test_only_superusers_promote_demote_or_edit_admins(self):
        for account, body in (
            (self.mentor, {'role': 'ADMIN'}),
            (self.other_admin, {'role': 'MENTOR'}),
            (self.other_admin, {'full_name': 'Renamed'}),
        ):
            with self.subTest(account=account.username, body=body):
                response = self.client.patch(member_url(account), body, format='json')
                self.assert_refused(response, status.HTTP_403_FORBIDDEN, 'SUPERUSER_REQUIRED')
        root = self.as_user(self.root)
        self.assertEqual(root.patch(member_url(self.mentor), {'role': 'ADMIN'}, format='json').status_code, 200)
        self.assertEqual(root.patch(member_url(self.other_admin), {'role': 'MENTOR'}, format='json').status_code, 200)

    def test_the_last_active_admin_is_kept(self):
        # A superuser outside the ADMIN role, and one remaining active admin.
        User.objects.filter(pk=self.root.pk).update(role='TUTOR')
        User.objects.filter(pk=self.other_admin.pk).update(is_active=False, deactivated_at=timezone.now())
        root = self.as_user(User.objects.get(pk=self.root.pk))
        self.assert_refused(root.patch(member_url(self.admin), {'role': 'MENTOR'}, format='json'), 409, 'LAST_ADMIN')
        self.assert_refused(root.post(member_url(self.admin, 'deactivate/'), {}, format='json'), 409, 'LAST_ADMIN')
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.role, self.admin.is_active), ('ADMIN', True))

    def test_nobody_changes_their_own_account(self):
        for actor in (self.admin, self.root):
            client = self.as_user(actor)
            for method, url, body in every_endpoint(actor)[1:]:
                with self.subTest(actor=actor.username, method=method, url=url):
                    self.assert_refused(call(client, method, url, body), 403, 'SELF_CHANGE_FORBIDDEN')

    def test_superuser_accounts_are_beyond_an_admins_reach(self):
        boss = self.make('boss', 'MENTOR', is_superuser=True)
        for method, url, body in every_endpoint(boss)[1:]:
            with self.subTest(method=method, url=url):
                self.assert_refused(call(self.client, method, url, body), 403, 'SUPERUSER_REQUIRED')
        boss.refresh_from_db()
        self.assertTrue(boss.check_password(STRONG))
        self.assertTrue(boss.is_active)


class TeamStatusTests(TeamTestCase):
    def test_deactivation_ends_existing_sessions_and_is_audited(self):
        session = APIClient()
        session.force_login(self.mentor)
        self.assertEqual(session.get(STUDENTS_URL).status_code, status.HTTP_200_OK)

        response = self.client.post(member_url(self.mentor, 'deactivate/'), {'reason': 'Left Eduport'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()['is_active'])
        self.mentor.refresh_from_db()
        self.assertEqual(
            (self.mentor.is_active, self.mentor.deactivated_by, self.mentor.deactivation_reason),
            (False, self.admin, 'Left Eduport'),
        )
        self.assertIsNotNone(self.mentor.deactivated_at)
        self.assertEqual(session.get(STUDENTS_URL).status_code, status.HTTP_403_FORBIDDEN)
        row = ActivityLog.objects.get(action='user.deactivate')
        self.assertEqual(row.changes, {'status': {'old': 'active', 'new': 'deactivated'}})
        self.assertEqual(row.context['reason'], 'Left Eduport')

    def test_reactivation_restores_access(self):
        self.client.post(member_url(self.tutor, 'deactivate/'), {}, format='json')
        response = self.client.post(member_url(self.tutor, 'reactivate/'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tutor.refresh_from_db()
        self.assertTrue(self.tutor.is_active)
        self.assertIsNone(self.tutor.deactivated_at)
        self.assertIsNone(self.tutor.deactivated_by)
        row = ActivityLog.objects.get(action='user.reactivate')
        self.assertEqual(row.changes, {'status': {'old': 'deactivated', 'new': 'active'}})
        session = APIClient()
        session.force_login(self.tutor)
        self.assertEqual(session.get(STUDENTS_URL).status_code, status.HTTP_200_OK)

    def test_deactivation_waits_for_the_handover(self):
        Student.objects.create(
            profile=self.parent, student_code='TS001', full_name='Kid',
            mentor=self.mentor, tutor=self.tutor, status=StatusChoices.ACTIVE,
        )
        response = self.client.post(member_url(self.tutor, 'deactivate/'), {}, format='json')
        self.assert_refused(response, status.HTTP_409_CONFLICT, 'HANDOVER_REQUIRED')
        self.tutor.refresh_from_db()
        self.assertTrue(self.tutor.is_active)

    def test_repeated_requests_are_refused(self):
        self.assert_refused(self.client.post(member_url(self.tutor, 'reactivate/'), {}, format='json'),
                            409, 'ALREADY_ACTIVE')
        self.client.post(member_url(self.tutor, 'deactivate/'), {}, format='json')
        self.assert_refused(self.client.post(member_url(self.tutor, 'deactivate/'), {}, format='json'),
                            409, 'ALREADY_DEACTIVATED')
        self.assertEqual(ActivityLog.objects.filter(action='user.deactivate').count(), 1)

    def test_only_superusers_deactivate_admins(self):
        self.assert_refused(self.client.post(member_url(self.other_admin, 'deactivate/'), {}, format='json'),
                            403, 'SUPERUSER_REQUIRED')
        response = self.as_user(self.root).post(member_url(self.other_admin, 'deactivate/'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_checks(self):
        for body, error in (({'reason': 5}, 'INVALID_INPUT'), ({'reason': 'x' * 501}, 'INVALID_INPUT'),
                            ({'note': 'x'}, 'UNKNOWN_FIELDS')):
            with self.subTest(body=body):
                self.assert_refused(self.client.post(member_url(self.tutor, 'deactivate/'), body, format='json'),
                                    400, error)
        self.client.post(member_url(self.tutor, 'deactivate/'), {}, format='json')
        self.assert_refused(
            self.client.post(member_url(self.tutor, 'reactivate/'), {'reason': 'Back'}, format='json'),
            400, 'UNKNOWN_FIELDS',
        )

    def test_the_old_status_endpoint_is_retired(self):
        # /api/users/<id>/status/ answers 410 (D3) and changes nothing; Team's
        # deactivate/reactivate are the only way.
        retired = self.client.post(
            f'/api/users/{self.tutor.pk}/status/', {'action': 'deactivate', 'reason': 'Paused'}, format='json'
        )
        self.assertEqual(retired.status_code, status.HTTP_410_GONE)
        self.tutor.refresh_from_db()
        self.assertTrue(self.tutor.is_active)
        self.assertFalse(ActivityLog.objects.filter(action='user.deactivate').exists())


class TeamPasswordResetTests(TeamTestCase):
    def reset(self, account, password=NEW_TEMPORARY, client=None):
        return (client or self.client).post(
            member_url(account, 'reset-password/'), {'temporary_password': password}, format='json'
        )

    def test_reset_forces_a_change_unlocks_and_signs_the_account_out(self):
        User.objects.filter(pk=self.mentor.pk).update(
            failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=10)
        )
        session = APIClient()
        session.force_login(User.objects.get(pk=self.mentor.pk))
        self.assertEqual(session.get(ME_URL).status_code, status.HTTP_200_OK)

        response = self.reset(self.mentor)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(NEW_TEMPORARY, response.content.decode())
        self.assertTrue(response.json()['must_change_password'])
        self.assertIsNone(response.json()['locked_until'])
        self.mentor.refresh_from_db()
        self.assertTrue(self.mentor.check_password(NEW_TEMPORARY))
        self.assertEqual(
            (self.mentor.failed_login_count, self.mentor.locked_until, self.mentor.must_change_password),
            (0, None, True),
        )
        # Every existing session of the account ends with the old password.
        self.assertEqual(session.get(ME_URL).status_code, status.HTTP_403_FORBIDDEN)
        browser = APIClient()
        old = browser.post(LOGIN_URL, {'username': 'mentor1', 'password': STRONG}, format='json')
        self.assertEqual(old.status_code, status.HTTP_400_BAD_REQUEST)
        new = browser.post(LOGIN_URL, {'username': 'mentor1', 'password': NEW_TEMPORARY}, format='json')
        self.assertEqual(new.status_code, status.HTTP_200_OK)
        self.assertTrue(new.json()['must_change_password'])

        row = ActivityLog.objects.get(action='user.password_reset')
        self.assertEqual((row.actor, row.entity_id), (self.admin, str(self.mentor.pk)))
        self.assertTrue(row.context['unlocked'])
        self.assert_no_secret_logged(NEW_TEMPORARY, STRONG)

    def test_google_only_staff_receive_a_password(self):
        google_staff = User.objects.create_user(
            email='google.staff@eduport.com', username='google.staff', full_name='Google Staff', role='TUTOR'
        )
        self.assertFalse(google_staff.has_usable_password())
        self.assertEqual(self.reset(google_staff).status_code, status.HTTP_200_OK)
        google_staff.refresh_from_db()
        self.assertTrue(google_staff.check_password(NEW_TEMPORARY))

    def test_a_too_short_temporary_password_is_refused(self):
        for short in ('short', '1234567'):
            with self.subTest(short=short):
                response = self.reset(self.mentor, short)
                self.assert_refused(response, status.HTTP_400_BAD_REQUEST, 'PASSWORD_POLICY')
                self.assertTrue(response.json()['details'])
        self.mentor.refresh_from_db()
        self.assertTrue(self.mentor.check_password(STRONG))
        self.assertFalse(self.mentor.must_change_password)

    def test_a_simple_temporary_password_of_8_is_accepted(self):
        # All digits, close to the account's own email, a common word: all fine.
        for simple in ('12345678', 'mentor1@eduport', 'password'):
            with self.subTest(simple=simple):
                self.assertEqual(self.reset(self.mentor, simple).status_code, status.HTTP_200_OK)
                self.mentor.refresh_from_db()
                self.assertTrue(self.mentor.check_password(simple))
                self.assertTrue(self.mentor.must_change_password)
        created = self.client.post(
            TEAM_URL, self.create_payload(temporary_password='12345678'), format='json'
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

    def test_only_superusers_reset_admin_passwords(self):
        self.assert_refused(self.reset(self.other_admin), 403, 'SUPERUSER_REQUIRED')
        self.assertEqual(self.reset(self.other_admin, client=self.as_user(self.root)).status_code, 200)

    def test_request_checks(self):
        url = member_url(self.mentor, 'reset-password/')
        for body, error in (
            ({}, 'INVALID_INPUT'),
            ({'temporary_password': 12345678901234}, 'INVALID_INPUT'),
            ({'temporary_password': NEW_TEMPORARY, 'must_change_password': False}, 'UNKNOWN_FIELDS'),
        ):
            with self.subTest(body=body):
                self.assert_refused(self.client.post(url, body, format='json'), 400, error)


class TeamPermissionTests(TeamTestCase):
    def put(self, account, permissions, client=None):
        return (client or self.client).put(
            member_url(account, 'permissions/'), {'permissions': permissions}, format='json'
        )

    def test_the_catalogue_holds_only_approved_permissions(self):
        self.assertEqual(self.client.get(CATALOGUE_URL).json(), [{
            'permission': 'accounts.view_team', 'label': 'View the team directory',
            'module': 'Team', 'can_grant': True,
        }])

    def test_granting_and_revoking_view_team(self):
        granted = self.put(self.mentor, ['accounts.view_team'])
        self.assertEqual(granted.status_code, status.HTTP_200_OK)
        self.assertEqual(granted.json()['permissions'], ['accounts.view_team'])
        mentor = User.objects.get(pk=self.mentor.pk)
        self.assertTrue(mentor.has_perm('accounts.view_team'))
        self.assertEqual(self.as_user(mentor).get(TEAM_URL).status_code, status.HTTP_200_OK)
        row = ActivityLog.objects.get(action='user.permissions_update')
        self.assertEqual((row.context['added'], row.context['removed']), (['accounts.view_team'], []))

        revoked = self.put(self.mentor, [])
        self.assertEqual(revoked.json()['permissions'], [])
        mentor = User.objects.get(pk=self.mentor.pk)
        self.assertFalse(mentor.has_perm('accounts.view_team'))
        self.assertEqual(self.as_user(mentor).get(TEAM_URL).status_code, status.HTTP_403_FORBIDDEN)
        # Repeating the same set changes nothing and records nothing.
        self.assertEqual(self.put(self.mentor, []).status_code, status.HTTP_200_OK)
        self.assertEqual(ActivityLog.objects.filter(action='user.permissions_update').count(), 2)

    def test_only_approved_permissions_can_be_assigned(self):
        for requested in (['accounts.change_user'], ['auth.add_permission'],
                          ['accounts.view_team', 'accounts.delete_user'], ['bogus']):
            with self.subTest(requested=requested):
                self.assert_refused(self.put(self.mentor, requested), 400, 'UNKNOWN_PERMISSION')
        for body in ({'permissions': 'accounts.view_team'}, {'permissions': [1]}, {'permissions': None}, {}):
            with self.subTest(body=body):
                response = self.client.put(member_url(self.mentor, 'permissions/'), body, format='json')
                self.assert_refused(response, 400, 'INVALID_INPUT')
        self.assertFalse(User.objects.get(pk=self.mentor.pk).user_permissions.exists())

    def test_you_can_only_grant_or_revoke_what_you_hold(self):
        # Individually grantable, but not on the Admin role group: admins do not
        # hold it, so only a superuser may grant or revoke it.
        superuser_only = {'label': 'View user profiles', 'module': 'Accounts',
                          'roles': ('ADMIN', 'MENTOR', 'TUTOR'), 'grantable': True}
        with patch.dict('accounts.permission_catalogue.CATALOGUE', {'accounts.view_user': superuser_only}):
            can_grant = {row['permission']: row['can_grant'] for row in self.client.get(CATALOGUE_URL).json()}
            self.assertEqual(can_grant, {'accounts.view_team': True, 'accounts.view_user': False})
            refused = self.put(self.mentor, ['accounts.view_user'])
            self.assert_refused(refused, status.HTTP_403_FORBIDDEN, 'PERMISSION_NOT_GRANTABLE')
            self.assertEqual(refused.json()['permissions'], ['accounts.view_user'])
            self.assertEqual(self.put(self.mentor, ['accounts.view_user'], client=self.as_user(self.root)).status_code, 200)
            # ...and an admin cannot take it away again either.
            self.assert_refused(self.put(self.mentor, []), status.HTTP_403_FORBIDDEN, 'PERMISSION_NOT_GRANTABLE')
        self.assertTrue(User.objects.get(pk=self.mentor.pk).has_perm('accounts.view_user'))

    def test_holding_view_team_does_not_let_you_grant_it(self):
        self.mentor.user_permissions.add(view_team_permission())
        holder = self.as_user(User.objects.get(pk=self.mentor.pk))
        self.assertEqual(self.put(self.tutor, ['accounts.view_team'], client=holder).status_code, 403)
        self.assertFalse(User.objects.get(pk=self.tutor.pk).user_permissions.exists())

    def test_admin_accounts_need_a_superuser(self):
        self.assert_refused(self.put(self.other_admin, ['accounts.view_team']), 403, 'SUPERUSER_REQUIRED')

    def test_me_reports_what_the_role_implies(self):
        # /me lists every effective permission: the role group's, plus grants.
        def me_permissions(user):
            return self.as_user(user).get(ME_URL).json()['user']['permissions']

        self.assertIn('accounts.view_team', me_permissions(self.admin))
        self.assertIn('accounts.manage_team', me_permissions(self.admin))
        self.assertIn('accounts.view_mentored_students', me_permissions(self.mentor))
        self.assertNotIn('accounts.view_team', me_permissions(self.mentor))
        self.assertEqual(me_permissions(self.parent), [])
        self.mentor.user_permissions.add(view_team_permission())
        self.assertIn('accounts.view_team', me_permissions(User.objects.get(pk=self.mentor.pk)))


class TeamSessionSecurityTests(TeamTestCase):
    def test_team_writes_need_the_csrf_token(self):
        browser = APIClient(enforce_csrf_checks=True)
        token = browser.get(CSRF_URL).json()['csrf_token']
        login = browser.post(LOGIN_URL, {'username': 'admin1', 'password': STRONG}, format='json',
                             HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertEqual(browser.post(TEAM_URL, self.create_payload(), format='json').status_code, 403)
        self.assertFalse(User.objects.filter(username='new.mentor').exists())
        created = browser.post(TEAM_URL, self.create_payload(), format='json',
                               HTTP_X_CSRFTOKEN=login.json()['csrf_token'])
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

    def test_a_flagged_admin_must_change_their_password_first(self):
        User.objects.filter(pk=self.admin.pk).update(must_change_password=True)
        browser = APIClient()
        browser.post(LOGIN_URL, {'username': 'admin1', 'password': STRONG}, format='json')
        self.assert_refused(browser.get(TEAM_URL), status.HTTP_403_FORBIDDEN, 'PASSWORD_CHANGE_REQUIRED')

    def test_a_deactivated_admin_loses_access_in_an_open_session(self):
        browser = APIClient()
        browser.force_login(self.admin)
        self.assertEqual(browser.get(TEAM_URL).status_code, status.HTTP_200_OK)
        User.objects.filter(pk=self.admin.pk).update(is_active=False, deactivated_at=timezone.now())
        self.assertEqual(browser.get(TEAM_URL).status_code, status.HTTP_403_FORBIDDEN)


@FAST_HASHING
class ConcurrentTeamChangeTests(TransactionTestCase):
    """Two superusers demoting the last two admins at once leave one admin."""

    def test_parallel_demotions_keep_the_last_admin(self):
        root = User.objects.create_superuser(
            username='root', email='root@eduport.com', full_name='Root', password=STRONG, role='TUTOR'
        )
        first = User.objects.create_user(
            email='a1@eduport.com', username='a1', password=STRONG, full_name='A One', role='ADMIN'
        )
        second = User.objects.create_user(
            email='a2@eduport.com', username='a2', password=STRONG, full_name='A Two', role='ADMIN'
        )
        start = threading.Barrier(2)
        results = {}

        def demote(account):
            try:
                client = APIClient()
                client.force_authenticate(root)
                start.wait()
                results[account.username] = client.patch(member_url(account), {'role': 'MENTOR'}, format='json')
            finally:
                connection.close()

        threads = [threading.Thread(target=demote, args=(account,)) for account in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        codes = sorted(response.status_code for response in results.values())
        self.assertEqual(codes, [status.HTTP_200_OK, status.HTTP_409_CONFLICT])
        self.assertEqual(User.objects.filter(role='ADMIN', is_active=True).count(), 1)
