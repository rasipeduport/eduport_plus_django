"""Reset Password for activated Learn accounts: an administrator's recovery without email."""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from activity.models import ActivityLog
from sales.tests_lifecycle import account
from sales.tests_quotes import QuoteTestCase
from .models import Invitation
from .credentials import reveal_credentials
from .tests_credentials import TEST_KEYS
from .tests_regenerate import NEW_PASSWORD as OWN_PASSWORD, EnrolledLearnAccount

User = get_user_model()
LATER_PASSWORD = 'Another-Personal-Secret-2027!'


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS, STRIPE_SECRET_KEY='sk_test_unit_only',
                   STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class ResetActivatedPasswordTests(EnrolledLearnAccount, QuoteTestCase, APITestCase):
    def activated(self):
        """An enrolled student who has set their own password, and the Learn session they did it in."""
        student, inv, temporary = self.enroll()
        client, signed_in = self.login(student.profile, temporary)
        changed = client.post('/api/auth/change-password/', {'current_password': temporary, 'new_password': OWN_PASSWORD},
                              format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        self.assertEqual(changed.status_code, 200, changed.content)
        inv.refresh_from_db(); student.refresh_from_db()
        self.assertEqual((inv.status, inv.credential_ciphertext), ('ACCEPTED', ''))
        return student, inv, client

    def reset(self, inv, seen=None, client=None):
        return (client or self.client).post(f'/api/invitations/{inv.pk}/credentials/reset/',
                                            {'last_password_reset_at': seen}, format='json')

    def reset_logs(self):
        return ActivityLog.objects.filter(action='invitation.password_reset')

    def test_an_activated_account_is_resettable_and_its_own_password_is_never_revealed(self):
        student, inv, _ = self.activated()
        self.client.force_authenticate(self.admin)
        row = self.listed(inv)
        self.assertEqual((row['status'], row['password_resettable'], row['credentials_regenerable'], row['credentials_available'],
                          row['last_password_reset_at']), ('ACCEPTED', True, False, False, None))
        refused = self.client.post(f'/api/invitations/{inv.pk}/credentials/')
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'CREDENTIALS_ACTIVATED'))
        self.assertNotIn(OWN_PASSWORD, str(self.client.get('/api/invitations/').json()))

    def test_reset_keeps_the_account_activated_and_requires_a_new_password(self):
        student, inv, _ = self.activated()
        activated_at, quota, status = inv.activated_at, student.total_class_quota, student.status
        self.client.force_authenticate(self.admin)
        response = self.reset(inv)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'reset')
        self.assertEqual(set(response.json()), {'status', 'last_password_reset_at'})
        temporary = self.reveal(inv)
        self.assertNotIn(temporary, response.content.decode())
        self.assertGreaterEqual(len(temporary), 30)
        inv.refresh_from_db(); student.refresh_from_db(); student.profile.refresh_from_db()
        self.assertEqual((inv.status, inv.activated_at, inv.account_id), ('ACCEPTED', activated_at, student.profile_id))
        self.assertIsNotNone(inv.password_reset_at)
        self.assertNotIn(temporary, inv.credential_ciphertext)
        self.assertTrue(student.profile.must_change_password)
        self.assertEqual((student.profile.username, student.total_class_quota, student.status),
                         (student.student_code.lower(), quota, status))
        row = self.listed(inv)
        self.assertEqual((row['status'], row['credentials_available'], row['password_resettable']), ('ACCEPTED', True, True))

        _, refused = self.login(student.profile, OWN_PASSWORD)
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'INVALID_CREDENTIALS'))
        client, signed_in = self.login(student.profile, temporary)
        self.assertEqual(signed_in.status_code, 200, signed_in.content)
        self.assertTrue(signed_in.json()['must_change_password'])
        self.assertEqual(client.get('/api/student/dashboard/').json()['error'], 'PASSWORD_CHANGE_REQUIRED')
        changed = client.post('/api/auth/change-password/', {'current_password': temporary, 'new_password': LATER_PASSWORD},
                              format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        self.assertEqual(changed.status_code, 200, changed.content)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.credential_ciphertext, inv.activated_at), ('ACCEPTED', '', activated_at))
        self.assertIsNone(reveal_credentials(inv))
        self.assertEqual(client.get('/api/student/dashboard/').status_code, 200)
        _, signed_in = self.login(student.profile, LATER_PASSWORD)
        self.assertEqual(signed_in.status_code, 200)
        self.assertFalse(signed_in.json()['must_change_password'])
        row = self.listed(inv)
        self.assertEqual((row['status'], row['credentials_available'], row['last_password_reset_at']),
                         ('ACCEPTED', False, response.json()['last_password_reset_at']))

    def test_reset_signs_the_student_out_everywhere_and_clears_a_lockout(self):
        student, inv, first = self.activated()
        second, signed_in = self.login(student.profile, OWN_PASSWORD)
        self.assertEqual(signed_in.status_code, 200)
        for client in (first, second):
            self.assertEqual(client.get('/api/auth/me/').status_code, 200)
        User.objects.filter(pk=student.profile_id).update(failed_login_count=5, locked_until=timezone.now() + timedelta(hours=1))
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.reset(inv).status_code, 200)
        for client in (first, second):
            self.assertIn(client.get('/api/auth/me/').status_code, [401, 403])
        account_now = User.objects.get(pk=student.profile_id)
        self.assertEqual((account_now.failed_login_count, account_now.locked_until), (0, None))
        _, signed_in = self.login(student.profile, self.reveal(inv))
        self.assertEqual(signed_in.status_code, 200, signed_in.content)
        self.assertTrue(self.reset_logs().get().context['unlocked'])

    def test_a_pending_account_is_regenerated_not_reset(self):
        student, inv, temporary = self.enroll()
        self.client.force_authenticate(self.admin)
        refused = self.reset(inv)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'ACCOUNT_NOT_ACTIVATED'))
        self.assertFalse(self.listed(inv)['password_resettable'])
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(temporary))
        self.assertEqual((inv.status, inv.password_reset_at), ('PENDING', None))
        self.assertFalse(self.reset_logs().exists())

    def test_an_activated_account_is_reset_not_regenerated_and_legacy_rows_have_nothing(self):
        student, inv, _ = self.activated()
        self.client.force_authenticate(self.admin)
        refused = self.regenerate(inv)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'CREDENTIALS_ACTIVATED'))
        legacy = Invitation.objects.create(email='legacy@example.test', role='STUDENT', status='ACCEPTED',
                                           extra_data={'student_code': 'EDP70002'})
        self.assertEqual(self.reset(legacy).status_code, 404)
        self.assertFalse(self.listed(legacy)['password_resettable'])
        self.assertEqual(self.client.post(f'/api/invitations/{uuid.uuid4()}/credentials/reset/',
                                          {'last_password_reset_at': None}, format='json').status_code, 404)
        self.assertFalse(self.reset_logs().exists())

    def test_activity_log_names_the_reset_reveal_and_copy_and_never_a_secret(self):
        student, inv, _ = self.activated()
        self.client.force_authenticate(self.admin)
        self.reset(inv)
        temporary = self.reveal(inv)
        copied = self.client.post(f'/api/invitations/{inv.pk}/credentials/', {'purpose': 'copy'}, format='json')
        self.assertEqual(copied.json()['temporary_password'], temporary)
        inv.refresh_from_db()
        row = self.reset_logs().get()
        self.assertEqual((row.actor_id, row.entity_type, row.entity_id, row.student_id, row.entity_label),
                         (self.admin.pk, 'invitation', str(inv.pk), student.pk, student.student_code))
        self.assertEqual((row.context['must_change_password'], row.context['unlocked']), (True, False))
        self.assertEqual(ActivityLog.objects.filter(action='invitation.credentials_revealed').count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action='invitation.credentials_copied').count(), 1)
        self.assertFalse(ActivityLog.objects.filter(action='invitation.credentials_regenerated').exists())
        everything = str(list(ActivityLog.objects.values()))
        for secret in (OWN_PASSWORD, temporary, inv.credential_ciphertext):
            self.assertNotIn(secret, everything)

    def test_a_repeated_or_stale_reset_changes_nothing(self):
        student, inv, _ = self.activated()
        self.client.force_authenticate(self.admin)
        first = self.reset(inv).json()['last_password_reset_at']
        temporary = self.reveal(inv)
        again = self.reset(inv)
        self.assertEqual((again.status_code, again.json()['error'], again.json()['last_password_reset_at']),
                         (409, 'CREDENTIALS_CHANGED', first))
        for bad in ({}, {'last_password_reset_at': 'yesterday'}, {'last_password_reset_at': '2026-11-17T10:00:00'}):
            refused = self.client.post(f'/api/invitations/{inv.pk}/credentials/reset/', bad, format='json')
            self.assertEqual((refused.status_code, refused.json()['error']), (400, 'INVALID_INPUT'), bad)
        self.assertEqual(self.reveal(inv), temporary)
        # Reset again deliberately, from what the list now shows: the first temporary password stops working.
        self.assertEqual(self.reset(inv, seen=self.listed(inv)['last_password_reset_at']).status_code, 200)
        _, refused = self.login(student.profile, temporary)
        self.assertEqual(refused.status_code, 400)
        _, signed_in = self.login(student.profile, self.reveal(inv))
        self.assertEqual(signed_in.status_code, 200)
        self.assertEqual(self.reset_logs().count(), 2)

    def test_only_who_may_reveal_may_reset(self):
        student, inv, _ = self.activated()
        mentor, tutor = account('reset_mentor', 'MENTOR'), account('reset_tutor', 'TUTOR')
        for user in (self.bde, mentor, tutor, student.profile):
            self.client.force_authenticate(user)
            self.assertEqual(self.reset(inv).status_code, 403, user.role)
        self.client.force_authenticate(None)
        self.assertIn(self.reset(inv).status_code, [401, 403])
        session = APIClient(enforce_csrf_checks=True); session.force_login(self.admin)
        self.assertEqual(self.reset(inv, client=session).status_code, 403)
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(OWN_PASSWORD))
        self.assertFalse(student.profile.must_change_password)
        self.assertIsNone(inv.password_reset_at)
        self.assertFalse(self.reset_logs().exists())

    def test_without_a_key_nothing_is_reset(self):
        student, inv, _ = self.activated()
        self.client.force_authenticate(self.admin)
        with override_settings(LEARN_INVITATION_KEYS=[]):
            self.assertEqual(self.reset(inv).status_code, 503)
        student.profile.refresh_from_db(); inv.refresh_from_db()
        self.assertTrue(student.profile.check_password(OWN_PASSWORD))
        self.assertFalse(student.profile.must_change_password)
        self.assertEqual((inv.credential_ciphertext, inv.password_reset_at), ('', None))
        self.assertFalse(self.reset_logs().exists())

    def test_copy_login_details_of_a_pending_account_is_logged_as_a_copy(self):
        student, inv, temporary = self.enroll()
        self.client.force_authenticate(self.admin)
        copied = self.client.post(f'/api/invitations/{inv.pk}/credentials/', {'purpose': 'copy'}, format='json')
        self.assertEqual((copied.status_code, copied.json()['temporary_password']), (200, temporary))
        self.assertIn('no-store', copied['Cache-Control'])
        refused = self.client.post(f'/api/invitations/{inv.pk}/credentials/', {'purpose': 'print'}, format='json')
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'INVALID_INPUT'))
        self.assertEqual(ActivityLog.objects.filter(action='invitation.credentials_copied').count(), 1)
        self.assertFalse(ActivityLog.objects.filter(action='invitation.credentials_revealed').exists())

    def test_the_first_activation_date_is_kept_through_every_later_password_change(self):
        student, inv, temporary = self.enroll()
        self.assertIsNone(inv.activated_at)
        client, signed_in = self.login(student.profile, temporary)
        before = timezone.now()
        client.post('/api/auth/change-password/', {'current_password': temporary, 'new_password': OWN_PASSWORD},
                    format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'ACCEPTED')
        self.assertGreaterEqual(inv.activated_at, before)  # The first change activates, as before.
        first = timezone.now() - timedelta(days=30)
        Invitation.objects.filter(pk=inv.pk).update(activated_at=first)

        # The student's own later change.
        changed = client.post('/api/auth/change-password/', {'current_password': OWN_PASSWORD, 'new_password': LATER_PASSWORD},
                              format='json', HTTP_X_CSRFTOKEN=client.get('/api/auth/me/').json()['csrf_token'])
        self.assertEqual(changed.status_code, 200, changed.content)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.activated_at), ('ACCEPTED', first))

        # An administrator's reset, then the change it requires.
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.reset(inv).status_code, 200)
        reset = self.reveal(inv)
        client, signed_in = self.login(student.profile, reset)
        changed = client.post('/api/auth/change-password/', {'current_password': reset, 'new_password': 'Third-Personal-Secret-2028!'},
                              format='json', HTTP_X_CSRFTOKEN=signed_in.json()['csrf_token'])
        self.assertEqual(changed.status_code, 200, changed.content)
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.activated_at, inv.credential_ciphertext), ('ACCEPTED', first, ''))
