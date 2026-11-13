"""Native Billing regression scenarios. Prepared only; not executed for this change.

All Stripe transport is mocked. These tests must never use account credentials.
"""
import copy
import uuid
from datetime import datetime, timedelta, timezone as utc
from decimal import Decimal as D
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from students.models import Student
from . import autopay, billing, services, tests_autopay as helpers, tests_payments as initial_helpers
from .autopay_models import AutopayAgreement, AutopayAttempt
from .ledger_models import StripeReviewItem
from .payment_models import Payment, StripeEvent
from .services import SalesError
from .tests_quotes import QuoteTestCase


def page(rows):
    return SimpleNamespace(auto_paging_iter=lambda: iter(rows))


class BillingPhaseTests(SimpleTestCase):
    def test_irregular_dates_are_exact_and_each_price_covers_its_entire_phase(self):
        start = datetime(2028, 1, 31, 6, tzinfo=utc.utc)
        rows = [{'id': str(uuid.uuid4()), 'position': i + 1, 'amount': amount, 'due_at': due}
                for i, (due, amount) in enumerate([(start, '33'), (start + timedelta(days=7), '34'),
                                                   (start + timedelta(days=80), '33')])]
        terms = billing.phase_terms(rows)
        self.assertEqual([r['amount'] for r in terms], [3300, 3400, 3300])
        self.assertEqual([r['start'] for r in terms], [int(r['due_at'].timestamp()) for r in rows])
        for index, term in enumerate(terms):
            self.assertGreaterEqual(billing.month_after(rows[index]['due_at'], term['months']).timestamp(), term['end'])
            if index < len(terms) - 1:
                self.assertEqual(term['end'], terms[index + 1]['start'])

    def test_unsupported_native_terms_are_rejected_before_any_money_is_collected(self):
        due = timezone.now() + timedelta(days=10)
        row = {'position': 1, 'amount': '2', 'due_at': due}
        for rows in [[], [dict(row, amount='1')], [dict(row, amount='2.5')],
                     [row, dict(row, position=2)],
                     [dict(row, position=n + 1, due_at=due + timedelta(days=n)) for n in range(11)],
                     [row, dict(row, position=2, due_at=billing.month_after(due, 37))]]:
            with self.subTest(rows=rows), self.assertRaises(SalesError):
                billing.phase_terms(rows)

    def test_malformed_remote_internal_identifiers_are_not_database_queries(self):
        for value in [None, '', 'not-an-internal-uuid', 'sub_remote']:
            self.assertIsNone(billing.internal_id(value))


def recorded_schedule():
    """A schedule as Stripe Test held it on 2026-11-13, references replaced: four
    monthly phases from 07:00:00 UTC, AED 350 then three of AED 700, provisioned and not yet started."""
    agreement = SimpleNamespace(pk=uuid.UUID(int=1), purchase_id=uuid.UUID(int=2), purchase=SimpleNamespace(quote_id=uuid.UUID(int=3)),
                                schedule_digest='recorded-digest', stripe_customer_id='cus_recorded', livemode=False)
    common = billing.metadata(agreement)
    instant = lambda *args: int(datetime(*args, tzinfo=utc.utc).timestamp())
    terms = [(instant(2026, 12, 12, 7, 11), 35000), (instant(2027, 1, 12, 7, 11), 70000),
             (instant(2027, 2, 12, 7, 11), 70000), (instant(2027, 3, 12, 7, 11), 70000)]
    agreement.billing_request = {'start_date': instant(2026, 11, 13, 7), 'end_behavior': 'cancel', 'metadata': common, 'phases': [
        {'end_date': end, 'metadata': {**common, 'installment_id': f'installment-{n}', 'installment_position': str(n)},
         'items': [{'quantity': 1, 'price_data': {'currency': 'aed', 'product': 'prod_recorded', 'unit_amount': amount,
                                                  'recurring': {'interval': 'month', 'interval_count': 1}}}]}
        for n, (end, amount) in enumerate(terms, start=1)]}
    request = agreement.billing_request
    phases = [{'start_date': request['start_date'] if index == 0 else request['phases'][index - 1]['end_date'],
               'end_date': phase['end_date'], 'metadata': dict(phase['metadata']), 'billing_cycle_anchor': 'phase_start',
               'proration_behavior': 'none', 'discounts': [], 'default_tax_rates': [], 'automatic_tax': {'enabled': False},
               'items': [{'quantity': 1, 'price': {'id': f'price_recorded_{index}', **phase['items'][0]['price_data']}}]}
              for index, phase in enumerate(request['phases'])]
    remote = {'id': 'sub_sched_recorded', 'customer': 'cus_recorded', 'livemode': False, 'metadata': dict(common),
              'status': 'not_started', 'end_behavior': 'cancel', 'current_phase': None, 'subscription': None, 'phases': phases}
    return agreement, remote


