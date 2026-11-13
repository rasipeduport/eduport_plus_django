"""Live-object boundary tests complement the all-route authorization snapshot."""
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Permission
from django.core import signing
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz import effective_permissions
from invitations.models import Invitation
from students.models import Student
from . import autopay, tests_payments as payment_helpers, tests_autopay as autopay_helpers
from .autopay_models import AutopayAgreement
from .payment_models import Payment, Purchase, StripeEvent
from .tests_lifecycle import account
from .tests_quotes import QuoteTestCase

KEY = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='


class InitialSalesFixture:
    setUp = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    url = payment_helpers.InitialPaymentTests.url
    start = payment_helpers.InitialPaymentTests.start
    payload = payment_helpers.InitialPaymentTests.payload
    collect = payment_helpers.InitialPaymentTests.collect
    stripe_transport = payment_helpers.InitialPaymentTests.stripe_transport
    event = payment_helpers.InitialPaymentTests.event
    webhook = payment_helpers.InitialPaymentTests.webhook

    def staff_requests(self, client, payment_id):
        """Valid request syntax prevents validation errors masking scope checks."""
        quote = self.client.get(self.url()).json()['quote']
        schedule = {'quote_id': quote['id'], 'initial_classes': '2', 'installments': [
            {'classes': '8', 'due_at': (timezone.now() + timedelta(days=2)).isoformat()}]}
        return [
            client.get(self.url()), client.post(self.url(), {'kind': 'NEW'}, format='json'),
            client.get(self.url('amount/'), {'purpose': 'TUITION', 'collection_mode': 'PARTIAL', 'classes': '1'}),
            client.post(self.url('payments/'), self.payload(), format='multipart'),
            client.post(f'/api/sales/enquiries/{self.lead.pk}/installment-quote/', {'quote_id': quote['id'], 'collection_mode': 'PARTIAL'}, format='json'),
            client.post(self.url('autopay/preview/'), schedule, format='json'),
            client.post(self.url('autopay/'), {**schedule, 'request_id': str(uuid.uuid4()), 'review_token': 'not-signed'}, format='json'),
            client.get(f'/api/sales/payments/{payment_id}/proof/'),
            client.post(f'/api/sales/payments/{payment_id}/expire/', {}, format='json'),
        ]


