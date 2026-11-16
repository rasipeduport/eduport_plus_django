"""Regenerate Temporary Password for pending Learn accounts, through the real enrollment path."""
import uuid
from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from activity.models import ActivityLog
from students.models import Student
from sales.tests_lifecycle import account
from sales.tests_quotes import QuoteTestCase
from .models import Invitation
from .credentials import CredentialUnavailable, issue_existing_student, reveal_credentials
from . import tests_credentials as enrolled
from .tests_credentials import TEST_KEYS

User = get_user_model()
NEW_PASSWORD = 'A-New-Personal-Secret-2026!'


class EnrolledLearnAccount:
    """A Learn account enrolled for real (tests_credentials' fixtures) and the calls on its invitation."""
    # The enrollment fixtures of tests_credentials, through its module so the
    # runner does not collect (and run) EnrollmentCredentialTests here again.
    setUp = enrolled.EnrollmentCredentialTests.setUp
    new_lead = enrolled.EnrollmentCredentialTests.new_lead
    url = enrolled.EnrollmentCredentialTests.url
    start = enrolled.EnrollmentCredentialTests.start
    token_sale = enrolled.EnrollmentCredentialTests.token_sale
    reserve_token = enrolled.EnrollmentCredentialTests.reserve_token
    payload = enrolled.EnrollmentCredentialTests.payload
    collect = enrolled.EnrollmentCredentialTests.collect
    stripe_transport = enrolled.EnrollmentCredentialTests.stripe_transport
    event = enrolled.EnrollmentCredentialTests.event
    webhook = enrolled.EnrollmentCredentialTests.webhook
    enroll = enrolled.EnrollmentCredentialTests.enroll
    login = enrolled.EnrollmentCredentialTests.login

    def regenerate(self, inv, seen=None, client=None):
        return (client or self.client).post(f'/api/invitations/{inv.pk}/credentials/regenerate/',
                                            {'last_password_reset_at': seen}, format='json')

    def reveal(self, inv):
        return self.client.post(f'/api/invitations/{inv.pk}/credentials/').json()['temporary_password']

    def listed(self, inv):
        return next(row for row in self.client.get('/api/invitations/').json() if row['id'] == str(inv.pk))


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS, STRIPE_SECRET_KEY='sk_test_unit_only',
                   STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class RegenerateCredentialTests(EnrolledLearnAccount, QuoteTestCase, APITestCase):
    def regenerated_logs(self):
        return ActivityLog.objects.filter(action='invitation.credentials_regenerated')

    def test_enrollment_issues_a_pending_account_never_regenerated(self):
        student, inv, password = self.enroll()
        self.client.force_authenticate(self.admin)
        row = self.listed(inv)
        self.assertEqual((row['status'], row['credentials_available'], row['credentials_regenerable'], row['last_password_reset_at']),
                         ('PENDING', True, True, None))
        self.assertIsNone(inv.password_reset_at)
        self.assertEqual(ActivityLog.objects.filter(action='invitation.credentials_created').count(), 1)
        self.assertFalse(self.regenerated_logs().exists())
        self.assertEqual(self.reveal(inv), password)

    def test_regeneration_replaces_the_password_and_still_requires_a_change(self):
        student, inv, old = self.enroll()
        self.client.force_authenticate(self.admin)
        response = self.regenerate(inv)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {'status', 'last_password_reset_at'})
        new = self.reveal(inv)
        self.assertNotEqual(new, old)
        self.assertGreaterEqual(len(new), 30)
        self.assertNotIn(new, response.content.decode())
        inv.refresh_from_db(); student.profile.refresh_from_db()
        self.assertEqual((inv.status, inv.account_id, inv.student_id), ('PENDING', student.profile_id, student.pk))
        self.assertIsNotNone(inv.password_reset_at)
        self.assertTrue(student.profile.must_change_password)
        self.assertNotIn(new, inv.credential_ciphertext)
        self.assertEqual(student.profile.username, student.student_code.lower())

        _, refused = self.login(student.profile, old)
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'INVALID_CREDENTIALS'))
        client, signed_in = self.login(student.profile, new)
        self.assertEqual(signed_in.status_code, 200, signed_in.content)
        self.assertTrue(signed_in.json()['must_change_password'])
        self.assertEqual(client.get('/api/student/dashboard/').json()['error'], 'PASSWORD_CHANGE_REQUIRED')
        changed = client.post('/api/auth/change-password/', {'current_password': new, 'new_password': NEW_PASSWORD},
                              format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        self.assertEqual(changed.status_code, 200, changed.content)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.credential_ciphertext), ('ACCEPTED', ''))
        self.assertIsNotNone(inv.activated_at)  # Activated by this first change of its own.
        self.assertIsNone(reveal_credentials(inv))
        row = self.listed(inv)
        self.assertEqual((row['status'], row['credentials_regenerable']), ('ACCEPTED', False))
        self.assertEqual(row['last_password_reset_at'], response.json()['last_password_reset_at'])

    def test_old_sessions_end_and_a_lockout_is_cleared(self):
        student, inv, old = self.enroll()
        old_session, signed_in = self.login(student.profile, old)
        self.assertEqual(signed_in.status_code, 200)
        User.objects.filter(pk=student.profile_id).update(failed_login_count=5, locked_until=timezone.now() + timedelta(hours=1))
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.regenerate(inv).status_code, 200)
        self.assertIn(old_session.get('/api/auth/me/').status_code, [401, 403])
        account_now = User.objects.get(pk=student.profile_id)
        self.assertEqual((account_now.failed_login_count, account_now.locked_until), (0, None))
        _, signed_in = self.login(student.profile, self.reveal(inv))
        self.assertEqual(signed_in.status_code, 200, signed_in.content)
        self.assertTrue(self.regenerated_logs().get().context['unlocked'])

    def test_activity_log_names_the_regeneration_and_never_a_secret(self):
        student, inv, old = self.enroll()
        self.client.force_authenticate(self.admin)
        self.regenerate(inv)
        new = self.reveal(inv)
        inv.refresh_from_db()
        row = self.regenerated_logs().get()
        self.assertEqual((row.actor_id, row.entity_type, row.entity_id, row.student_id, row.entity_label),
                         (self.admin.pk, 'invitation', str(inv.pk), student.pk, student.student_code))
        self.assertEqual((row.context['must_change_password'], row.context['unlocked']), (True, False))
        self.assertEqual(ActivityLog.objects.filter(action='invitation.credentials_revealed').count(), 1)
        everything = str(list(ActivityLog.objects.values()))
        for secret in (old, new, inv.credential_ciphertext):
            self.assertNotIn(secret, everything)
        self.assertNotIn(new, str(inv.extra_data))

    def test_a_repeated_or_stale_request_changes_nothing(self):
        student, inv, old = self.enroll()
        self.client.force_authenticate(self.admin)
        first = self.regenerate(inv).json()['last_password_reset_at']
        password = self.reveal(inv)
        again = self.regenerate(inv)
        self.assertEqual((again.status_code, again.json()['error']), (409, 'CREDENTIALS_CHANGED'))
        self.assertEqual(again.json()['last_password_reset_at'], first)
        for bad in ({}, {'last_password_reset_at': 'not-a-date'}, {'last_password_reset_at': '2026-13-45T10:00:00Z'},
                    {'last_password_reset_at': '2026-11-17T10:00:00'}, {'last_password_reset_at': 5}):
            refused = self.client.post(f'/api/invitations/{inv.pk}/credentials/regenerate/', bad, format='json')
            self.assertEqual((refused.status_code, refused.json()['error']), (400, 'INVALID_INPUT'), bad)
        self.assertEqual(self.reveal(inv), password)
        self.assertEqual(self.regenerated_logs().count(), 1)
        # Regenerating again deliberately, from what the list now shows, works.
        self.assertEqual(self.regenerate(inv, seen=self.listed(inv)['last_password_reset_at']).status_code, 200)
        self.assertNotEqual(self.reveal(inv), password)
        self.assertEqual(self.regenerated_logs().count(), 2)

    def test_an_activated_account_is_never_regenerated(self):
        student, inv, old = self.enroll()
        client, signed_in = self.login(student.profile, old)
        client.post('/api/auth/change-password/', {'current_password': old, 'new_password': NEW_PASSWORD},
                    format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        self.client.force_authenticate(self.admin)
        refused = self.regenerate(inv)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'CREDENTIALS_ACTIVATED'))
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(NEW_PASSWORD))
        self.assertFalse(student.profile.must_change_password)
        self.assertEqual((inv.status, inv.credential_ciphertext, inv.password_reset_at), ('ACCEPTED', '', None))
        self.assertFalse(self.regenerated_logs().exists())

    def test_only_who_may_reveal_may_regenerate(self):
        student, inv, old = self.enroll()
        mentor, tutor = account('regen_mentor', 'MENTOR'), account('regen_tutor', 'TUTOR')
        for user in (self.bde, mentor, tutor, student.profile):
            self.client.force_authenticate(user)
            self.assertEqual(self.regenerate(inv).status_code, 403, user.role)
        self.client.force_authenticate(None)
        self.assertIn(self.regenerate(inv).status_code, [401, 403])
        # A signed-in administrator without the CSRF token is refused too.
        session = APIClient(enforce_csrf_checks=True); session.force_login(self.admin)
        self.assertEqual(self.regenerate(inv, client=session).status_code, 403)
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(old))
        self.assertIsNone(inv.password_reset_at)
        self.assertFalse(self.regenerated_logs().exists())

    def test_legacy_and_unknown_rows_have_nothing_to_regenerate(self):
        legacy = Invitation.objects.create(email='legacy@example.test', role='STUDENT', status='PENDING',
                                           extra_data={'student_code': 'EDP70001'})
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.regenerate(legacy).status_code, 404)
        self.assertEqual(self.client.post(f'/api/invitations/{uuid.uuid4()}/credentials/regenerate/',
                                          {'last_password_reset_at': None}, format='json').status_code, 404)
        self.assertFalse(self.listed(legacy)['credentials_regenerable'])

    def test_regeneration_recovers_credentials_sealed_with_a_removed_key(self):
        student, inv, old = self.enroll()
        new_key = Fernet.generate_key().decode()
        self.client.force_authenticate(self.admin)
        with override_settings(LEARN_INVITATION_KEYS=[new_key]):
            with self.assertRaises(CredentialUnavailable): reveal_credentials(inv)
            self.assertTrue(self.listed(inv)['credentials_regenerable'])
            self.assertEqual(self.regenerate(inv).status_code, 200)
            _, signed_in = self.login(student.profile, self.reveal(inv))
        self.assertEqual(signed_in.status_code, 200, signed_in.content)

    @override_settings(LEARN_INVITATION_KEYS=[])
    def test_without_a_key_nothing_is_replaced(self):
        with override_settings(LEARN_INVITATION_KEYS=TEST_KEYS):
            student, inv, old = self.enroll()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.regenerate(inv).status_code, 503)
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(old))
        self.assertIsNone(inv.password_reset_at)
        self.assertFalse(self.regenerated_logs().exists())

    def test_repeated_legacy_issue_keeps_the_regenerated_credentials(self):
        student, inv, old = self.enroll()
        self.client.force_authenticate(self.admin)
        self.regenerate(inv)
        new = self.reveal(inv)
        again = issue_existing_student(student.pk, self.admin)
        self.assertEqual((again.pk, reveal_credentials(again)), (inv.pk, new))
        self.assertEqual((Invitation.objects.count(), Student.objects.count()), (1, 1))