def running(remote, index=0, moved=0):
    """``remote`` in phase ``index``, which Stripe restarted ``moved`` seconds after its agreed start."""
    remote = copy.deepcopy(remote)
    remote.update(status='active', subscription='sub_recorded')
    remote['phases'][index]['start_date'] += moved
    remote['current_phase'] = {key: remote['phases'][index][key] for key in ('start_date', 'end_date')}
    return remote


class ScheduleValidationTests(SimpleTestCase):
    """Stripe restarts a running phase when its subscription is updated; nothing else may move."""

    def setUp(self):
        self.agreement, self.remote = recorded_schedule()

    def refused(self, remote, message=billing.SCHEDULE_DATES_DIFFER):
        with self.assertRaisesMessage(ValueError, message):
            billing._validate_schedule(self.agreement, remote)

    def test_the_recorded_card_settings_update_moves_the_started_phase_19_seconds_later(self):
        billing._validate_schedule(self.agreement, self.remote)  # As provisioned.
        billing._validate_schedule(self.agreement, running(self.remote))  # Phase 1 starts on time.
        # 07:00:00 -> 07:00:19: Django set the new subscription's card options and Stripe restarted the phase.
        recorded = running(self.remote, moved=19)
        billing._validate_schedule(self.agreement, recorded)
        # Later transitions keep the completed phase's later start; a phase running now may be restarted too.
        later = running(recorded, index=1)
        later['phases'][0]['start_date'] = recorded['phases'][0]['start_date']
        billing._validate_schedule(self.agreement, later)
        billing._validate_schedule(self.agreement, running(later, index=1, moved=5))
        # A schedule stopped after that restart (an Admin cancellation) still reconciles.
        stopped = {**recorded, 'status': 'canceled', 'current_phase': None, 'canceled_at': recorded['phases'][0]['start_date'] + 3600}
        billing._validate_schedule(self.agreement, stopped)

    def test_a_started_phase_never_starts_earlier_than_agreed(self):
        self.refused(running(self.remote, moved=-19))

    def test_a_started_phase_cannot_start_at_or_after_its_own_end(self):
        window = self.remote['phases'][0]['end_date'] - self.remote['phases'][0]['start_date']
        for moved in (window, window + 60):
            with self.subTest(moved=moved):
                self.refused(running(self.remote, moved=moved))

    def test_end_dates_stay_exact(self):
        for index in (0, 2):
            remote = running(self.remote, moved=19)
            remote['phases'][index]['end_date'] += 60
            if index + 1 < len(remote['phases']):
                remote['phases'][index + 1]['start_date'] += 60
            if index == 0:
                remote['current_phase']['end_date'] += 60
            with self.subTest(phase=index):
                self.refused(remote)

    def test_phases_yet_to_start_and_unstarted_schedules_stay_exact(self):
        future = running(self.remote, moved=19)
        future['phases'][1]['start_date'] += 60
        self.refused(future)
        unstarted = copy.deepcopy(self.remote)
        unstarted['phases'][0]['start_date'] += 19
        self.refused(unstarted)
        early_stop = {**running(self.remote, moved=19), 'status': 'canceled', 'current_phase': None,
                      'canceled_at': self.remote['phases'][0]['start_date'] + 10}
        self.refused(early_stop)

    def test_the_moved_start_must_be_stripes_current_phase(self):
        disagreeing = running(self.remote, moved=19)
        disagreeing['current_phase']['start_date'] -= 10
        self.refused(disagreeing)
        unknown = running(self.remote, moved=19)
        unknown['current_phase']['end_date'] += 1
        self.refused(unknown)

    def test_everything_else_stays_strict_after_a_restart(self):
        pricing = 'Stripe phase pricing differs from the frozen installment.'
        cases = [
            (lambda r: r['phases'][0]['metadata'].update(installment_id='installment-9'), billing.SCHEDULE_DATES_DIFFER),
            (lambda r: r['phases'][2]['metadata'].update(installment_position='7'), billing.SCHEDULE_DATES_DIFFER),
            (lambda r: r['phases'][0]['items'][0]['price'].update(unit_amount=35100), pricing),
            (lambda r: r['phases'][1]['items'][0]['price'].update(product='prod_other'), pricing),
            (lambda r: r['phases'][0]['items'][0]['price']['recurring'].update(interval_count=2), pricing),
            (lambda r: r['phases'][0].update(proration_behavior='create_prorations'), pricing),
            (lambda r: r.update(end_behavior='release'), 'Stripe schedule phases do not match the frozen provisioning request.'),
            (lambda r: r['phases'].pop(), 'Stripe schedule phases do not match the frozen provisioning request.'),
            (lambda r: r.update(customer='cus_other'), 'Stripe schedule does not match this agreement, Customer and environment.'),
        ]
        for index, (change, message) in enumerate(cases):
            remote = running(self.remote, moved=19)
            change(remote)
            with self.subTest(case=index):
                self.refused(remote, message)


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only',
    STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
    AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai',
    LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class BillingTests(QuoteTestCase, APITestCase):
    setUp = initial_helpers.InitialPaymentTests.setUp
    new_lead = helpers.AutopayTests.new_lead
    url = helpers.AutopayTests.url
    start = helpers.AutopayTests.start
    webhook = helpers.AutopayTests.webhook
    schedule = helpers.AutopayTests.schedule
    preview = helpers.AutopayTests.preview
    begin = helpers.AutopayTests.begin
    checkout_event = helpers.AutopayTests.checkout_event
    initial_paid = helpers.AutopayTests.initial_paid

    def ready(self, engine=billing.ENGINE):
        self.assertEqual(self.start().status_code, 201)
        gateway, _, _ = helpers.AutopayTests.transport(self)
        gateway.v1.subscription_schedules.list.return_value = page([])
        gateway.v1.charges.list.return_value = page([])
        with mock.patch('sales.stripe_gateway.client', return_value=gateway), mock.patch('sales.autopay.DEFAULT_COLLECTION_ENGINE', engine):
            self.assertEqual(self.begin().status_code, 201)
            self.initial_paid(gateway)
        agreement = AutopayAgreement.objects.select_related('purchase__sale').get()
        self.assertEqual(agreement.collection_engine, engine)
        self.assertEqual(Student.objects.get().total_class_quota, 2)
        def create(request, options):
            phases = []
            for index, row in enumerate(request['phases']):
                phase = copy.deepcopy(row)
                phase['start_date'] = request['start_date'] if index == 0 else request['phases'][index - 1]['end_date']
                item = phase['items'][0]
                item['price'] = item.pop('price_data')
                phases.append(phase)
            remote = {'id': 'sub_sched_native', 'subscription': None, 'customer': agreement.stripe_customer_id,
                    'livemode': False, 'status': 'not_started', 'metadata': billing.metadata(agreement),
                    'default_settings': copy.deepcopy(request['default_settings']), 'phases': phases, 'end_behavior': 'cancel'}
            gateway.v1.subscription_schedules.retrieve.return_value = remote
            return remote
        gateway.v1.subscription_schedules.create.side_effect = create
        return agreement, gateway

    def provisioned(self):
        agreement, gateway = self.ready()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
        agreement.refresh_from_db()
        self.assertEqual(agreement.billing_status, 'PROVISIONED')
        agreement.stripe_subscription_id = 'sub_native'
        agreement.save(update_fields=['stripe_subscription_id'])
        subscription = {'id': 'sub_native', 'schedule': agreement.stripe_schedule_id,
            'metadata': billing.metadata(agreement), 'customer': agreement.stripe_customer_id,
            'livemode': False, 'status': 'active', 'default_payment_method': 'pm_autopay',
            'payment_settings': {'save_default_payment_method': 'on_subscription'}}
        gateway.v1.subscriptions.retrieve.return_value = subscription
        return agreement, gateway, subscription

    def invoice(self, agreement, row, status='paid', amount=None):
        amount = int(row.amount) * 100 if amount is None else amount
        return {'id': f'in_native_{row.position}', 'customer': agreement.stripe_customer_id, 'livemode': False,
            'currency': 'aed', 'total': amount, 'subtotal': amount, 'amount_due': amount, 'starting_balance': 0,
            'status': status, 'number': f'EDP-{row.position}', 'hosted_invoice_url': 'https://invoice.stripe.com/i/native',
            'attempt_count': 1, 'parent': {'subscription_details': {'subscription': 'sub_native',
                'metadata': {**billing.metadata(agreement), 'installment_id': str(row.pk)}}},
            'lines': {'has_more': False, 'data': [{'amount': amount, 'quantity': 1,
                'period': {'start': int(row.due_at.timestamp())}, 'parent': {'subscription_item_details': {'proration': False}}}]}}

    def deliver(self, agreement, gateway, row, kind='invoice.paid', status='paid', amount=None, intent_status='succeeded'):
        invoice = self.invoice(agreement, row, status, amount)
        intent = {'id': f'pi_invoice_{row.position}', 'customer': agreement.stripe_customer_id, 'livemode': False,
            'currency': 'aed', 'amount_received': int(row.amount) * 100, 'status': intent_status,
            'latest_charge': f'ch_invoice_{row.position}', 'last_payment_error': None}
        if intent_status == 'requires_action':
            intent['last_payment_error'] = {'code': 'authentication_required'}
        gateway.v1.invoices.retrieve.return_value = invoice
        gateway.v1.invoice_payments.list.return_value = page([{'id': f'inpay_{row.position}', 'status': 'paid' if status == 'paid' else 'open',
            'amount_paid': int(row.amount) * 100, 'payment': {'type': 'payment_intent', 'payment_intent': intent}}])
        # The expanded PI is used for paid invoices; failures retrieve its ID.
        gateway.v1.payment_intents.retrieve.return_value = intent
        event = {'id': f'evt_{uuid.uuid4().hex}', 'livemode': False, 'type': kind, 'data': {'object': invoice}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.webhook(event)
        self.assertEqual(response.status_code, 200, response.content)
        return event

    def test_initial_checkout_is_preserved_and_native_provisioning_is_idempotent(self):
        agreement, gateway = self.ready()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            billing.provision(agreement.pk)
            autopay.collect_due()
        request = gateway.v1.subscription_schedules.create.call_args.args[0]
        self.assertEqual(request['customer'], 'cus_phase1')
        self.assertEqual([p['items'][0]['price_data']['unit_amount'] for p in request['phases']], [15000, 15000, 10000])
        self.assertEqual(request['end_behavior'], 'cancel')
        self.assertEqual(gateway.v1.subscription_schedules.create.call_count, 1)
        gateway.v1.payment_intents.create.assert_not_called()
        self.assertEqual((Student.objects.count(), Payment.objects.count()), (1, 1))

    def test_unpaid_initial_checkout_never_provisions_subscription_or_enrolls(self):
        self.start()
        gateway, _, _ = helpers.AutopayTests.transport(self)
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.begin().status_code, 201)
            billing.provision(AutopayAgreement.objects.get().pk)
        gateway.v1.subscription_schedules.create.assert_not_called()
        self.assertFalse(Student.objects.exists())
        self.assertFalse(Payment.objects.filter(status='SUCCEEDED').exists())

    def test_later_invoice_can_settle_while_earlier_invoice_fails_and_replay_does_not_credit_twice(self):
        agreement, gateway, _ = self.provisioned()
        earlier, later = list(agreement.installments.filter(position__gt=0))[:2]
        self.deliver(agreement, gateway, earlier, 'invoice.payment_failed', 'open', intent_status='requires_payment_method')
        self.deliver(agreement, gateway, later)
        self.deliver(agreement, gateway, later, 'invoice.updated')
        earlier.refresh_from_db(); later.refresh_from_db()
        self.assertEqual((earlier.status, later.status), ('FAILED', 'PAID'))
        self.assertEqual(Student.objects.get().total_class_quota, 5)
        self.assertEqual(Payment.objects.filter(status='SUCCEEDED').count(), 2)
        self.assertEqual(later.attempts.count(), 1)
        gateway.v1.payment_intents.create.assert_not_called()
        connection.check_constraints()

    def test_whole_aed_rounding_stays_with_the_original_installment_when_payments_arrive_out_of_order(self):
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(6), 'offer_fee': D('5.3'),
            'single_payment_percent': D(0), 'single_payment_plan_types': [], 'note': ''})
        self.lead = self.new_lead()
        agreement, gateway, _ = self.provisioned()
        self.assertEqual([r.amount for r in agreement.installments.all()], [D(11), D(16), D(15), D(11)])
        # Original first+third allocations are 2+3 classes for AED 26, while
        # re-rounding a contiguous five-class prefix would incorrectly demand 27.
        later = agreement.installments.get(position=2)
        self.deliver(agreement, gateway, later)
        self.assertEqual(sum(Payment.objects.filter(status='SUCCEEDED').values_list('amount', flat=True)), D(26))
        self.assertEqual(Student.objects.get().total_class_quota, 5)
        connection.check_constraints()

    def test_wrong_amount_is_quarantined_and_does_not_credit_quota(self):
        agreement, gateway, _ = self.provisioned()
        self.deliver(agreement, gateway, agreement.installments.get(position=1), status='open', amount=999)
        agreement.refresh_from_db()
        self.assertEqual((agreement.billing_status, Student.objects.get().total_class_quota), ('REQUIRES_REVIEW', 2))
        gateway.v1.invoices.update.assert_called_with('in_native_1', {'auto_advance': False})
        self.assertEqual(Payment.objects.count(), 1)

    def test_authentication_required_uses_hosted_invoice_and_no_local_retry(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        self.deliver(agreement, gateway, row, 'invoice.payment_action_required', 'open', intent_status='requires_action')
        row.refresh_from_db()
        self.assertEqual(row.status, 'REQUIRES_CUSTOMER_ACTION')
        self.assertEqual(Student.objects.get().total_class_quota, 2)
        private = autopay.agreement_data(agreement, include_actions=True)['installments'][1]
        public = autopay.agreement_data(agreement)['installments'][1]
        self.assertEqual(private['stripe_invoice_url'], 'https://invoice.stripe.com/i/native')
        self.assertIsNone(public['stripe_invoice_url'])
        self.assertIsNone(autopay.prepare_due(row.pk))
        gateway.v1.payment_intents.create.assert_not_called()

    def test_wrong_customer_currency_and_environment_do_not_credit_classes(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        for changes in [{'customer': 'cus_other'}, {'currency': 'usd'}, {'livemode': True}]:
            invalid = {**self.invoice(agreement, row, status='open'), **changes}
            with self.subTest(changes=changes), mock.patch.object(self, 'invoice', return_value=invalid):
                self.deliver(agreement, gateway, row, status='open')
                self.assertEqual(Payment.objects.count(), 1)
                self.assertEqual(Student.objects.get().total_class_quota, 2)

    def test_void_and_uncollectible_invoices_preserve_allocations_without_quota(self):
        agreement, gateway, _ = self.provisioned()
        for position, event, state in [(1, 'invoice.voided', 'void'), (2, 'invoice.marked_uncollectible', 'uncollectible')]:
            row = agreement.installments.get(position=position)
            self.deliver(agreement, gateway, row, event, state)
            row.refresh_from_db()
            self.assertEqual(row.payment.status, 'FAILED')
            self.assertEqual(row.stripe_invoice_status, state)
        self.assertEqual(Student.objects.get().total_class_quota, 2)
        self.assertEqual(agreement.installments.count(), 4)

    def test_initial_payment_and_reusable_method_are_separate_provisioning_conditions(self):
        agreement, gateway = self.ready()
        agreement.setup_status = 'INCOMPLETE'
        agreement.save(update_fields=['setup_status'])
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
        gateway.v1.subscription_schedules.create.assert_not_called()
        self.assertEqual((Student.objects.count(), Student.objects.get().total_class_quota), (1, 2))

    def test_legacy_migration_keeps_initial_payment_and_never_runs_the_legacy_collector_after_switch(self):
        agreement, gateway = self.ready(engine='LEGACY_PI')
        original_payment = agreement.installments.get(position=0).payment_id
        billing.migrate_legacy(agreement.pk)
        billing.migrate_legacy(agreement.pk)
        agreement.refresh_from_db()
        self.assertEqual(agreement.collection_engine, billing.ENGINE)
        self.assertEqual(agreement.installments.get(position=0).payment_id, original_payment)
        self.assertIsNone(autopay.prepare_due(agreement.installments.get(position=1).pk))
        self.assertEqual(Payment.objects.count(), 1)
        gateway.v1.payment_intents.create.assert_not_called()

    def test_billing_webhook_requires_signature_before_any_provider_read(self):
        with mock.patch('sales.stripe_gateway.client') as gateway:
            result = APIClient().post('/api/sales/webhooks/stripe/',
                {'id': 'evt_forged', 'type': 'invoice.paid'}, format='json', HTTP_STRIPE_SIGNATURE='invalid')
        self.assertEqual(result.status_code, 400)
        gateway.assert_not_called()

    def test_canceled_subscription_preserves_outstanding_schedule_and_history(self):
        agreement, gateway, subscription = self.provisioned()
        subscription['status'] = 'canceled'
        event = {'id': 'evt_subscription_deleted', 'livemode': False, 'type': 'customer.subscription.deleted',
                 'data': {'object': subscription}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event).status_code, 200)
        agreement.refresh_from_db()
        self.assertEqual(agreement.stripe_subscription_status, 'canceled')
        self.assertEqual(agreement.billing_status, 'REQUIRES_REVIEW')
        self.assertEqual(agreement.installments.count(), 4)
        self.assertEqual(Payment.objects.count(), 1)

    def test_post_enrollment_bde_and_unrelated_staff_permissions_are_unchanged(self):
        agreement, gateway, _ = self.provisioned()
        self.assertEqual(self.preview().status_code, 403)
        self.assertEqual(self.client.post(f'/api/sales/autopay/{agreement.pk}/initial-checkout/',
            {'request_id': str(uuid.uuid4())}, format='json').status_code, 403)
        other = APIClient(); other.force_authenticate(self.other_bde)
        self.assertEqual(other.get(self.url()).status_code, 404)
        self.client.force_authenticate(self.admin)
        response = self.client.get(f'/api/sales/students/{agreement.purchase.sale.student_id}/initial-sale/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['autopay']['stripe_subscription_id'], 'sub_native')

    def test_frozen_billing_origin_and_allocation_cannot_be_rewritten(self):
        agreement, _, _ = self.provisioned()
        for changes in [{'collection_engine': 'LEGACY_PI'}, {'stripe_schedule_id': 'sub_sched_other'},
                        {'billing_request': {}}]:
            with self.subTest(changes=changes), self.assertRaises(DatabaseError), transaction.atomic():
                AutopayAgreement.objects.filter(pk=agreement.pk).update(**changes)


    def schedule_event(self, gateway, remote, status=200):
        gateway.v1.subscription_schedules.retrieve.return_value = remote
        event = {'id': f'evt_{uuid.uuid4().hex}', 'livemode': False, 'type': 'subscription_schedule.updated', 'data': {'object': remote}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.webhook(event)
        self.assertEqual(response.status_code, status, response.content)
        return StripeEvent.objects.get(event_id=event['id'])

    def test_the_first_installment_card_settings_update_keeps_the_schedule_provisioned(self):
        agreement, gateway, _ = self.provisioned()
        # As recorded: Stripe starts phase 1, then Django's card-settings update restarts it 19 seconds later.
        remote = running(gateway.v1.subscription_schedules.retrieve.return_value, moved=19)
        remote['subscription'] = 'sub_native'
        self.assertEqual(self.schedule_event(gateway, remote).outcome, 'PROCESSED')
        agreement.refresh_from_db()
        self.assertEqual((agreement.billing_status, agreement.billing_message), ('PROVISIONED', ''))
        # Earlier than agreed is not Stripe's restart: the agreement needs review, as before.
        remote['phases'][0]['start_date'] = remote['current_phase']['start_date'] = remote['phases'][0]['start_date'] - 38
        record = self.schedule_event(gateway, remote, status=400)
        self.assertEqual((record.outcome, record.error), ('REJECTED', billing.SCHEDULE_DATES_DIFFER))
        agreement.refresh_from_db()
        self.assertEqual((agreement.billing_status, agreement.billing_message), ('REQUIRES_REVIEW', billing.SCHEDULE_DATES_DIFFER))

    def reconcile(self, gateway, invoices, *args):
        for resource in (gateway.v1.checkout.sessions, gateway.v1.payment_intents, gateway.v1.refunds, gateway.v1.disputes):
            resource.list.return_value = page([])
        gateway.v1.invoices.list.return_value = page(invoices)
        out = StringIO()
        with mock.patch('sales.management.commands.reconcile_stripe_ledger.stripe.StripeClient', return_value=gateway):
            call_command('reconcile_stripe_ledger', *args, stdout=out)
        return out.getvalue()

    def test_reconciliation_reports_a_linked_invoice_paid_at_stripe_but_not_in_django(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        # As recorded: invoice.created arrived, then Stripe paid the invoice while no webhook could reach Django.
        self.deliver(agreement, gateway, row, 'invoice.created', 'draft')
        row.refresh_from_db()
        self.assertEqual((row.status, row.stripe_invoice_id), ('INVOICE_DRAFT', 'in_native_1'))
        paid = {**self.invoice(agreement, row), 'amount_paid': int(row.amount) * 100}
        output = self.reconcile(gateway, [paid])
        self.assertIn('MISMATCH INCONSISTENT: in_native_1 · Stripe invoice is paid; Django records installment 1 as INVOICE_DRAFT.', output)
        self.assertFalse(StripeReviewItem.objects.exists())
        self.reconcile(gateway, [paid], '--record-review')
        self.reconcile(gateway, [paid], '--record-review')
        item = StripeReviewItem.objects.get()
        self.assertEqual((item.kind, item.object_id, item.source, item.amount), ('INCONSISTENT', 'in_native_1', 'RECONCILIATION', row.amount))
        # Reporting credits nothing and changes nothing.
        row.refresh_from_db()
        self.assertEqual((row.status, Student.objects.get().total_class_quota, Payment.objects.count()), ('INVOICE_DRAFT', 2, 1))
        gateway.v1.invoices.update.assert_not_called()

    def test_reconciliation_accepts_matching_outcomes_and_reports_a_django_payment_stripe_voided(self):
        agreement, gateway, _ = self.provisioned()
        first, second = agreement.installments.filter(position__in=[1, 2]).order_by('position')
        self.deliver(agreement, gateway, first)
        self.deliver(agreement, gateway, second, 'invoice.created', 'draft')
        paid = {**self.invoice(agreement, first), 'amount_paid': int(first.amount) * 100}
        draft = self.invoice(agreement, second, status='draft')
        self.assertIn('Stripe and the Django ledger agree for this window.', self.reconcile(gateway, [paid, draft]))
        self.assertIn('Stripe and the Django ledger agree for this window.', self.reconcile(gateway, [paid, {**draft, 'status': 'open'}]))
        output = self.reconcile(gateway, [{**paid, 'status': 'void'}, draft])
        self.assertIn('MISMATCH INCONSISTENT: in_native_1 · Stripe invoice is void; Django records installment 1 as PAID.', output)