@override_settings(LEARN_INVITATION_KEYS=[KEY], STRIPE_SECRET_KEY='sk_test_unit_only',
    STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class InitialSalesAuthorizationTests(InitialSalesFixture, QuoteTestCase, APITestCase):
    def test_other_bde_is_denied_every_staff_transport_for_a_real_sale(self):
        self.assertEqual(self.start().status_code, 201)
        self.assertEqual(self.collect().status_code, 201)
        payment = Payment.objects.get()
        other = APIClient(); other.force_authenticate(self.other_bde)
        for result in self.staff_requests(other, payment.pk):
            self.assertEqual(result.status_code, 404, result.content)
        self.assertEqual((Payment.objects.count(), Student.objects.count()), (1, 1))

    def test_mentor_tutor_student_and_sales_tl_cannot_gain_payment_access_via_direct_grants(self):
        self.start(); self.collect(); payment = Payment.objects.get()
        grant = Permission.objects.get(content_type__app_label='accounts', codename='manage_initial_sales')
        for role in ('MENTOR', 'TUTOR', 'STUDENT', 'SALES_TL'):
            with self.subTest(role=role):
                user = account('sales_boundary_' + role.lower(), role)
                user.user_permissions.add(grant)
                self.assertNotIn('accounts.manage_initial_sales', effective_permissions(user))
                client = APIClient(); client.force_authenticate(user)
                for result in self.staff_requests(client, payment.pk):
                    self.assertEqual(result.status_code, 403, result.content)
                self.assertEqual(client.get(f'/api/sales/students/{Student.objects.get().pk}/initial-sale/').status_code, 403)
        self.assertEqual(Payment.objects.count(), 1)

    def test_after_enrollment_the_bde_can_only_collect_the_remaining_balance(self):
        self.start(); result = self.collect(); self.assertEqual(result.status_code, 201)
        payment = Payment.objects.get(); student = Student.objects.get()
        original_password = student.profile.password
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertTrue(self.client.get(self.url()).json()['can_collect'])  # 4 of 10 classes remain unpaid.
        responses = self.staff_requests(self.client, payment.pk)
        # History, idempotent start, own receipt and a remaining-balance amount
        # stay available. Collecting more than the 4 unpaid classes is refused;
        # Autopay setup is pre-enrollment only; a received payment cannot be
        # expired; a pinned replacement conflicts.
        self.assertEqual([res.status_code for res in responses], [200, 201, 200, 400, 409, 403, 403, 200, 409])
        self.assertEqual((responses[3].json()['error'], responses[8].json()['error']), ('INVALID_ALLOCATION', 'PAYMENT_NOT_PENDING'))
        self.assertEqual((Payment.objects.count(), Purchase.objects.count(), Student.objects.count(), Invitation.objects.count()), (1, 1, 1, 1))
        student.refresh_from_db()
        self.assertEqual((student.total_class_quota, student.profile.password), (6, original_password))

    def test_admin_can_see_initial_sale_receipt_student_and_invitation(self):
        self.start(); self.collect(); payment = Payment.objects.get(); student = Student.objects.get()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(self.client.get(f'/api/sales/students/{student.pk}/initial-sale/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/sales/payments/{payment.pk}/proof/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/students/{student.pk}/profile/').status_code, 200)
        rows = self.client.get('/api/invitations/').json()
        self.assertEqual(rows[0]['student_id'], str(student.pk))
        self.assertEqual(self.client.post(f'/api/invitations/{rows[0]["id"]}/credentials/').status_code, 200)

    def test_webhook_ignores_staff_session_and_always_requires_signature(self):
        self.start()
        for user in (None, self.admin, self.bde):
            client = APIClient(enforce_csrf_checks=True)
            if user: client.force_authenticate(user)
            for signature in ('', 't=1,v1=forged'):
                response = client.post('/api/sales/webhooks/stripe/', b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE=signature)
                self.assertEqual((response.status_code, response.json()['error']), (400, 'INVALID_SIGNATURE'))
        self.assertEqual((StripeEvent.objects.count(), Payment.objects.count(), Student.objects.count()), (0, 0, 0))


@override_settings(LEARN_INVITATION_KEYS=[KEY], STRIPE_SECRET_KEY='sk_test_unit_only',
    STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
    AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AutopayAuthorizationTests(InitialSalesFixture, QuoteTestCase, APITestCase):
    new_lead = autopay_helpers.AutopayTests.new_lead
    schedule = autopay_helpers.AutopayTests.schedule
    preview = autopay_helpers.AutopayTests.preview
    transport = autopay_helpers.AutopayTests.transport
    begin = autopay_helpers.AutopayTests.begin
    checkout_event = autopay_helpers.AutopayTests.checkout_event
    initial_paid = autopay_helpers.AutopayTests.initial_paid
    future_event = autopay_helpers.AutopayTests.future_event

    def test_only_owner_or_admin_can_restart_a_real_unpaid_agreement(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.begin().status_code, 201)
            agreement = AutopayAgreement.objects.get()
            for user, status in [(self.other_bde, 404), (account('autopay_tutor_boundary', 'TUTOR'), 403),
                                  (account('autopay_mentor_boundary', 'MENTOR'), 403)]:
                client = APIClient(); client.force_authenticate(user)
                result = client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/', {'request_id': str(uuid.uuid4())}, format='json')
                self.assertEqual(result.status_code, status, result.content)
        self.assertEqual(Payment.objects.count(), 1)

    def test_admin_can_review_and_begin_initial_autopay_without_enrolling(self):
        self.start(); self.client.force_authenticate(self.admin)
        gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.begin().status_code, 201)
        self.assertEqual(AutopayAgreement.objects.get().created_by_id, self.admin.pk)
        self.assertFalse(Student.objects.exists())

    def test_enrollment_stops_fresh_bde_setup_and_restart_and_teaching_staff_financial_payloads(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
        agreement = AutopayAgreement.objects.get(); student = Student.objects.get()
        self.assertEqual(self.preview().status_code, 403)
        self.assertEqual(self.client.post(self.url('autopay/'), {**self.schedule(),
            'request_id': str(uuid.uuid4()), 'review_token': 'not-signed'}, format='json').status_code, 403)
        result = self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/', {'request_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(result.status_code, 403)
        mentor = account('finance_private_mentor', 'MENTOR'); tutor = account('finance_private_tutor', 'TUTOR')
        student.mentor, student.tutor = mentor, tutor; student.save(update_fields=['mentor', 'tutor'])
        for user in (mentor, tutor):
            client = APIClient(); client.force_authenticate(user)
            profile = client.get(f'/api/students/{student.pk}/profile/')
            self.assertEqual(profile.status_code, 200, profile.content)
            self.assertNotIn('autopay', profile.json())
            self.assertNotIn('payments', profile.json())
            self.assertNotIn('paid_amount', str(profile.json()))
            self.assertEqual(client.get(f'/api/sales/students/{student.pk}/initial-sale/').status_code, 403)
        self.assertEqual((Payment.objects.count(), Student.objects.count(), student.total_class_quota), (1, 1, 2))

    def test_parent_link_is_signature_and_expiry_scoped_not_a_staff_permission(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
        agreement = AutopayAgreement.objects.get()
        attempt = agreement.installments.get(position=0).attempts.get()
        token = autopay.action_token(attempt)
        anonymous = APIClient(enforce_csrf_checks=True)
        valid = anonymous.get(f'/api/sales/autopay/actions/{token}/')
        self.assertEqual(valid.status_code, 200)
        self.assertNotIn('client_secret', valid.json())
        self.assertIn('no-store', valid['Cache-Control'])
        self.assertEqual(anonymous.get(f'/api/sales/autopay/actions/{token}x/').status_code, 404)
        with mock.patch('django.core.signing.time.time', return_value=signing.time.time() + 8 * 86400):
            self.assertEqual(anonymous.get(f'/api/sales/autopay/actions/{token}/').status_code, 404)
        self.assertEqual((Payment.objects.count(), Student.objects.get().total_class_quota), (1, 2))
