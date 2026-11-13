"""Database-free Checkout request contracts; Stripe transport and ORM are mocked."""
import copy
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs

import stripe
from django.test import SimpleTestCase, override_settings

from . import autopay_stripe, checkout
from .services import SalesError


@override_settings(SECRET_KEY='checkout-compatibility-tests-only', SECRET_KEY_FALLBACKS=[],
                   HUB_URL='https://hub.example.test', STRIPE_LIVE_MODE=False)
class CheckoutCompatibilityTests(SimpleTestCase):
    def setUp(self):
        self.account = SimpleNamespace(pk=uuid.uuid4(), reference='SA-000001', student_name='Fixture Student',
                                       student_id=None, student=None)
        self.sale = SimpleNamespace(pk=uuid.uuid4(), enquiry_id=uuid.uuid4(), account=self.account)
        self.purchase = SimpleNamespace(pk=uuid.uuid4(), sale=self.sale, sale_id=self.sale.pk, classes=Decimal('10'),
                                        quote_id=uuid.uuid4(), quote=SimpleNamespace(reference='Q-000001'))
        self.payment = SimpleNamespace(pk=uuid.uuid4(), sale=self.sale, purchase=self.purchase,
                                       purchase_id=self.purchase.pk, purpose='TUITION',
                                       amount=Decimal('100'), classes=Decimal('2'))
        self.initial = SimpleNamespace(pk=uuid.uuid4(), payment_id=self.payment.pk)
        self.agreement = SimpleNamespace(pk=self.payment.pk, purchase=self.purchase,
            installments=mock.Mock(), terms_url='https://terms.example.test/autopay',
            consent_text='Fixture consent for the reviewed instalment schedule.')
        self.agreement.installments.get.return_value = self.initial
        self.operation_model = self.enterContext(mock.patch.object(checkout, 'StripeCheckoutOperation'))
        self.customer_model = self.enterContext(mock.patch.object(checkout, 'StripeCustomer'))
        self.operation_model.objects.filter.return_value.first.return_value = None
        self.mapping = SimpleNamespace(customer_id='cus_compatibility_fixture', livemode=False)
        self.customer_model.objects.filter.return_value.first.return_value = self.mapping
        self.operation_model.objects.create.side_effect = lambda **fields: SimpleNamespace(
            **fields, payment_id=fields['payment'].pk)
        # Django supplies the billing contact and the student's Customer row.
        self.guardian = SimpleNamespace(pk=uuid.uuid4(), full_name='Fixture Parent', email='parent@fixture.test')
        self.enterContext(mock.patch('sales.student_accounts.billing_guardian', return_value=self.guardian))
        self.prepared = self.enterContext(mock.patch('sales.customers.prepared_mapping', return_value=self.mapping))

    def test_initial_request_is_card_only_and_preserves_consent_and_off_session_setup(self):
        operation = checkout.prepare(self.payment, agreement=self.agreement)
        params = operation.request
        self.assertEqual(params['allowed_payment_method_types'], ['card'])
        self.assertNotIn('payment_method_types', params)
        self.assertEqual(params['wallet_options'], {'link': {'display': 'never'}})
        self.assertEqual(params['consent_collection'], {
            'terms_of_service': 'required', 'payment_method_reuse_agreement': {'position': 'auto'}})
        self.assertEqual(params['payment_intent_data']['setup_future_usage'], 'off_session')
        self.assertIn(self.agreement.terms_url, params['custom_text']['terms_of_service_acceptance']['message'])
        self.assertIn(self.agreement.consent_text, params['custom_text']['terms_of_service_acceptance']['message'])
        self.assertEqual(params['line_items'][0]['price_data']['unit_amount'], 10000)
        self.assertEqual(params['line_items'][0]['price_data']['currency'], 'aed')
        self.customer_model.objects.create.assert_not_called()

    def test_official_sdk_wire_request_uses_supported_card_filter_and_existing_customer(self):
        class Transport(stripe.HTTPClient):
            name = 'checkout-compatibility-fixture'

            def __init__(self):
                super().__init__()
                self.calls = []

            def request(self, method, url, headers, post_data=None, **kwargs):
                body = post_data.decode() if isinstance(post_data, bytes) else post_data
                self.calls.append((method, url, headers, parse_qs(body)))
                return json.dumps({'id': 'cs_fixture_only', 'object': 'checkout.session'}), 200, {}

        operation = checkout.prepare(self.payment, agreement=self.agreement)
        transport = Transport()
        client = stripe.StripeClient('sk_test_unit_only', http_client=transport, max_network_retries=0)
        client.v1.checkout.sessions.create({**operation.request, 'customer': self.mapping.customer_id},
            options={'idempotency_key': operation.idempotency_key})
        self.assertEqual(len(transport.calls), 1)
        _, url, headers, params = transport.calls[0]
        self.assertTrue(url.endswith('/v1/checkout/sessions'))
        self.assertEqual(params['allowed_payment_method_types[0]'], ['card'])
        self.assertNotIn('payment_method_types[0]', params)
        self.assertEqual(params['payment_intent_data[setup_future_usage]'], ['off_session'])
        self.assertEqual(params['consent_collection[terms_of_service]'], ['required'])
        self.assertEqual(params['customer'], [self.mapping.customer_id])
        self.assertEqual(params['line_items[0][price_data][unit_amount]'], ['10000'])
        self.assertEqual(headers['Idempotency-Key'], operation.idempotency_key)

    def test_existing_historical_request_is_returned_without_rewriting_it(self):
        operation_id = uuid.uuid4()
        historical = SimpleNamespace(pk=operation_id, payment_id=self.payment.pk,
            request={'payment_method_types': ['card'], 'mode': 'payment'}, status='ERROR',
            livemode=False, message='Fixture: rejected historical request requires explicit review.')
        original = copy.deepcopy(historical.request)
        self.operation_model.objects.filter.return_value.first.return_value = historical
        result = checkout.prepare(self.payment, agreement=self.agreement, attempt_id=operation_id)
        self.assertIs(result, historical)
        self.assertEqual(historical.request, original)
        self.operation_model.objects.create.assert_not_called()
        self.customer_model.objects.filter.assert_not_called()
        self.operation_model.objects.select_related.return_value.get.return_value = historical
        with mock.patch('sales.stripe_gateway.client') as client:
            with self.assertRaises(SalesError) as rejected:
                checkout.fulfill(operation_id)
        self.assertEqual((rejected.exception.code, rejected.exception.http_status), ('CHECKOUT_REVIEW_REQUIRED', 409))
        client.assert_not_called()
        self.assertEqual(historical.request, original)

    def test_explicit_replacement_preparation_uses_new_filter_and_keeps_frozen_origin(self):
        original_id, replacement_id = uuid.uuid4(), uuid.uuid4()
        historical_request = autopay_stripe.checkout_options(self.agreement, self.payment, original_id)
        historical_request['payment_method_types'] = historical_request.pop('allowed_payment_method_types')
        frozen = copy.deepcopy(historical_request)
        replacement = checkout.prepare(self.payment, agreement=self.agreement, attempt_id=replacement_id)
        self.assertEqual(replacement.request['allowed_payment_method_types'], ['card'])
        self.assertNotIn('payment_method_types', replacement.request)
        self.assertEqual(replacement.request['metadata']['attempt_id'], str(replacement_id))
        self.assertEqual(replacement.request['metadata']['checkout_operation_id'], str(replacement_id))
        self.assertEqual(replacement.idempotency_key, f'eduport-checkout-operation-{replacement_id}')
        self.assertIs(replacement.payment, self.payment)
        self.assertEqual(historical_request, frozen)
        self.customer_model.objects.create.assert_not_called()
