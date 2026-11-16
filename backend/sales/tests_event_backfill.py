"""Webhook backfill (sales.event_backfill, sales.tasks.recover_missed_stripe_events).

All Stripe transport is mocked. These tests must never use account credentials.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as utc
from unittest import mock

import stripe
from django.db import connections
from django.test import override_settings
from rest_framework.test import APITestCase

from students.models import Student
from . import billing, event_backfill, stripe_gateway, tasks, tests_autopay as helpers, tests_billing, tests_payments as initial_helpers
from .ledger_models import StripeReviewItem
from .payment_models import Payment, StripeEvent, StripeEventCursor
from .tests_billing import page
from .tests_quotes import QuoteTestCase

NOW = datetime(2026, 12, 11, 8, 0, tzinfo=utc.utc)


def at(minutes_ago, now=NOW):
    return int((now - timedelta(minutes=minutes_ago)).timestamp())


def event(event_id, kind, obj, created):
    return {'id': event_id, 'type': kind, 'livemode': False, 'created': created, 'data': {'object': obj}}


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only',
    STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
    AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai',
    LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class StripeEventBackfillTests(QuoteTestCase, APITestCase):
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
    ready = tests_billing.BillingTests.ready
    provisioned = tests_billing.BillingTests.provisioned
    invoice = tests_billing.BillingTests.invoice
    deliver = tests_billing.BillingTests.deliver

    def backfill(self, gateway, events, now=NOW, **options):
        gateway.v1.events.list.return_value = page(events)
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            return event_backfill.run(now=now, **options)

    def missed_invoice(self, agreement, gateway, row, created):
        """An installment invoice Stripe paid while no webhook reached Django."""
        invoice = self.invoice(agreement, row)
        intent = {'id': f'pi_invoice_{row.position}', 'customer': agreement.stripe_customer_id, 'livemode': False,
            'currency': 'aed', 'amount_received': int(row.amount) * 100, 'status': 'succeeded',
            'latest_charge': f'ch_invoice_{row.position}', 'last_payment_error': None}
        gateway.v1.invoices.retrieve.return_value = invoice
        gateway.v1.invoice_payments.list.return_value = page([{'id': f'inpay_{row.position}', 'status': 'paid',
            'amount_paid': int(row.amount) * 100, 'payment': {'type': 'payment_intent', 'payment_intent': intent}}])
        gateway.v1.payment_intents.retrieve.return_value = intent
        return event(f'evt_paid_{row.position}', 'invoice.paid', invoice, created)

    def credits(self):
        return Student.objects.get().total_class_quota, Payment.objects.filter(status='SUCCEEDED').count()

    def pending_checkout(self):
        """An initial AutoPay Checkout the parent paid, its completion never delivered."""
        self.assertEqual(self.start().status_code, 201)
        gateway, _, _ = helpers.AutopayTests.transport(self)
        gateway.v1.subscription_schedules.list.return_value = page([])
        gateway.v1.charges.list.return_value = page([])
        with mock.patch('sales.stripe_gateway.client', return_value=gateway), mock.patch('sales.autopay.DEFAULT_COLLECTION_ENGINE', billing.ENGINE):
            self.assertEqual(self.begin().status_code, 201)
        payment = Payment.objects.get()
        completed = {**self.checkout_event(payment), 'created': at(20)}
        gateway.v1.payment_intents.retrieve.return_value = {'id': completed['data']['object']['payment_intent'], 'status': 'succeeded',
            'customer': payment.stripe_customer_id, 'currency': 'aed', 'amount_received': int(payment.amount) * 100,
            'setup_future_usage': 'off_session', 'payment_method': 'pm_autopay', 'livemode': False}
        return gateway, payment, completed

    def test_a_checkout_rendered_in_an_older_api_version_is_credited_once(self):
        gateway, payment, completed = self.pending_checkout()
        completed['api_version'] = '2025-11-17.clover'  # Stripe keeps each event in its creation-time version.
        with self.assertLogs('sales.event_backfill', 'INFO') as logs:
            summary = self.backfill(gateway, [completed])
        self.assertEqual((summary['recovered'], summary['api_versions']), ({'PROCESSED': 1}, {'2025-11-17.clover': 1}))
        self.assertTrue(any(completed['id'] in line and 'API 2025-11-17.clover' in line for line in logs.output))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'SUCCEEDED')
        credited = self.credits()
        self.assertEqual(self.backfill(gateway, [completed], now=NOW + timedelta(minutes=10))['already_recorded'], 1)
        self.assertEqual(self.credits(), credited)

    def test_a_payload_whose_shape_differs_fails_closed_without_credit(self):
        gateway, payment, completed = self.pending_checkout()
        # As a newer API version might render it: the Customer expanded instead of its ID.
        obj = completed['data']['object']
        obj['customer'] = {'id': obj['customer'], 'object': 'customer'}
        completed['api_version'] = '2099-01-01.future'
        with self.assertLogs('sales.event_backfill', 'WARNING') as logs:
            summary = self.backfill(gateway, [completed])
        self.assertEqual(summary['recovered'], {'REJECTED': 1})
        self.assertTrue(any('API 2099-01-01.future' in line and 'REJECTED' in line for line in logs.output))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'PENDING')
        self.assertFalse(Student.objects.exists())
        record = StripeEvent.objects.get(pk=completed['id'])
        self.assertEqual((record.outcome, record.source), ('REJECTED', 'BACKFILL'))
        self.assertTrue(StripeReviewItem.objects.filter(event=record, status='OPEN').exists())
        # Recorded as the webhook would record it: final, reviewed by an Admin, never retried into a credit.
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - event_backfill.GRACE)

    def test_the_initial_lookback_is_configurable_and_capped_at_stripe_retention(self):
        gateway = mock.MagicMock()
        two_days = event('evt_two_days', 'customer.updated', {'id': 'cus_1'}, at(2 * 24 * 60))
        with override_settings(STRIPE_EVENT_BACKFILL_INITIAL_LOOKBACK_HOURS=72):
            summary = self.backfill(gateway, [two_days])
        self.assertEqual(gateway.v1.events.list.call_args.args[0]['created']['gte'], at(72 * 60))
        self.assertEqual(summary['recovered'], {'IGNORED': 1})
        StripeEventCursor.objects.all().delete()
        with override_settings(STRIPE_EVENT_BACKFILL_INITIAL_LOOKBACK_HOURS=40 * 24), self.assertLogs('sales.event_backfill', 'WARNING'):
            self.backfill(gateway, [])
        self.assertEqual(gateway.v1.events.list.call_args.args[0]['created']['gte'], int((NOW - event_backfill.RETENTION).timestamp()))

    def test_an_outage_beyond_stripe_retention_is_reported_and_the_run_carries_on(self):
        gateway = mock.MagicMock()
        StripeEventCursor.objects.create(mode='test', processed_through=NOW - timedelta(days=40))
        recent = event('evt_recent', 'customer.updated', {'id': 'cus_1'}, at(30))
        with self.assertLogs('sales.event_backfill', 'ERROR') as logs:
            summary = self.backfill(gateway, [recent])
        oldest = NOW - event_backfill.RETENTION
        self.assertEqual(summary['unrecoverable'], {'from': (NOW - timedelta(days=40)).isoformat(), 'to': oldest.isoformat()})
        self.assertTrue(any('reconcile_stripe_ledger' in line for line in logs.output))
        self.assertEqual(gateway.v1.events.list.call_args.args[0]['created']['gte'], int(oldest.timestamp()))
        self.assertEqual(summary['recovered'], {'IGNORED': 1})
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - event_backfill.GRACE)

    def test_the_backfill_lock_never_blocks_a_communications_job(self):
        from communications.tasks import _LOCK_CLASS_JOBS, single_run
        other = connections.create_connection('default')  # A second session, as another worker would hold.
        try:
            with single_run('recover_missed_stripe_events') as held, other.cursor() as cursor:
                self.assertTrue(held)
                cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [_LOCK_CLASS_JOBS, 'dispatch_messages'])
                self.assertTrue(cursor.fetchone()[0])
                cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s))', [_LOCK_CLASS_JOBS, 'dispatch_messages'])
                cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s))', [_LOCK_CLASS_JOBS, 'recover_missed_stripe_events'])
                self.assertFalse(cursor.fetchone()[0])
        finally:
            other.close()

    def test_a_missed_installment_payment_is_recovered_once(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        quota, paid_count = self.credits()
        paid = self.missed_invoice(agreement, gateway, row, created=at(20))
        with self.assertLogs('sales.event_backfill', 'INFO') as logs:
            summary = self.backfill(gateway, [paid])
        self.assertEqual(summary['recovered'], {'PROCESSED': 1})
        self.assertTrue(any(paid['id'] in line and 'PROCESSED' in line for line in logs.output))
        row.refresh_from_db()
        self.assertEqual(row.status, 'PAID')
        self.assertEqual(self.credits(), (quota + row.classes, paid_count + 1))
        record = StripeEvent.objects.get(pk=paid['id'])
        self.assertEqual((record.outcome, record.source), ('PROCESSED', 'BACKFILL'))
        # The next run finds it recorded: nothing is processed or credited again.
        summary = self.backfill(gateway, [paid], now=NOW + timedelta(minutes=10))
        self.assertEqual((summary['already_recorded'], summary['recovered']), (1, {}))
        self.assertEqual(self.credits(), (quota + row.classes, paid_count + 1))
        gateway.v1.payment_intents.create.assert_not_called()

    def test_events_the_webhook_processed_are_never_processed_again(self):
        agreement, gateway, _ = self.provisioned()
        delivered = {**self.deliver(agreement, gateway, agreement.installments.get(position=1)), 'created': at(30)}
        StripeEvent.objects.create(event_id='evt_customer', event_type='customer.updated', outcome='IGNORED')
        ignored = event('evt_customer', 'customer.updated', {'id': agreement.stripe_customer_id}, at(25))
        before = self.credits()
        with mock.patch('sales.stripe_gateway.process_event', wraps=stripe_gateway.process_event) as handler:
            summary = self.backfill(gateway, [delivered, ignored])
        handler.assert_not_called()
        self.assertEqual((summary['already_recorded'], summary['recovered']), (2, {}))
        self.assertEqual(StripeEvent.objects.get(pk=delivered['id']).source, 'WEBHOOK')
        self.assertEqual(self.credits(), before)

    def test_a_webhook_delivery_racing_the_run_is_not_processed_twice(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        paid = self.missed_invoice(agreement, gateway, row, created=at(20))
        # The webhook delivers it after the run checked what was recorded.
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(paid).status_code, 200)
        credited = self.credits()
        with mock.patch('sales.event_backfill.recorded', return_value=set()):
            summary = self.backfill(gateway, [paid])
        self.assertEqual((summary['already_recorded'], summary['recovered']), (1, {}))
        self.assertEqual(StripeEvent.objects.get(pk=paid['id']).source, 'WEBHOOK')
        self.assertEqual(self.credits(), credited)

    def test_recent_events_are_left_to_the_webhook_until_the_grace_period_passes(self):
        agreement, gateway, _ = self.provisioned()
        paid = self.missed_invoice(agreement, gateway, agreement.installments.get(position=1), created=at(5))
        summary = self.backfill(gateway, [paid])
        self.assertEqual(summary['recovered'], {})
        self.assertFalse(StripeEvent.objects.filter(pk=paid['id']).exists())
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - event_backfill.GRACE)
        self.assertEqual(self.backfill(gateway, [paid], now=NOW + timedelta(minutes=10))['recovered'], {'PROCESSED': 1})

    def test_the_first_run_only_looks_back_an_hour_and_leaves_history_alone(self):
        gateway = mock.MagicMock()
        old = event('evt_old', 'customer.updated', {'id': 'cus_1'}, at(3 * 24 * 60))
        recent = event('evt_recent', 'customer.updated', {'id': 'cus_1'}, at(30))
        summary = self.backfill(gateway, [recent, old])
        params = gateway.v1.events.list.call_args.args[0]
        self.assertEqual(params['created'], {'gte': at(60), 'lte': at(10)})
        self.assertEqual(summary['recovered'], {'IGNORED': 1})
        self.assertEqual(set(StripeEvent.objects.values_list('event_id', flat=True)), {'evt_recent'})
        self.assertEqual(StripeEventCursor.objects.get(pk='test').processed_through, NOW - event_backfill.GRACE)

    def test_a_listing_failure_changes_nothing_and_the_next_run_recovers(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        StripeEventCursor.objects.create(mode='test', processed_through=NOW - timedelta(minutes=30))
        paid = self.missed_invoice(agreement, gateway, row, created=at(20))
        gateway.v1.events.list.side_effect = stripe.APIConnectionError('Stripe unreachable')
        with mock.patch('sales.stripe_gateway.client', return_value=gateway), self.assertLogs('sales.event_backfill', 'ERROR'):
            summary = event_backfill.run(now=NOW)
        self.assertEqual(summary['error'], 'listing failed')
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - timedelta(minutes=30))
        self.assertFalse(StripeEvent.objects.filter(pk=paid['id']).exists())
        gateway.v1.events.list.side_effect = None
        self.assertEqual(self.backfill(gateway, [paid], now=NOW + timedelta(minutes=10))['recovered'], {'PROCESSED': 1})
        row.refresh_from_db()
        self.assertEqual(row.status, 'PAID')

    def test_a_failing_event_holds_the_checkpoint_and_is_retried_while_others_proceed(self):
        agreement, gateway, _ = self.provisioned()
        row = agreement.installments.get(position=1)
        quota, _ = self.credits()
        paid = self.missed_invoice(agreement, gateway, row, created=at(40))
        later = event('evt_customer', 'customer.updated', {'id': agreement.stripe_customer_id}, at(30))
        gateway.v1.invoices.retrieve.side_effect = stripe.APIConnectionError('Stripe unreachable')
        with self.assertLogs('sales.event_backfill', 'ERROR') as logs:
            summary = self.backfill(gateway, [later, paid])
        self.assertEqual((summary['failed'], summary['recovered']), ([paid['id']], {'IGNORED': 1}))
        self.assertTrue(any(paid['id'] in line for line in logs.output))
        self.assertFalse(StripeEvent.objects.filter(pk=paid['id']).exists())
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - timedelta(minutes=40))
        # Stripe answers again: the next run retries it, once, and moves on.
        gateway.v1.invoices.retrieve.side_effect = None
        summary = self.backfill(gateway, [later, paid], now=NOW + timedelta(minutes=10))
        self.assertEqual((summary['recovered'], summary['already_recorded']), ({'PROCESSED': 1}, 1))
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW)
        self.assertEqual(Student.objects.get().total_class_quota, quota + row.classes)

    def test_a_run_that_stops_early_resumes_where_it_stopped_oldest_first(self):
        gateway = mock.MagicMock()
        older = event('evt_older', 'customer.updated', {'id': 'cus_1'}, at(40))
        newer = event('evt_newer', 'customer.updated', {'id': 'cus_1'}, at(30))
        summary = self.backfill(gateway, [newer, older], batch=1)  # Stripe lists newest first.
        self.assertTrue(summary['stopped_early'])
        self.assertEqual(list(StripeEvent.objects.values_list('event_id', flat=True)), ['evt_older'])
        self.assertEqual(StripeEventCursor.objects.get().processed_through, NOW - timedelta(minutes=30))
        summary = self.backfill(gateway, [newer, older], now=NOW + timedelta(minutes=1), batch=1)
        self.assertEqual((summary['already_recorded'], summary['recovered']), (1, {'IGNORED': 1}))
        self.assertEqual(StripeEvent.objects.filter(source='BACKFILL').count(), 2)

    def test_the_task_runs_once_at_a_time_and_only_with_stripe_configured(self):
        @contextmanager
        def held_elsewhere(job):
            yield False
        with mock.patch('communications.tasks.single_run', held_elsewhere), mock.patch('sales.event_backfill.run') as run:
            self.assertEqual(tasks.recover_missed_stripe_events(), {'skipped': 'another run is in progress'})
        run.assert_not_called()
        with override_settings(STRIPE_SECRET_KEY='', STRIPE_WEBHOOK_SECRET=''), mock.patch('sales.event_backfill.run') as run:
            self.assertEqual(tasks.recover_missed_stripe_events(), {'skipped': 'Stripe is not configured'})
        run.assert_not_called()
        with mock.patch('sales.event_backfill.run', return_value={'recovered': {}}) as run:
            self.assertEqual(tasks.recover_missed_stripe_events(), {'recovered': {}})
        run.assert_called_once_with()
