"""Initial sales tests use a disposable DB, signed webhook fixtures and mocked Stripe transport."""
import hashlib
import hmac
import json
import tempfile
import time
import uuid
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, close_old_connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from students.models import Student
from . import payments, quotes, services
from .payment_models import Payment, Purchase, Sale, StripeCustomer, StripeEvent
from .tests_quotes import QuoteTestCase, lead_of


class AllocationTests(SimpleTestCase):
    def test_whole_rounding_and_final_installment_conserve_total(self):
        self.assertEqual([payments.whole(D(x)) for x in ['52.875', '52.40', '52.50']], [D(53), D(52), D(53)])
        for total in [D(500), D(53), D(101)]:
            paid = {'classes': D(0), 'amount': D(0)}
            amounts = []
            for classes in [D(6), D(2), D(2)]:
                amount, _ = payments.allocation(total, D(10), paid, classes, 'PARTIAL')
                paid = {'classes': paid['classes'] + classes, 'amount': paid['amount'] + amount}
                amounts.append(amount)
            self.assertEqual(sum(amounts), total)
            self.assertTrue(all(amount == payments.whole(amount) for amount in amounts))

    def test_token_credit_does_not_invent_paid_classes(self):
        due, classes = payments.allocation(D(500), D(10), {'classes': D(0), 'amount': D(100)}, D(6), 'PARTIAL')
        self.assertEqual((due, classes), (D(200), D(6)))

    def test_invalid_or_excess_allocations_are_refused(self):
        for classes in ['0', '-1', '0.25', '11', 'NaN', 'Infinity']:
            with self.assertRaises(services.SalesError):
                payments.allocation(D(500), D(10), {'classes': D(0), 'amount': D(0)}, classes, 'PARTIAL')
        with self.assertRaises(services.SalesError):
            payments.allocation(D(1), D(100), {'classes': D(0), 'amount': D(0)}, D(60), 'PARTIAL')


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class InitialPaymentTests(QuoteTestCase, APITestCase):
    def setUp(self):
        self.make_world()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.storage = override_settings(MEDIA_ROOT=self.tmp.name)
        self.storage.enable()
        self.addCleanup(self.storage.disable)
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(60), 'offer_fee': D(50),
                                                    'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
        self.counter = 0
        self.lead = self.new_lead()
        self.client.force_authenticate(self.bde)

    def new_lead(self, owner=None, collection_mode='PARTIAL'):
        self.counter += 1
        lead = lead_of(owner or self.bde, f'Phase Student {self.counter}', f'508000{self.counter:03d}')
        lead.parent_email = 'parent@phase1.test'
        lead.save(update_fields=['parent_email'])
        quotes.create_quote(owner or self.bde, {'collection_mode': collection_mode, 'syllabus': self.bridge.pk, 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'lead': lead.pk})
        return lead

    def url(self, suffix=''):
        return f'/api/sales/enquiries/{self.lead.pk}/sale/{suffix}'

    def start(self, kind='NEW', **extra):
        return self.client.post(self.url(), {'kind': kind, **extra}, format='json')

    def payload(self, **extra):
        return {'request_id': str(uuid.uuid4()), 'method': 'TRANSFER', 'purpose': 'TUITION', 'collection_mode': 'PARTIAL',
                'classes': '6', 'amount': '300', 'received_confirmed': True,
                'proof': SimpleUploadedFile('receipt.png', b'\x89PNG\r\n\x1a\n' + b'0' * 20, content_type='image/png'), **extra}

    def collect(self, **extra):
        return self.client.post(self.url('payments/'), self.payload(**extra), format='multipart')

    def stripe_transport(self):
        gateway = mock.MagicMock()
        gateway.v1.customers.create.side_effect = lambda params, options: {'id': 'cus_phase1', 'livemode': False, **params}
        calls = []
        def checkout(params, options):
            calls.append(params)
            return {'id': f'cs_test_{len(calls)}', 'url': f'https://checkout.stripe.com/c/pay/session{len(calls)}',
                    **params, 'livemode': False, 'currency': 'aed', 'amount_total': params['line_items'][0]['price_data']['unit_amount']}
        gateway.v1.checkout.sessions.create.side_effect = checkout
        return gateway, calls

    def event(self, payment, event_id=None, event_type='checkout.session.completed', **overrides):
        obj = {'id': payment.stripe_checkout_id, 'object': 'checkout.session', 'customer': payment.stripe_customer_id,
               'amount_total': int(payment.amount) * 100, 'currency': 'aed', 'client_reference_id': str(payment.pk),
               'payment_status': 'paid', 'payment_intent': f'pi_{payment.pk.hex}',
               'metadata': {'payment_id': str(payment.pk), 'enquiry_id': str(payment.sale.enquiry_id),
                            'sale_id': str(payment.sale_id), 'purchase_id': str(payment.purchase_id or ''),
                            'quote_id': str(payment.purchase.quote_id if payment.purchase_id else payment.sale.original_quote_id or '')}, **overrides}
        return {'id': event_id or f'evt_{uuid.uuid4().hex}', 'object': 'event', 'type': event_type,
                'livemode': False, 'data': {'object': obj}}

    def webhook(self, event, valid=True):
        raw = json.dumps(event).encode()
        stamp = int(time.time())
        digest = hmac.new(b'whsec_unit_only', f'{stamp}.'.encode() + raw, hashlib.sha256).hexdigest()
        return APIClient().post('/api/sales/webhooks/stripe/', raw, content_type='application/json',
                                HTTP_STRIPE_SIGNATURE=f't={stamp},v1={digest if valid else "invalid"}')

    def test_new_sale_loads_quote_and_partial_direct_payment_enrolls_only_paid_classes(self):
        self.assertEqual(self.start().status_code, 201)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(self.client.get(self.url()).json()['totals']['purchased_classes'], '10')
        response = self.collect()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()['state']
        self.assertEqual((body['totals']['package_amount'], body['totals']['paid_amount'], body['totals']['remaining_amount']), ('500', '300', '200'))
        self.assertEqual((body['totals']['paid_classes'], body['totals']['unpaid_classes'], body['totals']['available_quota']), ('6', '4', '6'))
        student = Student.objects.get()
        self.assertRegex(student.student_code, r'^EDP\d{5,}$')
        self.assertEqual((student.quota_source, student.total_class_quota), ('PAYMENTS', D(6)))
        self.assertEqual(Purchase.objects.get().student, student)
        self.assertEqual(Payment.objects.get().sale.student, student)

    def test_enrollment_issues_student_credentials_without_google_or_parent_linking(self):
        from invitations.models import Invitation
        from invitations.credentials import reveal_credentials
        self.start()
        self.assertEqual(self.collect().status_code, 201)
        student = Student.objects.get()
        invitation = Invitation.objects.get(student=student)
        self.assertEqual((invitation.status, invitation.account_id), ('PENDING', student.profile_id))
        client = APIClient()
        for _ in range(2):
            response = client.post('/api/auth/learn/login/', {'username': student.profile.username,
                                  'password': reveal_credentials(invitation)}, format='json')
            self.assertEqual(response.status_code, 200, response.content)
        student.refresh_from_db()
        self.assertEqual((Student.objects.count(), Payment.objects.count(), student.total_class_quota), (1, 1, D(6)))

    def test_every_direct_method_and_full_payment_support_receipt_and_edited_date(self):
        for method in ['TRANSFER', 'AJAS_UAE', 'AJAS_INDIA']:
            with self.subTest(method=method):
                self.lead = self.new_lead(collection_mode='FULL')
                self.start()
                yesterday = timezone.localdate() - timedelta(days=1)
                response = self.collect(method=method, collection_mode='FULL', classes='10', amount='500', payment_date=yesterday.isoformat())
                self.assertEqual(response.status_code, 201, response.content)
                payment = Payment.objects.get(pk=response.json()['payment']['id'])
                self.assertEqual((payment.method, payment.payment_date), (method, yesterday))
                proof = self.client.get(response.json()['payment']['proof_url'])
                self.assertEqual(proof.status_code, 200)
                self.assertEqual(proof['Cache-Control'], 'private, no-store')

    def test_token_requires_date_is_fixed_and_alone_never_enrolls(self):
        self.assertEqual(self.start('TOKEN').status_code, 400)
        self.assertEqual(self.start('TOKEN', expected_start_date=(timezone.localdate() + timedelta(days=5)).isoformat()).status_code, 201)
        bad = self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='99')
        self.assertEqual(bad.status_code, 400)
        response = self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        self.assertEqual(response.json()['state']['sale']['token_status'], 'UPCOMING')
        self.assertRegex(response.json()['state']['sale']['reservation_reference'], r'^TOK\d+')
        followups = self.client.get(f'/api/bde/follow-ups/?enquiry={self.lead.pk}')
        items = [row for row in followups.json()['results'] if row['type'] == 'TOKEN_TUITION']
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['reservation']['payment_status'], items[0]['reservation']['remaining_amount']), ('SUCCEEDED', '400'))
        self.assertEqual(self.client.get(f'/api/bde/follow-ups/?enquiry={self.lead.pk}').json()['results'], followups.json()['results'])
        response = self.collect(amount='200')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Student.objects.get().total_class_quota, D(6))
        self.assertEqual(response.json()['state']['totals']['paid_amount'], '300')
        self.assertEqual(Payment.objects.count(), 2)

    def test_token_reservation_cannot_replace_its_quote_with_a_package_below_the_token(self):
        self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
        original = quotes.latest_quote(self.lead)
        with self.assertRaises(services.SalesError) as caught:
            quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'lead': self.lead.pk, 'syllabus': self.bridge.pk, 'revision': 1,
                'plan_type': 'BRIDGE_COURSE', 'chapter_ids': [self.days[0]], 'replaces': original.pk})
        self.assertEqual(caught.exception.code, 'TOKEN_EXCEEDS_PACKAGE')
        self.assertEqual(quotes.latest_quote(self.lead).pk, original.pk)
        self.assertEqual((Student.objects.count(), Payment.objects.count()), (0, 1))

    def test_invalid_direct_payment_never_credits_or_enrolls(self):
        self.start()
        for extra in [{'amount': '301'}, {'classes': '11'}, {'classes': '0'}, {'received_confirmed': False},
                      {'proof': SimpleUploadedFile('evil.svg', b'<svg/>', content_type='image/svg+xml')},
                      {'payment_date': (timezone.localdate() + timedelta(days=1)).isoformat()}]:
            response = self.collect(**extra)
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual((Payment.objects.count(), Student.objects.count(), Purchase.objects.count()), (0, 0, 0))

    def test_idempotent_direct_retry_and_post_enrollment_boundary(self):
        self.start()
        request_id = str(uuid.uuid4())
        first = self.collect(request_id=request_id)
        second = self.collect(request_id=request_id)
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.json()['payment']['id'], second.json()['payment']['id'])
        self.assertEqual((Payment.objects.count(), Student.objects.count()), (1, 1))
        self.assertEqual(self.collect().status_code, 403)
        self.assertEqual(self.collect(request_id=request_id, amount='500').status_code, 409)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_discounted_installments_require_immutable_replacement(self):
        # Repin a quote at v1, where the Bridge single-payment privilege is 5%.
        old = quotes.latest_quote(self.lead)
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(60), 'offer_fee': D(50),
            'single_payment_percent': D(5), 'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': ''})
        discounted = quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'syllabus': self.bridge.pk, 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                                                   'lead': self.lead.pk, 'replaces': old.pk})
        before = quotes.quote_data(discounted)
        self.start()
        self.assertEqual(self.collect().json()['error'], 'REPLACEMENT_REQUIRED')
        response = self.client.post(f'/api/sales/enquiries/{self.lead.pk}/installment-quote/', {'quote_id': str(discounted.pk), 'collection_mode': 'PARTIAL'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()['supersedes'], response.json()['single_payment_saving'], response.json()['collection_mode']), (str(discounted.pk), '0', 'PARTIAL'))
        # Only current/selection status changes when a later snapshot exists.
        after = quotes.quote_data(discounted)
        for key in ['is_current', 'selection_status']:
            before.pop(key); after.pop(key)
        self.assertEqual(after, before)
        self.assertEqual(self.collect().status_code, 201)

    def test_permissions_and_admin_student_oversight_and_mentor_assignment(self):
        self.start()
        other = APIClient(); other.force_authenticate(self.other_bde)
        self.assertEqual(other.get(self.url()).status_code, 404)
        self.assertEqual(other.post(self.url('payments/'), self.payload(), format='multipart').status_code, 404)
        result = self.collect().json()
        student = Student.objects.get()
        self.assertEqual(other.get(result['payment']['proof_url']).status_code, 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f'/api/sales/students/{student.pk}/initial-sale/').status_code, 200)
        from .tests_lifecycle import account
        mentor = account('phase1mentor', 'MENTOR')
        response = self.client.post('/api/students/reassign/', {'id': str(student.pk), 'mentor': str(mentor.pk), 'tutor': None}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(mentor)
        self.assertEqual(self.client.get(f'/api/students/{student.pk}/profile/').status_code, 200)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_sheet_sync_cannot_overwrite_paid_quota(self):
        self.start(); self.collect()
        student = Student.objects.get()
        from students.quota_sync import sync_one_student_quota, TARGETED_PAYMENT_MANAGED
        self.assertEqual(sync_one_student_quota(student.student_code), TARGETED_PAYMENT_MANAGED)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/students/{student.pk}/sync-quota/').status_code, 409)
        student.refresh_from_db(); self.assertEqual(student.total_class_quota, D(6))

    def test_stripe_partial_link_signed_webhook_and_replays_enroll_once(self):
        self.start()
        gateway, calls = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.collect(method='STRIPE')
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(Student.objects.count(), 0)
            self.assertEqual(calls[0]['line_items'][0]['price_data']['unit_amount'], 30000)
            payment = Payment.objects.get()
            event = self.event(payment)
            self.assertEqual(self.webhook(event, valid=False).status_code, 400)
            self.assertEqual(Student.objects.count(), 0)
            first = self.webhook(event)
            self.assertEqual(first.status_code, 200, first.content)
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook(self.event(payment)).status_code, 200)
            self.assertEqual((Payment.objects.count(), Student.objects.count()), (1, 1))
            self.assertEqual(Student.objects.get().total_class_quota, D(6))
            self.assertEqual(StripeEvent.objects.count(), 2)

    def test_official_stripe_sdk_encodes_customer_bound_whole_aed_checkout(self):
        import stripe
        from urllib.parse import parse_qs
        from .stripe_gateway import client

        class Transport(stripe.HTTPClient):
            name = 'phase1-test-transport'

            def __init__(self):
                super().__init__()
                self.calls = []

            def request(self, method, url, headers, post_data=None, **kwargs):
                self.calls.append((method, url, headers, parse_qs(post_data)))
                body = ({'id': 'cus_phase1', 'object': 'customer'} if url.endswith('/customers') else
                        {'id': 'cs_test_sdk', 'object': 'checkout.session', 'url': 'https://checkout.stripe.com/c/pay/sdk'})
                return json.dumps(body), 200, {}

        transport = Transport()
        self.start()
        with mock.patch('sales.stripe_gateway.stripe.RequestsClient', return_value=transport):
            # Do not mock gateway/client/v1 services: exercise the pinned SDK.
            self.assertIsInstance(client(), stripe.StripeClient)
            response = self.collect(method='STRIPE')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(transport.calls), 2)
        method, url, headers, params = transport.calls[1]
        self.assertEqual((method, url), ('post', 'https://api.stripe.com/v1/checkout/sessions'))
        self.assertEqual(params['customer'], ['cus_phase1'])
        self.assertEqual(params['line_items[0][price_data][unit_amount]'], ['30000'])
        self.assertEqual(params['metadata[enquiry_id]'], [str(self.lead.pk)])
        self.assertTrue(headers['Idempotency-Key'].startswith('eduport-collection-'))
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assertEqual(Student.objects.count(), 0)

    def test_stripe_customer_reused_for_token_and_full_tuition_and_metadata_updated(self):
        self.lead = self.new_lead(collection_mode='FULL')
        self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        gateway, calls = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            token = Payment.objects.get()
            self.assertEqual(self.webhook(self.event(token)).status_code, 200)
            self.assertEqual(Student.objects.count(), 0)
            response = self.collect(method='STRIPE', classes='10', collection_mode='FULL', amount='400')
            self.assertEqual(response.status_code, 201, response.content)
            tuition = Payment.objects.get(pk=response.json()['payment']['id'])
            self.assertEqual(calls[1]['line_items'][0]['price_data']['unit_amount'], 40000)
            self.assertEqual(self.webhook(self.event(tuition)).status_code, 200)
            self.assertEqual(gateway.v1.customers.create.call_count, 1)
            from .stripe_gateway import sync_customer_metadata
            sync_customer_metadata(self.lead.pk)
            self.assertEqual(gateway.v1.customers.update.call_args.args[1]['metadata']['edp_student_id'], Student.objects.get().student_code)
            self.assertTrue(StripeCustomer.objects.get().student_metadata_synced)

    def test_stripe_mismatches_failures_and_unpaid_events_do_not_enroll(self):
        self.start(); gateway, _ = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE')
            payment = Payment.objects.get()
            for mismatch in [{'amount_total': 29999}, {'currency': 'usd'}, {'customer': 'cus_other'}, {'metadata': {}}]:
                self.assertEqual(self.webhook(self.event(payment, **mismatch)).status_code, 400)
            self.assertEqual(self.webhook(self.event(payment, payment_status='unpaid')).status_code, 200)
            self.assertEqual(Student.objects.count(), 0)
            response = self.webhook(self.event(payment, event_type='checkout.session.async_payment_failed'))
            self.assertEqual(response.status_code, 200)
            payment.refresh_from_db(); self.assertEqual(payment.status, 'FAILED')
            self.assertEqual(Student.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET='')
    def test_unconfigured_stripe_is_not_a_fake_success_path(self):
        self.start()
        response = self.collect(method='STRIPE')
        self.assertEqual((response.status_code, response.json()['error']), (503, 'STRIPE_NOT_CONFIGURED'))
        self.assertEqual((Payment.objects.count(), Student.objects.count(), Purchase.objects.count()), (0, 0, 0))

    def test_existing_staff_invitation_and_disabled_parent_do_not_control_enrollment(self):
        from django.contrib.auth import get_user_model
        from invitations.models import Invitation
        Invitation.objects.create(email=self.lead.parent_email, role='MENTOR')
        parent = get_user_model().objects.create_user(username='disabled-phase-parent', email=self.lead.parent_email, role='STUDENT', is_active=False)
        self.start()
        self.assertEqual(self.collect().status_code, 201)
        self.assertNotEqual(Student.objects.get().profile_id, parent.pk)

    def test_missing_parent_email_does_not_block_enrollment(self):
        self.lead.parent_email = ''; self.lead.save(update_fields=['parent_email'])
        self.start()
        self.assertEqual(self.collect().status_code, 201)
        self.assertEqual((Payment.objects.count(), Student.objects.count()), (1, 1))

    def test_half_class_paid_quota_and_whole_aed_collection(self):
        old = quotes.latest_quote(self.lead)
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(45), 'offer_fee': D('35.25'),
            'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
        chosen = self.bridge.revisions.get(number=1).chapters.order_by('position')[1]
        quote = quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'syllabus': self.bridge.pk, 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                                             'chapter_ids': [chosen.pk], 'lead': self.lead.pk, 'replaces': old.pk})
        self.assertEqual((quote.classes, quote.payable_amount), (D('1.5'), D('52.875')))
        self.assertEqual(quotes.quote_data(quote)['collection_amount'], '53')
        self.start()
        response = self.collect(classes='1.5', amount='53', collection_mode='FULL')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Student.objects.get().total_class_quota, D('1.5'))

    def test_demo_tutor_is_retained(self):
        from bookings.models import BookingSlot, BookingType, DemoBooking, BookingStatus
        from .tests_lifecycle import account
        tutor = account('phase_demo_tutor', 'TUTOR')
        now = timezone.now()
        slot = BookingSlot.objects.create(booking_type=BookingType.DEMO, local_date=timezone.localdate() - timedelta(days=2),
            local_time='10:00', starts_at=now-timedelta(days=2), ends_at=now-timedelta(days=2)+timedelta(hours=1))
        DemoBooking.objects.create(lead=self.lead, slot=slot, seat=1, assigned_tutor=tutor,
            tutor_assigned_at=now, status=BookingStatus.COMPLETED, completed_at=now,
            referral_status='NO_REF')
        self.start(); response = self.collect()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Student.objects.get().tutor, tutor)

    def test_overdue_reminder_state_and_expired_stripe_link(self):
        self.start('TOKEN', expected_start_date=(timezone.localdate() + timedelta(days=1)).isoformat())
        gateway, _ = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            payment = Payment.objects.get()
            self.assertEqual(self.client.post(f'/api/sales/payments/{payment.pk}/expire/').status_code, 200)
            payment.refresh_from_db(); self.assertEqual(payment.status, 'EXPIRED')
            self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            sale = Sale.objects.get()
            self.assertEqual(payments.token_state(sale, payments.received(sale), timezone.localdate() + timedelta(days=2)), 'OVERDUE')


