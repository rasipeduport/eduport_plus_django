"""Real session/CSRF and ledger integration tests; Stripe transport is mocked."""
from unittest import mock
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from activity.models import ActivityLog
from students.models import Student
from sales.tests_quotes import QuoteTestCase
from sales import tests_payments as fixtures
from sales.payment_models import Payment
from .models import Invitation
from .credentials import reveal_credentials, issue_existing_student, credential_cipher

User = get_user_model()
TEST_KEYS = ['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=']


@override_settings(LEARN_INVITATION_KEYS=TEST_KEYS, STRIPE_SECRET_KEY='sk_test_unit_only',
                   STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class EnrollmentCredentialTests(QuoteTestCase, APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        fixtures.InitialPaymentTests.setUp(self)
    new_lead = fixtures.InitialPaymentTests.new_lead
    url = fixtures.InitialPaymentTests.url
    start = fixtures.InitialPaymentTests.start
    payload = fixtures.InitialPaymentTests.payload
    collect = fixtures.InitialPaymentTests.collect
    stripe_transport = fixtures.InitialPaymentTests.stripe_transport
    event = fixtures.InitialPaymentTests.event
    webhook = fixtures.InitialPaymentTests.webhook

    def enroll(self):
        self.lead.parent_email = ''
        self.lead.save(update_fields=['parent_email'])
        self.assertEqual(self.start().status_code, 201)
        result = self.collect()
        self.assertEqual(result.status_code, 201, result.content)
        student = Student.objects.select_related('profile').get()
        invitation = Invitation.objects.get(student=student)
        return student, invitation, reveal_credentials(invitation)

    def login(self, account, password, client=None):
        client = client or APIClient(enforce_csrf_checks=True)
        token = client.get('/api/auth/csrf/').json()['csrf_token']
        response = client.post('/api/auth/learn/login/', {'username': account.username, 'password': password},
                               format='json', HTTP_X_CSRFTOKEN=token)
        return client, response

    def test_no_email_enrolls_and_creates_exact_student_account_and_pending_invitation(self):
        student, invitation, password = self.enroll()
        self.assertIsNone(student.profile.email)
        self.assertEqual(student.profile.username, student.student_code.lower())
        self.assertTrue(student.profile.check_password(password))
        self.assertTrue(student.profile.must_change_password)
        self.assertEqual(invitation.account, student.profile)
        self.assertEqual(invitation.status, 'PENDING')
        self.assertEqual(student.total_class_quota, 6)
        self.assertEqual((Student.objects.count(), Invitation.objects.count()), (1, 1))

    def test_encryption_hash_and_audit_never_persist_plaintext(self):
        student, inv, password = self.enroll()
        self.assertNotIn(password, inv.credential_ciphertext)
        self.assertNotIn(password, student.profile.password)
        self.assertGreaterEqual(len(password), 30)
        self.assertNotIn(password, str(list(ActivityLog.objects.values())))
        self.assertNotIn(password, str(inv.extra_data))

    def test_duplicate_direct_request_does_not_regenerate_credentials(self):
        self.start()
        body = self.payload()
        request_id = body['request_id']
        self.assertEqual(self.client.post(self.url('payments/'), body, format='multipart').status_code, 201)
        inv = Invitation.objects.get()
        ciphertext = inv.credential_ciphertext
        self.collect(request_id=request_id)
        inv.refresh_from_db()
        self.assertEqual(inv.credential_ciphertext, ciphertext)
        self.assertEqual((Student.objects.count(), Invitation.objects.count(), Payment.objects.count()), (1, 1, 1))

    def test_duplicate_signed_webhooks_do_not_recreate_credentials(self):
        # No enquiry email: Learn credentials never depend on it. The billing
        # contact given here has one, so Checkout shows it prefilled.
        self.lead.parent_email = ''; self.lead.save(update_fields=['parent_email'])
        self.start(billing_contact={'full_name': 'Billing Parent', 'email': 'billing@phase1.test'}); gateway, _ = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.collect(method='STRIPE').status_code, 201)
            payment = Payment.objects.get()
            self.assertFalse(Student.objects.exists())
            event = self.event(payment)
            self.assertEqual(self.webhook(event).status_code, 200)
            original = Invitation.objects.get().credential_ciphertext
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook(self.event(payment)).status_code, 200)
        self.assertEqual((Student.objects.count(), Invitation.objects.count(), Payment.objects.count()), (1, 1, 1))
        self.assertEqual(Invitation.objects.get().credential_ciphertext, original)
        self.assertEqual(Student.objects.get().total_class_quota, 6)

    def test_existing_parent_or_staff_email_never_selects_learn_identity(self):
        parent = User.objects.create_user(username='existing-parent', email=self.lead.parent_email, role='STUDENT')
        self.start(); self.assertEqual(self.collect().status_code, 201)
        self.assertNotEqual(Student.objects.get().profile, parent)
        self.assertFalse(parent.students.exists())

    def test_same_contact_email_creates_separate_sibling_credentials(self):
        self.start(); self.collect()
        first = Invitation.objects.get()
        shared = self.lead.parent_email
        self.lead = self.new_lead()
        self.lead.parent_email = shared; self.lead.save(update_fields=['parent_email'])
        # The same parent email: a person confirms this is a different child.
        self.assertEqual(self.start(confirm_distinct_child=True).status_code, 201); self.collect()
        self.assertEqual(Student.objects.count(), 2)
        second = Invitation.objects.exclude(pk=first.pk).get()
        self.assertNotEqual(first.account_id, second.account_id)
        self.assertNotEqual(first.account.username, second.account.username)
        self.assertNotEqual(reveal_credentials(first), reveal_credentials(second))

    def test_pending_login_is_gated_on_server_and_me_does_not_expose_academics(self):
        student, inv, password = self.enroll()
        client, result = self.login(student.profile, password)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()['must_change_password'])
        me = client.get('/api/auth/me/')
        self.assertNotIn('student_profiles', me.json())
        self.assertEqual(client.get('/api/student/dashboard/').json()['error'], 'PASSWORD_CHANGE_REQUIRED')
        self.assertEqual(client.post('/api/auth/select-student/', {'student_id': str(student.pk)}, format='json',
                                     HTTP_X_CSRFTOKEN=result.json()['csrf_token']).json()['error'], 'PASSWORD_CHANGE_REQUIRED')

    def test_password_change_activates_and_erases_temporary_credentials(self):
        student, inv, password = self.enroll()
        client, result = self.login(student.profile, password)
        result = client.post('/api/auth/change-password/', {'current_password': password, 'new_password': 'A-New-Personal-Secret-2026!'},
                             format='json', HTTP_X_CSRFTOKEN=result.json()['csrf_token'])
        self.assertEqual(result.status_code, 200, result.content)
        inv.refresh_from_db(); student.profile.refresh_from_db()
        self.assertEqual(inv.status, 'ACCEPTED')
        self.assertIsNotNone(inv.activated_at)
        self.assertEqual(inv.credential_ciphertext, '')
        self.assertFalse(student.profile.must_change_password)
        self.assertIsNone(reveal_credentials(inv))
        self.assertEqual(client.get('/api/student/dashboard/').status_code, 200)
        self.assertEqual(client.get('/api/auth/me/').json()['student_profile']['student_code'], student.student_code)
        _, old = self.login(student.profile, password)
        self.assertEqual(old.status_code, 400)
        _, new = self.login(student.profile, 'A-New-Personal-Secret-2026!')
        self.assertEqual(new.status_code, 200)
        self.assertFalse(new.json()['must_change_password'])

    def test_invalid_password_and_reuse_leave_account_pending(self):
        student, inv, password = self.enroll(); client, result = self.login(student.profile, password)
        for current, new, code in [('wrong', 'New-Password-9', 'INVALID_CURRENT_PASSWORD'),
                                   (password, password, 'PASSWORD_REUSED'), (password, '123', 'PASSWORD_POLICY')]:
            res = client.post('/api/auth/change-password/', {'current_password': current, 'new_password': new},
                              format='json', HTTP_X_CSRFTOKEN=result.json()['csrf_token'])
            self.assertEqual(res.json()['error'], code)
        inv.refresh_from_db(); self.assertEqual(inv.status, 'PENDING')
        self.assertTrue(inv.credential_ciphertext)

    def test_login_requires_csrf_and_invalid_credentials_are_generic(self):
        student, inv, password = self.enroll()
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/auth/learn/login/', {'username': student.profile.username, 'password': password}).status_code, 403)
        _, result = self.login(student.profile, 'wrong')
        self.assertEqual(result.json()['error'], 'INVALID_CREDENTIALS')

    def test_admin_list_and_explicit_reveal_have_correct_identity_and_no_store(self):
        student, inv, password = self.enroll()
        self.client.force_authenticate(self.admin)
        data = self.client.get('/api/invitations/').json()[0]
        self.assertEqual((data['student_code'], data['student_name'], data['username']),
                         (student.student_code, student.full_name, student.profile.username))
        self.assertNotIn(password, str(data)); self.assertNotIn('credential_ciphertext', data)
        response = self.client.post(f'/api/invitations/{inv.pk}/credentials/')
        self.assertEqual(response.json()['temporary_password'], password)
        self.assertIn('no-store', response['Cache-Control'])

    def test_bde_and_student_cannot_read_or_reveal_credentials(self):
        student, inv, password = self.enroll()
        for user in [self.bde, student.profile]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/invitations/').status_code, 403)
            self.assertEqual(self.client.post(f'/api/invitations/{inv.pk}/credentials/').status_code, 403)
            self.assertEqual(self.client.post(f'/api/invitations/students/{student.pk}/issue/').status_code, 403)

    def test_reveal_requires_session_csrf(self):
        student, inv, password = self.enroll()
        client = APIClient(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(f'/api/invitations/{inv.pk}/credentials/').status_code, 403)

    def test_hub_auth_is_unchanged_and_google_endpoint_is_removed(self):
        student, inv, password = self.enroll()
        client = APIClient()
        self.assertEqual(client.post('/api/auth/login/', {'username': student.profile.username, 'password': password}).status_code, 400)
        self.assertEqual(client.post('/api/auth/login/', {'username': self.bde.username, 'password': 'Sales-Pass-2026'}).status_code, 200)
        self.assertEqual(client.post('/api/auth/google/', {'credential': 'anything'}).status_code, 404)
        _, result = self.login(self.bde, 'Sales-Pass-2026')
        self.assertEqual(result.status_code, 400)

    @override_settings(LEARN_INVITATION_KEYS=[])
    def test_missing_key_prevents_collection_before_payment_or_enrollment(self):
        self.start()
        self.assertEqual(self.collect().status_code, 503)
        self.assertEqual((Student.objects.count(), Invitation.objects.count(), Payment.objects.count()), (0, 0, 0))

    def test_ciphertext_tampering_fails_closed(self):
        student, inv, password = self.enroll()
        inv.credential_ciphertext = inv.credential_ciphertext[:-5] + 'xxxxx'
        from .credentials import CredentialUnavailable
        with self.assertRaises(CredentialUnavailable): reveal_credentials(inv)

    def test_repeated_issue_never_rotates_credentials(self):
        student, inv, password = self.enroll()
        again = issue_existing_student(student.pk, self.admin)
        self.assertEqual((again.pk, reveal_credentials(again)), (inv.pk, password))

    def test_username_collision_is_resolved_without_changing_edp_id(self):
        from .credentials import new_account
        User.objects.create_user(username='edp99999', email='staff-collision@example.test', role='ADMIN')
        user, password = new_account('EDP99999', 'Student')
        self.assertTrue(user.username.startswith('edp99999-'))
        self.assertTrue(user.check_password(password))

    def test_legacy_transition_preserves_academics_and_sibling_and_invalidates_parent_access(self):
        parent = User.objects.create_user(email='legacy@example.test', username='legacy', role='STUDENT')
        first = Student.objects.create(profile=parent, student_code='EDP80001', full_name='First', total_class_quota=8)
        sibling = Student.objects.create(profile=parent, student_code='EDP80002', full_name='Sibling', total_class_quota=4)
        Invitation.objects.create(email=parent.email, role='STUDENT', status='ACCEPTED', extra_data={'student_code': first.student_code})
        inv = issue_existing_student(first.pk, self.admin)
        first.refresh_from_db(); sibling.refresh_from_db()
        self.assertEqual((first.total_class_quota, sibling.profile_id), (8, parent.pk))
        self.assertNotEqual(first.profile_id, parent.pk)
        self.assertEqual(inv.student, first)
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(issue_existing_student(first.pk, self.admin).pk, inv.pk)

    def test_unpaid_and_token_do_not_create_credentials(self):
        self.start('TOKEN', expected_start_date='2099-01-01')
        self.collect(purpose='TOKEN', classes='0', amount='100', collection_mode='FULL')
        self.assertEqual((Student.objects.count(), Invitation.objects.count()), (0, 0))

    def test_password_change_requires_csrf(self):
        student, inv, password = self.enroll()
        client, response = self.login(student.profile, password)
        denied = client.post('/api/auth/change-password/', {'current_password': password, 'new_password': 'New-Secret-For-Learn-2026'}, format='json')
        self.assertEqual(denied.status_code, 403)
        inv.refresh_from_db(); self.assertEqual(inv.status, 'PENDING')

    def test_enrollment_and_payment_roll_back_if_invitation_cannot_be_created(self):
        from .credentials import CredentialUnavailable
        self.start()
        with mock.patch('invitations.credentials.create_invitation', side_effect=CredentialUnavailable()):
            self.assertEqual(self.collect().status_code, 503)
        self.assertEqual((Student.objects.count(), Invitation.objects.count(), Payment.objects.count()), (0, 0, 0))
        self.assertFalse(User.objects.filter(email__isnull=True).exists())

    def test_key_rotation_can_read_existing_credentials_and_reject_removed_key(self):
        from cryptography.fernet import Fernet
        from .credentials import CredentialUnavailable
        student, inv, password = self.enroll()
        new_key = Fernet.generate_key().decode()
        with override_settings(LEARN_INVITATION_KEYS=[new_key, *TEST_KEYS]):
            self.assertEqual(reveal_credentials(inv), password)
        with override_settings(LEARN_INVITATION_KEYS=[new_key]):
            with self.assertRaises(CredentialUnavailable): reveal_credentials(inv)

    def test_password_change_invalidates_other_sessions_and_reveal_after_activation(self):
        student, inv, password = self.enroll()
        first, result = self.login(student.profile, password)
        second, other = self.login(student.profile, password)
        changed = first.post('/api/auth/change-password/', {'current_password': password, 'new_password': 'New-Student-Only-Secret-2026!'},
                             format='json', HTTP_X_CSRFTOKEN=result.json()['csrf_token'])
        self.assertEqual(changed.status_code, 200)
        self.assertIn(second.get('/api/auth/me/').status_code, [401, 403])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/invitations/{inv.pk}/credentials/').status_code, 409)

    def test_linked_enrollment_history_refuses_purge_without_a_server_error(self):
        student, inv, password = self.enroll()
        self.client.force_authenticate(self.admin)
        response = self.client.delete(f'/api/students/{student.pk}/', {'confirm_code': student.student_code}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'HAS_HISTORY'))
        self.assertTrue(Invitation.objects.filter(student=student).exists())
