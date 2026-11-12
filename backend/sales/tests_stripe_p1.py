"""P1 regression cases, prepared but NOT executed. All provider IO is mocked.

Transaction tests allow the Checkout mock to assert that local origins really
committed before provider dispatch. No account credentials or broker are used.
"""
import copy
import uuid
from datetime import timedelta
from unittest import mock

import stripe
from django.db import connection, DatabaseError, transaction
from django.test import override_settings, SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from invitations.models import Invitation
from students.models import Student
from . import autopay, billing, checkout, tests_autopay as auto_helpers, tests_billing as billing_helpers
from . import tests_payments as initial_helpers
from .autopay_models import AutopayAgreement
from .payment_models import Payment, Purchase, StripeCheckoutOperation, StripeCustomer
from .stripe_gateway import is_definitive_rejection
from .tests_quotes import QuoteTestCase
from .services import SalesError


class RejectionClassificationTests(SimpleTestCase):
    def test_an_inflight_or_unclassified_failure_is_not_a_definitive_rejection(self):
        for status, code, expected in [(400, 'parameter_invalid', True), (409, 'idempotency_key_in_use', False),
                                       (400, 'lock_timeout', False), (None, None, False)]:
            with self.subTest(status=status, code=code):
                error = stripe.InvalidRequestError('fixture only', 'phases', code=code, http_status=status)
                self.assertEqual(is_definitive_rejection(error), expected)


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only',
    STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
    AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai',
    LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class StripeP1Tests(QuoteTestCase, APITransactionTestCase):
    new_lead = auto_helpers.AutopayTests.new_lead
    url = auto_helpers.AutopayTests.url
    start = auto_helpers.AutopayTests.start
    webhook = auto_helpers.AutopayTests.webhook
    schedule = auto_helpers.AutopayTests.schedule
    preview = auto_helpers.AutopayTests.preview
    checkout_event = auto_helpers.AutopayTests.checkout_event
    initial_paid = auto_helpers.AutopayTests.initial_paid
    ready = billing_helpers.BillingTests.ready
    provisioned = billing_helpers.BillingTests.provisioned

    def setUp(self):
        initial_helpers.InitialPaymentTests.setUp(self)
        self.review_tokens = {}
        queued = mock.patch('sales.tasks.provision_billing_subscription.delay')
        queued.start()
        self.addCleanup(queued.stop)

    def begin(self, data=None, request_id=None):
        data, request_id = data or self.schedule(), request_id or uuid.uuid4()
        key = str(request_id)
        if key not in self.review_tokens:
            reviewed = self.preview(data)
            self.assertEqual(reviewed.status_code, 200, reviewed.content)
            self.review_tokens[key] = reviewed.json()['review_token']
        return self.client.post(self.url('autopay/'), {**data, 'request_id': key,
            'review_token': self.review_tokens[key]}, format='json')

    def lost_checkout(self):
        self.start()
        gateway, _, _ = auto_helpers.AutopayTests.transport(self)
        original = gateway.v1.checkout.sessions.create.side_effect
        requests, remote = [], {}
        def create(params, options):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual((Payment.objects.count(), Purchase.objects.count(), AutopayAgreement.objects.count()), (1, 1, 1))
            operation = StripeCheckoutOperation.objects.get()
            self.assertEqual(operation.request, {k: v for k, v in params.items() if k != 'customer'})
            requests.append((copy.deepcopy(params), copy.deepcopy(options)))
            if not remote:
                remote.update(original(params, options))
                raise stripe.APIConnectionError('fixture response lost after remote creation')
            return copy.deepcopy(remote)  # fake provider's idempotent replay
        gateway.v1.checkout.sessions.create.side_effect = create
        gateway.v1.checkout.sessions.list.return_value = billing_helpers.page([])
        frozen = self.schedule()
        request_id = uuid.uuid4()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.begin(frozen, request_id)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(StripeCheckoutOperation.objects.get().status, 'UNKNOWN')
        self.assertFalse(Student.objects.exists())
        return gateway, frozen, request_id, requests, remote

    def test_lost_response_keeps_durable_identifiers_and_exact_request_across_retries(self):
        gateway, frozen, request_id, requests, _ = self.lost_checkout()
        ids = list(AutopayAgreement.objects.get().installments.values_list('pk', flat=True))
        self.lead.parent_name = 'Changed after the first request'
        self.lead.save(update_fields=['parent_name'])
        with override_settings(HUB_URL='https://changed-hub.example.test'), mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.begin(frozen, request_id)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(ids, list(AutopayAgreement.objects.get().installments.values_list('pk', flat=True)))
        self.assertEqual((Payment.objects.count(), StripeCheckoutOperation.objects.count()), (1, 1))
        self.assertEqual(gateway.v1.customers.create.call_count, 1)

    def test_existing_remote_session_is_adopted_without_another_create(self):
        gateway, _, _, _, remote = self.lost_checkout()
        gateway.v1.checkout.sessions.list.return_value = billing_helpers.page([remote])
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            checkout.reconcile_pending()
        self.assertEqual(StripeCheckoutOperation.objects.get().stripe_checkout_id, remote['id'])
        self.assertEqual(gateway.v1.checkout.sessions.create.call_count, 1)
        self.assertFalse(Student.objects.exists())

    def test_signed_success_can_bind_a_lost_response_and_enroll_exactly_once(self):
        gateway, _, _, _, remote = self.lost_checkout()
        payment = Payment.objects.get()
        intent_id = f'pi_{payment.pk.hex}'
        gateway.v1.payment_intents.retrieve.return_value = {'id': intent_id, 'status': 'succeeded', 'customer': 'cus_phase1',
            'currency': 'aed', 'amount_received': int(payment.amount) * 100, 'setup_future_usage': 'off_session',
            'payment_method': 'pm_autopay', 'livemode': False}
        event = {'id': 'evt_lost_checkout_paid', 'type': 'checkout.session.completed', 'livemode': False,
            'data': {'object': {**remote, 'payment_status': 'paid', 'payment_intent': intent_id,
                                'consent': {'terms_of_service': 'accepted'}}}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event).status_code, 200)
            self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual((Student.objects.count(), Invitation.objects.count(), Payment.objects.count()), (1, 1, 1))
        self.assertEqual(Student.objects.get().total_class_quota, 2)
        self.assertEqual(StripeCustomer.objects.get().customer_id, 'cus_phase1')

    def test_unknown_expired_checkout_does_not_issue_a_fresh_request(self):
        gateway, _, _, _, _ = self.lost_checkout()
        operation = StripeCheckoutOperation.objects.get()
        with mock.patch('sales.checkout.timezone.now', return_value=operation.started_at + timedelta(hours=25)), mock.patch('sales.stripe_gateway.client', return_value=gateway):
            checkout.reconcile_pending()
        self.assertEqual(gateway.v1.checkout.sessions.create.call_count, 1)
        self.assertEqual(StripeCheckoutOperation.objects.get().status, 'REQUIRES_REVIEW')

    def test_explicit_replacement_corrects_card_parameter_without_rewriting_failed_history(self):
        from . import autopay_stripe
        self.assertEqual(self.start().status_code, 201)
        gateway, _, _ = auto_helpers.AutopayTests.transport(self)
        create = gateway.v1.checkout.sessions.create.side_effect
        options = autopay_stripe.checkout_options

        def historical_options(*args, **kwargs):
            params = options(*args, **kwargs)
            params['payment_method_types'] = params.pop('allowed_payment_method_types')
            return params

        gateway.v1.checkout.sessions.create.side_effect = stripe.InvalidRequestError(
            'fixture: unsupported Checkout parameter', 'payment_method_types', http_status=400)
        schedule, request_id = self.schedule(), uuid.uuid4()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway), mock.patch(
                'sales.autopay_stripe.checkout_options', side_effect=historical_options):
            rejected = self.begin(schedule, request_id)
        self.assertEqual((rejected.status_code, rejected.json()['error']), (409, 'STRIPE_CHECKOUT_REJECTED'))
        original = StripeCheckoutOperation.objects.get()
        frozen_operation = copy.deepcopy(StripeCheckoutOperation.objects.values().get(pk=original.pk))
        from .autopay_models import AutopayAttempt
        frozen_attempt = copy.deepcopy(AutopayAttempt.objects.values().get(pk=original.pk))
        agreement = AutopayAgreement.objects.get()
        payment = Payment.objects.get()
        purchase_id = payment.purchase_id
        customer_id = StripeCustomer.objects.get().customer_id

        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            replay = self.begin(schedule, request_id)
            self.assertEqual((replay.status_code, replay.json()['error']), (409, 'CHECKOUT_REVIEW_REQUIRED'))
            self.assertEqual(gateway.v1.checkout.sessions.create.call_count, 1)
            gateway.v1.checkout.sessions.create.side_effect = create
            replacement_id = uuid.uuid4()
            response = self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/',
                {'request_id': str(replacement_id)}, format='json')
            self.assertEqual(response.status_code, 200, response.content)
            replay = self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/',
                {'request_id': str(replacement_id)}, format='json')
            self.assertEqual(replay.status_code, 200, replay.content)
            self.assertEqual(gateway.v1.checkout.sessions.create.call_count, 2)
        self.assertEqual(response.status_code, 200, response.content)
        replacement = StripeCheckoutOperation.objects.get(pk=replacement_id)
        self.assertEqual(replacement.request['allowed_payment_method_types'], ['card'])
        self.assertNotIn('payment_method_types', replacement.request)
        dispatched = gateway.v1.checkout.sessions.create.call_args.args[0]
        self.assertEqual(dispatched['allowed_payment_method_types'], ['card'])
        self.assertNotIn('payment_method_types', dispatched)
        self.assertEqual(dispatched['customer'], customer_id)
        self.assertEqual(StripeCheckoutOperation.objects.values().get(pk=original.pk), frozen_operation)
        self.assertEqual(AutopayAttempt.objects.values().get(pk=original.pk), frozen_attempt)
        self.assertEqual((Payment.objects.count(), Purchase.objects.count(), StripeCustomer.objects.count()), (1, 1, 1))
        self.assertEqual((StripeCheckoutOperation.objects.count(), AutopayAttempt.objects.count()), (2, 2))
        payment.refresh_from_db()
        self.assertEqual(payment.purchase_id, purchase_id)
        self.assertEqual(gateway.v1.customers.create.call_count, 1)
        self.assertFalse(Student.objects.exists())

    def test_customer_response_loss_reuses_its_frozen_body_and_identity(self):
        self.start()
        gateway, _, _ = auto_helpers.AutopayTests.transport(self)
        sent, remote = [], {}
        def customer(params, options):
            self.assertFalse(connection.in_atomic_block)
            sent.append((copy.deepcopy(params), copy.deepcopy(options)))
            if not remote:
                remote.update({'id': 'cus_phase1', 'livemode': False, **params})
                raise stripe.APIConnectionError('fixture Customer response lost')
            return copy.deepcopy(remote)
        gateway.v1.customers.create.side_effect = customer
        gateway.v1.customers.list.return_value = billing_helpers.page([])
        data, request_id = self.schedule(), uuid.uuid4()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.begin(data, request_id).status_code, 503)
            self.assertIsNone(StripeCustomer.objects.get().customer_id)
            self.lead.parent_name = 'A changed parent label'
            self.lead.save(update_fields=['parent_name'])
            self.assertEqual(self.begin(data, request_id).status_code, 201)
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(StripeCustomer.objects.count(), 1)

    def test_checkout_request_and_bound_customer_are_immutable(self):
        agreement, _ = self.ready()
        operation = StripeCheckoutOperation.objects.get()
        for model, filters, changes in [
            (StripeCheckoutOperation, {'pk': operation.pk}, {'request': {}}),
            (StripeCustomer, {'enquiry_id': self.lead.pk}, {'customer_id': 'cus_other'}),
        ]:
            with self.subTest(changes=changes), self.assertRaises(DatabaseError), transaction.atomic():
                model.objects.filter(**filters).update(**changes)

    def test_current_subscription_card_is_used_and_detached_replacement_never_falls_back_to_initial(self):
        agreement, gateway, subscription = self.provisioned()
        subscription['default_payment_method'] = 'pm_replacement'
        initial = copy.deepcopy(gateway.v1.payment_methods.retrieve.return_value)
        replacement = {'id': 'pm_replacement', 'customer': 'cus_phase1',
            'livemode': False, 'type': 'card', 'card': {'country': 'US', 'last4': '4444', 'brand': 'visa'}}
        gateway.v1.payment_methods.retrieve.side_effect = lambda method_id: copy.deepcopy(
            replacement if method_id == 'pm_replacement' else initial)
        gateway.v1.payment_intents.retrieve.reset_mock()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            from .autopay_stripe import refresh_setup
            refresh_setup(agreement.pk)
            agreement.refresh_from_db()
            self.assertEqual((agreement.stripe_payment_method_id, agreement.setup_status), ('pm_replacement', 'READY'))
            replacement['customer'] = None
            refresh_setup(agreement.pk)
        agreement.refresh_from_db()
        self.assertEqual((agreement.stripe_payment_method_id, agreement.setup_status), ('pm_replacement', 'INCOMPLETE'))
        gateway.v1.payment_intents.retrieve.assert_not_called()
        self.assertEqual(Student.objects.get().total_class_quota, 2)

    def test_not_started_schedule_uses_its_current_default_card(self):
        agreement, gateway = self.ready()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            remote = gateway.v1.subscription_schedules.retrieve.return_value
            remote['default_settings']['default_payment_method'] = 'pm_schedule_current'
            gateway.v1.payment_methods.retrieve.return_value = {'id': 'pm_schedule_current', 'type': 'card',
                'customer': 'cus_phase1', 'livemode': False, 'card': {'country': 'US', 'brand': 'visa', 'last4': '4444'}}
            gateway.v1.payment_intents.retrieve.reset_mock()
            from .autopay_stripe import refresh_setup
            refresh_setup(agreement.pk)
        agreement.refresh_from_db()
        self.assertEqual(agreement.stripe_payment_method_id, 'pm_schedule_current')
        gateway.v1.payment_intents.retrieve.assert_not_called()

    def test_explicit_recovery_uses_new_generation_only_after_verified_rejection(self):
        agreement, gateway = self.ready()
        create = gateway.v1.subscription_schedules.create.side_effect
        gateway.v1.subscription_schedules.create.side_effect = stripe.InvalidRequestError(
            'fixture rejection', 'phases', http_status=400, code='parameter_invalid')
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            first_key = gateway.v1.subscription_schedules.create.call_args.kwargs['options']['idempotency_key']
            agreement.refresh_from_db()
            self.assertEqual((agreement.billing_status, agreement.provisioning_rejection_verified), ('ERROR', True))
            billing.provision_ready()
            self.assertEqual(gateway.v1.subscription_schedules.create.call_count, 1)
            gateway.v1.subscription_schedules.create.side_effect = create
            billing.provision(agreement.pk, recover=True)
            recovered_key = gateway.v1.subscription_schedules.create.call_args.kwargs['options']['idempotency_key']
        agreement.refresh_from_db()
        self.assertNotEqual(first_key, recovered_key)
        self.assertEqual((agreement.billing_status, agreement.billing_issue_scope, agreement.provisioning_generation), ('PROVISIONED', '', 1))
        billing.problem(agreement.pk, 'fixture late error from generation zero', 'ERROR',
                        scope='PROVISIONING', generation=0, unbound=True)
        agreement.refresh_from_db()
        self.assertEqual(agreement.billing_status, 'PROVISIONED')
        self.assertEqual(gateway.v1.payment_intents.create.call_count, 0)

    def test_unknown_expired_provisioning_stays_manual_even_with_recover(self):
        agreement, gateway = self.ready()
        gateway.v1.subscription_schedules.create.side_effect = stripe.APIConnectionError('fixture uncertain outcome')
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            agreement.refresh_from_db()
            with mock.patch('sales.billing.timezone.now', return_value=agreement.provisioning_started_at + timedelta(hours=25)):
                billing.provision(agreement.pk, recover=True)
        agreement.refresh_from_db()
        self.assertEqual((agreement.billing_status, agreement.provisioning_generation), ('REQUIRES_REVIEW', 0))
        self.assertEqual(gateway.v1.subscription_schedules.create.call_count, 1)

    def test_recovery_adopts_existing_schedule_before_any_new_create(self):
        agreement, gateway = self.ready()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            remote = gateway.v1.subscription_schedules.retrieve.return_value
            billing.problem(agreement.pk, 'fixture stale provisioning flag', 'ERROR', scope='PROVISIONING')
            gateway.v1.subscription_schedules.list.return_value = billing_helpers.page([remote])
            billing.provision(agreement.pk, recover=True)
        agreement.refresh_from_db()
        self.assertEqual(agreement.billing_status, 'PROVISIONED')
        self.assertEqual(gateway.v1.subscription_schedules.create.call_count, 1)

    def test_provisioning_recovery_does_not_clear_invoice_review(self):
        agreement, gateway, _ = self.provisioned()
        billing.problem(agreement.pk, 'fixture invoice mismatch', scope='RECONCILIATION')
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            with self.assertRaises(SalesError) as refused:
                billing.provision(agreement.pk, recover=True)
        self.assertEqual(refused.exception.code, 'UNRELATED_REVIEW')
        agreement.refresh_from_db()
        self.assertEqual(agreement.billing_issue_scope, 'RECONCILIATION')