@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class PaymentConcurrencyTests(QuoteTestCase, TransactionTestCase):
    def setUp(self):
        self.make_world()
        # TransactionTestCase flushes data-migration role grants between tests.
        # Rebuild only this fixture's BDE grant; production permissions stay migration-managed.
        from django.contrib.auth.models import Group, Permission
        from accounts.models import RoleGroup
        group, _ = Group.objects.get_or_create(name='phase1-concurrency-bdes')
        RoleGroup.objects.update_or_create(role='BDE', defaults={'group': group})
        group.permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='manage_initial_sales'))
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = override_settings(MEDIA_ROOT=self.tmp.name)
        self.storage.enable(); self.addCleanup(self.storage.disable); self.addCleanup(self.tmp.cleanup)
        self.lead = self.make_lead(1)

    def make_lead(self, index):
        lead = lead_of(self.bde, f'Concurrent {index}', f'507000{index:03d}')
        lead.parent_email = 'concurrent-parent@phase1.test'; lead.save(update_fields=['parent_email'])
        quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'syllabus': self.bridge.pk, 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'lead': lead.pk})
        payments.start_sale(self.bde, lead.pk, {'kind': 'NEW'})
        return lead

    def data(self):
        return {'request_id': uuid.uuid4(), 'purpose': 'TUITION', 'method': 'TRANSFER', 'classes': D(10),
                'amount': D(333), 'collection_mode': 'FULL', 'payment_date': timezone.localdate(), 'received_confirmed': True,
                'proof': SimpleUploadedFile('receipt.png', b'\x89PNG\r\n\x1a\n' + b'0' * 20)}

    def run_parallel(self, leads):
        barrier = Barrier(2)
        def run(lead):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return str(payments.collect(self.bde, lead.pk, self.data()).pk)
            except services.SalesError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, leads))

    def test_two_simultaneous_initial_collections_cannot_enroll_or_credit_twice(self):
        results = self.run_parallel([self.lead, self.lead])
        self.assertIn('ALREADY_ENROLLED', results)
        self.assertEqual((Student.objects.count(), Payment.objects.count()), (1, 1))
        self.assertEqual(Student.objects.get().total_class_quota, D(10))
        from invitations.models import Invitation
        self.assertEqual(Invitation.objects.filter(student__isnull=False).count(), 1)

    def test_edp_numbers_are_unique_for_simultaneous_sibling_enrollments(self):
        second = self.make_lead(2)
        self.run_parallel([self.lead, second])
        self.assertEqual(Student.objects.count(), 2)
        self.assertEqual(len(set(Student.objects.values_list('student_code', flat=True))), 2)
        self.assertEqual(len(set(Student.objects.values_list('profile_id', flat=True))), 2)
        from invitations.models import Invitation
        self.assertEqual(Invitation.objects.filter(student__isnull=False).count(), 2)

    def test_received_ledger_and_purchase_cannot_be_rewritten(self):
        payment = payments.collect(self.bde, self.lead.pk, self.data())
        with self.assertRaises(DatabaseError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(amount=D(1))
        with self.assertRaises(DatabaseError), transaction.atomic():
            Purchase.objects.filter(pk=payment.purchase_id).update(classes=D(100))
