"""Real database/signatures, official Stripe SDK transport isolated from live payments."""
import copy
import json
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock
from types import SimpleNamespace

from django.db import DatabaseError, transaction, connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from students.models import Student
from . import autopay, quotes, services
from .autopay_models import AutopayAgreement, AutopayAttempt, AutopayInstallment
from .payment_models import Payment, Purchase, StripeEvent
from .tests_quotes import QuoteTestCase
from . import tests_payments as payment_test_helpers


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only',
                   STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
                   AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai')
@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class AutopayTests(QuoteTestCase, APITestCase):
    def setUp(self):
        # Preserve explicit historical PI-engine coverage; new native Billing
        # scenarios live in tests_billing. Never route native agreements to PI.
        engine = mock.patch('sales.autopay.DEFAULT_COLLECTION_ENGINE', 'LEGACY_PI')
        engine.start()
        self.addCleanup(engine.stop)
        payment_test_helpers.InitialPaymentTests.setUp(self)
    def new_lead(self, owner=None, collection_mode='AUTOPAY'):
        return payment_test_helpers.InitialPaymentTests.new_lead(self, owner, collection_mode=collection_mode)
    url = payment_test_helpers.InitialPaymentTests.url
    start = payment_test_helpers.InitialPaymentTests.start
    payload = payment_test_helpers.InitialPaymentTests.payload
    collect = payment_test_helpers.InitialPaymentTests.collect
    webhook = payment_test_helpers.InitialPaymentTests.webhook

    def schedule(self):
        quote = quotes.latest_quote(self.lead)
        base = timezone.now()
        return {'quote_id': str(quote.pk), 'initial_classes': '2', 'installments': [
            {'classes': count, 'due_at': (base + timedelta(minutes=10 * n)).isoformat()}
            for n, count in enumerate(['3', '3', '2'], 1)]}

    def preview(self, data=None):
        return self.client.post(self.url('autopay/preview/'), data or self.schedule(), format='json')

    def transport(self):
        gateway, checkouts = payment_test_helpers.InitialPaymentTests.stripe_transport(self)
        gateway.v1.payment_methods.retrieve.return_value = {'id': 'pm_autopay', 'type': 'card', 'customer': 'cus_phase1',
            'livemode': False, 'card': {'brand': 'visa', 'last4': '4242'}}
        charges = []
        def create(params, options):
            result = {'id': f'pi_auto_{params["metadata"]["attempt_id"].replace("-", "")}', 'object': 'payment_intent',
                **params, 'status': 'processing', 'livemode': False, 'amount_received': 0, 'last_payment_error': None}
            charges.append((copy.deepcopy(params), options, result))
            return result
        gateway.v1.payment_intents.create.side_effect = create
        return gateway, checkouts, charges

    def begin(self, data=None, request_id=None):
        data = data or self.schedule()
        reviewed = self.preview(data)
        self.assertEqual(reviewed.status_code, 200, reviewed.content)
        return self.client.post(self.url('autopay/'), {**data, 'review_token': reviewed.json()['review_token'],
            'request_id': str(request_id or uuid.uuid4())}, format='json')

    def checkout_event(self, payment, **changes):
        event = payment_test_helpers.InitialPaymentTests.event(self, payment, **changes)
        installment = payment.autopay_installment
        attempt = installment.attempts.order_by('-number').first()
        obj = event['data']['object']
        obj['id'] = attempt.stripe_checkout_id
        obj['metadata'] = autopay.metadata(installment.agreement, installment, attempt.pk)
        obj['consent'] = {'terms_of_service': 'accepted'}
        obj['livemode'] = False
        return event

    def initial_paid(self, gateway):
        payment = Payment.objects.get()
        event = self.checkout_event(payment)
        gateway.v1.payment_intents.retrieve.return_value = {'id': event['data']['object']['payment_intent'], 'status': 'succeeded',
            'customer': payment.stripe_customer_id, 'currency': 'aed', 'amount_received': int(payment.amount) * 100,
            'setup_future_usage': 'off_session', 'payment_method': 'pm_autopay', 'livemode': False}
        result = self.webhook(event)
        self.assertEqual(result.status_code, 200, result.content)
        return payment, event

    def future_event(self, result, kind='payment_intent.succeeded', **changes):
        obj = {**result, 'status': 'succeeded', 'amount_received': result['amount'], **changes}
        return {'id': f'evt_{uuid.uuid4().hex}', 'type': kind, 'livemode': False, 'data': {'object': obj}}

    def test_complete_review_reconciles_whole_aed_and_preserves_half_classes(self):
        self.start()
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()['installments']
        self.assertEqual([row['amount'] for row in rows], ['100', '150', '150', '100'])
        self.assertEqual(sum(D(row['classes']) for row in rows), D(10))
        self.assertEqual((Payment.objects.count(), Student.objects.count(), AutopayAgreement.objects.count()), (0, 0, 0))
        data = self.schedule(); data['initial_classes'] = '1.5'; data['installments'][0]['classes'] = '3.5'
        self.assertEqual(self.preview(data).status_code, 200)

    def test_schedule_rounding_settles_exact_package_and_rejects_invalid_allocations(self):
        self.start()
        data = self.schedule()
        for first in ['0', '0.25', '11']:
            invalid = copy.deepcopy(data); invalid['initial_classes'] = first
            self.assertGreaterEqual(self.preview(invalid).status_code, 400)
        for counts in [['3', '3', '1'], ['3', '3', '3']]:
            invalid = copy.deepcopy(data)
            for row, count in zip(invalid['installments'], counts): row['classes'] = count
            self.assertEqual(self.preview(invalid).status_code, 400)
        from . import payments
        paid = {'classes': D(0), 'amount': D(0)}
        parts = []
        for classes in [D(2), D(3), D(3), D(2)]:
            amount, _ = payments.allocation(D(53), D(10), paid, classes, 'PARTIAL')
            parts.append(amount); paid = {'classes': paid['classes'] + classes, 'amount': paid['amount'] + amount}
        self.assertEqual((parts, sum(parts)), ([D(11), D(16), D(15), D(11)], D(53)))

    def test_due_dates_must_be_explicit_future_unique_and_ordered(self):
        self.start(); data = self.schedule()
        for value in ['garbage', timezone.localdate().isoformat(), (timezone.now() - timedelta(days=1)).isoformat()]:
            invalid = copy.deepcopy(data); invalid['installments'][0]['due_at'] = value
            self.assertEqual(self.preview(invalid).status_code, 400)
        duplicate = copy.deepcopy(data); duplicate['installments'][1]['due_at'] = duplicate['installments'][0]['due_at']
        self.assertEqual(self.preview(duplicate).status_code, 400)
        reversed_dates = copy.deepcopy(data); reversed_dates['installments'].reverse()
        self.assertEqual(self.preview(reversed_dates).status_code, 400)

    def test_schedule_allocates_the_rounded_frozen_quote_total(self):
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(6), 'offer_fee': D('5.25'),
            'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
        self.lead = self.new_lead(); self.start()
        quote = quotes.latest_quote(self.lead)
        self.assertEqual((quote.payable_amount, quote.collection_amount), (D('52.5'), D(53)))
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([row['amount'] for row in response.json()['installments']], ['11', '16', '15', '11'])

    def test_billing_timezone_converts_local_dates_and_rejects_dst_ambiguity(self):
        self.start(); data = self.schedule()
        day = timezone.localdate() + timedelta(days=2)
        for n, row in enumerate(data['installments']): row['due_at'] = f'{day + timedelta(days=n)}T10:00'
        response = self.preview(data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['installments'][1]['due_at'].endswith('06:00:00+00:00'))
        with override_settings(SALES_BILLING_TIMEZONE='America/New_York'):
            with self.assertRaises(services.SalesError): autopay.due_instant('2027-11-07T01:30', autopay.billing_zone())

    def test_combined_paid_checkout_saves_off_session_with_explicit_consent_and_no_enrollment(self):
        self.start(); gateway, calls, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway): response = self.begin()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((Student.objects.count(), Payment.objects.count()), (0, 1))
        self.assertEqual(calls[0]['mode'], 'payment')
        self.assertEqual(calls[0]['payment_intent_data']['setup_future_usage'], 'off_session')
        self.assertEqual(calls[0]['consent_collection']['terms_of_service'], 'required')
        self.assertEqual(calls[0]['allowed_payment_method_types'], ['card'])
        self.assertNotIn('payment_method_types', calls[0])
        self.assertEqual(calls[0]['line_items'][0]['price_data']['unit_amount'], 10000)
        self.assertEqual(response.json()['autopay']['source'], 'BDE_INITIAL')

    def test_official_sdk_encodes_combined_checkout_parameters(self):
        import stripe
        from urllib.parse import parse_qs
        class Transport(stripe.HTTPClient):
            name = 'autopay-test-transport'
            def __init__(self): super().__init__(); self.calls = []
            def request(self, method, url, headers, post_data=None, **kwargs):
                self.calls.append((url, parse_qs(post_data)))
                obj = {'id': 'cus_sdk_auto', 'object': 'customer'} if url.endswith('/customers') else {
                    'id': 'cs_sdk_auto', 'object': 'checkout.session', 'url': 'https://checkout.stripe.com/c/pay/sdk-auto'}
                return json.dumps(obj), 200, {}
        self.start(); transport = Transport()
        with mock.patch('sales.stripe_gateway.stripe.RequestsClient', return_value=transport): response = self.begin()
        self.assertEqual(response.status_code, 201, response.content)
        params = transport.calls[1][1]
        self.assertEqual(params['mode'], ['payment'])
        self.assertEqual(params['payment_intent_data[setup_future_usage]'], ['off_session'])
        self.assertEqual(params['consent_collection[terms_of_service]'], ['required'])
        self.assertEqual(params['allowed_payment_method_types[0]'], ['card'])
        self.assertNotIn('payment_method_types[0]', params)
        self.assertEqual(params['customer'], ['cus_sdk_auto'])
        self.assertEqual(params['line_items[0][price_data][unit_amount]'], ['10000'])
        self.assertEqual(Student.objects.count(), 0)

    def test_changed_or_unreviewed_schedule_cannot_create_checkout(self):
        self.start(); data = self.schedule(); reviewed = self.preview(data).json()
        data['initial_classes'] = '3'; data['installments'][0]['classes'] = '2'
        response = self.client.post(self.url('autopay/'), {**data, 'review_token': reviewed['review_token'], 'request_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

    def test_initial_payment_and_setup_readiness_are_separate_and_duplicates_never_reenroll(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.begin().status_code, 201)
            _, event = self.initial_paid(gateway)
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook({**event, 'id': 'evt_another_initial'}).status_code, 200)
        self.assertEqual((Student.objects.count(), Payment.objects.count()), (1, 1))
        self.assertEqual(Student.objects.get().total_class_quota, D(2))
        agreement = AutopayAgreement.objects.get()
        self.assertEqual((agreement.status, agreement.setup_status, agreement.stripe_payment_method_id), ('ACTIVE', 'READY', 'pm_autopay'))
        self.assertEqual(agreement.installments.get(position=0).status, 'PAID')

    def test_missing_consent_or_wrong_customer_or_unsupported_method_never_marks_ready(self):
        for case in ['consent', 'customer', 'unsupported', 'mode']:
            if case != 'consent': self.lead = self.new_lead()
            self.start(); gateway, _, _ = self.transport()
            customer_id = f'cus_{case}'
            gateway.v1.customers.create.return_value.id = customer_id
            gateway.v1.payment_methods.retrieve.return_value['customer'] = customer_id
            gateway.v1.checkout.sessions.create.side_effect = lambda params, options: SimpleNamespace(id=f'cs_test_{case}', url=f'https://checkout.stripe.com/c/pay/{case}')
            with mock.patch('sales.stripe_gateway.client', return_value=gateway):
                self.assertEqual(self.begin().status_code, 201)
                payment = Payment.objects.filter(sale__enquiry=self.lead).get(); event = self.checkout_event(payment)
                gateway.v1.payment_intents.retrieve.return_value = {'status': 'succeeded', 'customer': customer_id, 'currency': 'aed',
                    'amount_received': 10000, 'setup_future_usage': 'off_session', 'payment_method': 'pm_autopay', 'livemode': False}
                if case == 'consent': event['data']['object']['consent'] = {}
                if case == 'customer': gateway.v1.payment_methods.retrieve.return_value['customer'] = 'cus_other'
                if case == 'unsupported': gateway.v1.payment_methods.retrieve.return_value['type'] = 'ideal'
                if case == 'mode': gateway.v1.payment_methods.retrieve.return_value['livemode'] = True
                response = self.webhook(event)
                self.assertEqual(response.status_code, 200, response.content)
                agreement = AutopayAgreement.objects.get(purchase__sale__enquiry=self.lead)
                self.assertNotEqual(agreement.setup_status, 'READY')
                self.assertEqual(agreement.purchase.sale.student.total_class_quota, D(2))

    def test_due_collection_credits_only_after_signed_success_and_blocks_later_installments(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
            agreement = AutopayAgreement.objects.get(); first = agreement.installments.get(position=1)
            with mock.patch('sales.autopay.timezone.now', return_value=first.due_at + timedelta(seconds=1)):
                autopay.collect_due()
                autopay.collect_due()
            self.assertEqual(len(charges), 1)
            self.assertEqual(Student.objects.get().total_class_quota, D(2))
            event = self.future_event(charges[0][2])
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook({**event, 'id': 'evt_same_charge_again'}).status_code, 200)
            self.assertEqual(Student.objects.get().total_class_quota, D(5))
            with mock.patch('sales.autopay.timezone.now', return_value=agreement.installments.get(position=3).due_at + timedelta(seconds=1)):
                autopay.collect_due()
                self.assertEqual(len(charges), 2, 'third installment waits for the second one to be verified')
            self.assertEqual(Payment.objects.count(), 3)

    def test_failure_remains_active_no_assumed_retry_and_no_later_charge(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway); agreement = AutopayAgreement.objects.get()
            with mock.patch('sales.autopay.timezone.now', return_value=agreement.installments.get(position=3).due_at + timedelta(seconds=1)):
                autopay.collect_due()
                event = self.future_event(charges[0][2], kind='payment_intent.payment_failed', status='requires_payment_method', amount_received=0, last_payment_error={'code': 'card_declined'})
                self.assertEqual(self.webhook(event).status_code, 200)
                for _ in range(3): autopay.collect_due()
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, len(charges)), ('ACTIVE', 1))
        self.assertEqual((Payment.objects.count(), AutopayAttempt.objects.count(), Student.objects.get().total_class_quota), (2, 2, D(2)))

    def test_authentication_requires_parent_action_and_never_repeats_off_session(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway); row = AutopayAgreement.objects.get().installments.get(position=1)
            with mock.patch('sales.autopay.timezone.now', return_value=row.due_at + timedelta(seconds=1)): autopay.collect_due()
            event = self.future_event(charges[0][2], kind='payment_intent.requires_action', status='requires_action', amount_received=0)
            self.assertEqual(self.webhook(event).status_code, 200)
            attempt = row.attempts.get(); gateway.v1.payment_intents.retrieve.return_value = {**event['data']['object'], 'client_secret': 'pi_unit_secret'}
            token = autopay.action_token(attempt)
            response = APIClient().get(f'/api/sales/autopay/actions/{token}/')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['needs_action'])
            self.assertEqual(response.json()['client_secret'], 'pi_unit_secret')
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            with mock.patch('sales.autopay.timezone.now', return_value=row.due_at + timedelta(minutes=1)): autopay.collect_due()
            self.assertEqual(len(charges), 1)
            self.assertEqual(self.webhook(self.future_event(charges[0][2])).status_code, 200)
            self.assertEqual(Student.objects.get().total_class_quota, D(5))
        self.assertEqual(APIClient().get('/api/sales/autopay/actions/invalid/').status_code, 404)

    def test_admin_visibility_and_post_enrollment_bde_and_mentor_boundaries(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway): self.begin(); self.initial_paid(gateway)
        student = Student.objects.get(); agreement = AutopayAgreement.objects.get()
        self.assertEqual(self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/', {'request_id': str(uuid.uuid4())}, format='json').status_code, 403)
        self.assertEqual(self.preview().status_code, 403)
        self.client.force_authenticate(self.admin)
        students = self.client.get('/api/students/').json()
        self.assertEqual(students[0]['autopay']['status'], 'ACTIVE')
        profile = self.client.get(f'/api/sales/students/{student.pk}/initial-sale/').json()
        self.assertEqual(profile['autopay']['id'], str(agreement.pk))
        self.client.force_authenticate(self.other_bde)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        from .tests_lifecycle import account
        self.client.force_authenticate(account('autopay-mentor', 'MENTOR'))
        self.assertEqual(self.client.get(f'/api/sales/students/{student.pk}/initial-sale/').status_code, 403)

    def test_discount_replacement_required_and_token_sale_excluded(self):
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(60), 'offer_fee': D(50),
            'single_payment_percent': D(5), 'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': ''})
        old = quotes.latest_quote(self.lead)
        quotes.create_quote(self.bde, {'collection_mode': 'FULL', 'syllabus': self.bridge.pk, 'revision': 1, 'lead': self.lead.pk, 'plan_type': 'BRIDGE_COURSE', 'replaces': old.pk})
        self.start(); response = self.preview()
        self.assertEqual((response.status_code, response.json()['error']), (409, 'REPLACEMENT_REQUIRED'))
        self.lead = self.new_lead(collection_mode='PARTIAL'); self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        self.assertEqual(self.preview().status_code, 400)

    def test_all_successful_installments_settle_package_once_without_repricing(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
            services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(100), 'offer_fee': D(80),
                'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
            agreement = AutopayAgreement.objects.get()
            for row in agreement.installments.filter(position__gt=0):
                with mock.patch('sales.autopay.timezone.now', return_value=row.due_at + timedelta(seconds=1)): autopay.collect_due()
                event = self.future_event(charges[-1][2])
                self.assertEqual(self.webhook(event).status_code, 200)
                self.assertEqual(self.webhook(event).status_code, 200)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'COMPLETED')
        self.assertEqual([entry[0]['amount'] for entry in charges], [15000, 15000, 10000])
        self.assertEqual((Payment.objects.count(), Student.objects.count(), Student.objects.get().total_class_quota), (4, 1, D(10)))
        self.assertEqual(autopay.agreement_data(agreement)['remaining_amount'], '0')

    def test_initial_unpaid_invalid_signature_and_attachment_alone_never_enroll(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway): self.begin()
        payment = Payment.objects.get(); event = self.checkout_event(payment)
        self.assertEqual(self.webhook(event, valid=False).status_code, 400)
        event['data']['object']['payment_status'] = 'unpaid'
        self.assertEqual(self.webhook(event).status_code, 200)
        attachment = {'id': 'evt_attached_only', 'type': 'payment_method.attached', 'livemode': False,
            'data': {'object': {'id': 'pm_autopay', 'customer': 'cus_phase1', 'metadata': {}}}}
        self.assertEqual(self.webhook(attachment).status_code, 200)
        self.assertEqual((Student.objects.count(), AutopayAgreement.objects.get().setup_status), (0, 'PENDING'))

    def test_future_payment_mismatches_are_rejected_and_detached_methods_block_collection(self):
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway); agreement = AutopayAgreement.objects.get()
            first = agreement.installments.get(position=1)
            with mock.patch('sales.autopay.timezone.now', return_value=first.due_at + timedelta(seconds=1)): autopay.collect_due()
            for values in [{'amount': 100}, {'currency': 'usd'}, {'customer': 'cus_other'}, {'payment_method': 'pm_other'}, {'livemode': True}]:
                self.assertEqual(self.webhook(self.future_event(charges[0][2], **values)).status_code, 400)
            self.assertEqual(Student.objects.get().total_class_quota, D(2))
            event = {'id': 'evt_detached', 'type': 'payment_method.detached', 'livemode': False,
                'data': {'object': {'id': 'pm_autopay', 'metadata': {}}}}
            self.assertEqual(self.webhook(event).status_code, 200)
            agreement.refresh_from_db(); self.assertEqual(agreement.setup_status, 'INCOMPLETE')

    def test_incomplete_setup_can_reconcile_without_undoing_payment_or_granting_more_quota(self):
        import stripe
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin()
            gateway.v1.payment_methods.retrieve.side_effect = stripe.APIConnectionError('temporary test transport error')
            self.initial_paid(gateway)
            agreement = AutopayAgreement.objects.get()
            self.assertEqual((agreement.setup_status, Student.objects.get().total_class_quota), ('INCOMPLETE', D(2)))
            gateway.v1.payment_methods.retrieve.side_effect = None
            autopay.collect_due()
            agreement.refresh_from_db()
            self.assertEqual((agreement.setup_status, Student.objects.get().total_class_quota, len(charges)), ('READY', D(2), 0))

    def test_transport_reconciliation_reuses_attempt_and_idempotency_key(self):
        import stripe
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway)
            first = AutopayAgreement.objects.get().installments.get(position=1)
            create = gateway.v1.payment_intents.create.side_effect
            gateway.v1.payment_intents.create.side_effect = stripe.APIConnectionError('unconfirmed test transport')
            with mock.patch('sales.autopay.timezone.now', return_value=first.due_at + timedelta(seconds=1)):
                autopay.collect_due()
                first_key = gateway.v1.payment_intents.create.call_args.kwargs['options']['idempotency_key']
                gateway.v1.payment_intents.create.side_effect = create
                autopay.collect_due()
            second_key = gateway.v1.payment_intents.create.call_args.kwargs['options']['idempotency_key']
            self.assertEqual(first_key, second_key)
            self.assertEqual((first.attempts.count(), Payment.objects.count(), Student.objects.get().total_class_quota), (1, 2, D(2)))

    def test_initial_checkout_restart_keeps_one_payment_and_adds_an_auditable_attempt(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); payment = Payment.objects.get(); agreement = AutopayAgreement.objects.get()
            self.assertEqual(self.client.post(f'/api/sales/payments/{payment.pk}/expire/').status_code, 200)
            response = self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/', {'request_id': str(uuid.uuid4())}, format='json')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual((Payment.objects.count(), agreement.installments.get(position=0).attempts.count()), (1, 2))
            self.initial_paid(gateway)
        self.assertEqual((Student.objects.count(), Student.objects.get().total_class_quota), (1, D(2)))

    def test_future_attempt_history_shares_one_installment_and_one_payment(self):
        # Future policy can create another attempt under the same immutable allocation.
        # No retry scheduler is enabled or invoked by this data/lifecycle fixture.
        self.start(); gateway, _, charges = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.begin(); self.initial_paid(gateway); row = AutopayAgreement.objects.get().installments.get(position=1)
            with mock.patch('sales.autopay.timezone.now', return_value=row.due_at + timedelta(seconds=1)): autopay.collect_due()
            self.webhook(self.future_event(charges[0][2], kind='payment_intent.payment_failed', status='requires_payment_method', amount_received=0))
            first = row.attempts.get()
            row.refresh_from_db()
            second = AutopayAttempt.objects.create(installment=row, number=2, status='PENDING', stripe_payment_intent_id=first.stripe_payment_intent_id)
            result = {**charges[0][2], 'metadata': autopay.metadata(row.agreement, row, second.pk)}
            self.assertEqual(self.webhook(self.future_event(result)).status_code, 200)
        first.refresh_from_db()
        self.assertEqual((first.status, row.attempts.count(), Payment.objects.count(), Student.objects.get().total_class_quota), ('FAILED', 2, 2, D(5)))

    def test_schedule_and_attempt_origins_cannot_be_edited_or_deleted(self):
        self.start(); gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway): self.begin()
        agreement = AutopayAgreement.objects.get(); row = agreement.installments.get(position=1)
        for operation in [lambda: AutopayAgreement.objects.filter(pk=agreement.pk).update(billing_timezone='UTC'),
                          lambda: AutopayInstallment.objects.filter(pk=row.pk).update(amount=1),
                          lambda: AutopayAttempt.objects.all().update(number=10),
                          lambda: AutopayInstallment.objects.filter(pk=row.pk).delete()]:
            with self.assertRaises(DatabaseError), transaction.atomic(): operation()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    @override_settings(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET='', STRIPE_PUBLISHABLE_KEY='')
    def test_missing_configuration_allows_review_but_never_fakes_checkout(self):
        self.start()
        self.assertFalse(self.preview().json()['checkout_available'])
        self.assertEqual(self.begin().status_code, 503)
        self.assertEqual((Payment.objects.count(), AutopayAgreement.objects.count()), (0, 0))
