"""Fixed-installment Autopay on the student's own Customer: labels, lifecycle and cancellation.

Stripe transport is mocked (fixtures from tests_billing); nothing reaches Stripe.
"""
import uuid
from decimal import Decimal as D
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from students.models import Student
from . import billing, tests_billing as billing_helpers
from .account_models import StudentAccount
from .autopay_models import AutopayAgreement
from .payment_models import Payment, StripeCustomer
from .tests_quotes import QuoteTestCase

HELPERS = ('setUp', 'new_lead', 'url', 'start', 'webhook', 'schedule', 'preview', 'begin', 'checkout_event', 'initial_paid',
           'ready', 'provisioned', 'invoice', 'deliver')


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only',
    STRIPE_PUBLISHABLE_KEY='pk_test_unit_only', STRIPE_LIVE_MODE=False,
    AUTOPAY_TERMS_URL='https://eduport.test/autopay-terms', SALES_BILLING_TIMEZONE='Asia/Dubai',
    LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class AutopayIdentityTests(QuoteTestCase, APITestCase):
    locals().update({name: getattr(billing_helpers.BillingTests, name) for name in HELPERS})

    def cancel(self, agreement, gateway, **data):
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            return self.client.post(f'/api/sales/autopay/{agreement.pk}/cancel/', data, format='json')

    def test_fixed_schedule_runs_on_the_students_own_customer_with_student_labels(self):
        agreement, gateway = self.ready()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
        agreement.refresh_from_db()
        self.assertEqual(agreement.billing_status, 'PROVISIONED')  # The frozen request still validates.
        request = gateway.v1.subscription_schedules.create.call_args.args[0]
        account, student = StudentAccount.objects.get(), Student.objects.get()
        customer = StripeCustomer.objects.get(account=account).customer_id
        initial = agreement.installments.get(position=0).payment
        self.assertEqual({request['customer'], agreement.stripe_customer_id, initial.stripe_customer_id}, {customer})
        # A fixed, finite schedule: one phase per agreed installment, then cancel.
        future = list(agreement.installments.filter(position__gt=0))
        self.assertEqual((len(request['phases']), request['end_behavior']), (len(future), 'cancel'))
        self.assertEqual(request['start_date'], int(future[0].due_at.timestamp()))
        self.assertEqual([phase['end_date'] for phase in request['phases'][:-1]], [int(row.due_at.timestamp()) for row in future[1:]])
        self.assertTrue(all(phase['items'][0]['price_data']['recurring']['interval'] == 'month' for phase in request['phases']))
        # One reusable product; student references in metadata and descriptions.
        self.assertEqual({phase['items'][0]['price_data']['product'] for phase in request['phases']}, {'eduport_plus_tuition'})
        gateway.v1.products.create.assert_not_called()
        for meta in [request['metadata'], *[phase['metadata'] for phase in request['phases']]]:
            self.assertEqual((meta['autopay_id'], meta['eduport_account_ref'], meta['edp_student_id']),
                             (str(agreement.pk), account.reference, student.student_code))
        self.assertEqual([phase['metadata']['installment_id'] for phase in request['phases']], [str(row.pk) for row in future])
        self.assertIn(student.full_name, request['phases'][0]['description'])
        self.assertIn(f'installment 1 of {len(future)}', request['phases'][0]['description'])

    def test_installments_fail_retry_succeed_and_complete_on_the_students_sale(self):
        agreement, gateway, _ = self.provisioned()
        account = StudentAccount.objects.get()
        rows = list(agreement.installments.filter(position__gt=0))
        self.deliver(agreement, gateway, rows[0], 'invoice.payment_failed', 'open', intent_status='requires_payment_method')
        rows[0].refresh_from_db()
        self.assertEqual((rows[0].status, Student.objects.get().total_class_quota), ('FAILED', D(2)))
        self.deliver(agreement, gateway, rows[0])  # Stripe's own retry succeeds.
        for row in rows[1:]:
            self.deliver(agreement, gateway, row)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, 'COMPLETED')
        payments = list(Payment.objects.filter(status='SUCCEEDED').select_related('sale'))
        self.assertEqual(len(payments), 1 + len(rows))
        self.assertEqual({payment.sale.account_id for payment in payments}, {account.pk})
        self.assertEqual(Payment.objects.get(autopay_installment=rows[0]).stripe_charge_id, 'ch_invoice_1')
        self.assertEqual(Student.objects.get().total_class_quota, agreement.purchase.classes)

    def test_administrator_cancels_with_a_reason_stripe_first_and_history_is_kept(self):
        agreement, gateway, subscription = self.provisioned()
        self.assertEqual(self.cancel(agreement, gateway, reason='Parent asked to stop Autopay.').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.cancel(agreement, gateway, reason='stop').json()['error'], 'REASON_REQUIRED')
        gateway.v1.subscription_schedules.cancel.return_value = {'id': agreement.stripe_schedule_id, 'status': 'canceled'}
        response = self.cancel(agreement, gateway, reason='Parent asked to stop Autopay after this term.', source='PARENT_REQUEST')
        self.assertEqual(response.status_code, 200, response.content)
        gateway.v1.subscription_schedules.cancel.assert_called_once_with(agreement.stripe_schedule_id, {'invoice_now': False, 'prorate': False})
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, agreement.cancellation_source, agreement.cancelled_by), ('CANCELLED', 'PARENT_REQUEST', self.admin))
        self.assertEqual(response.json()['autopay']['cancellation_source'], 'PARENT_REQUEST')
        self.assertEqual(list(agreement.installments.values_list('status', flat=True)), ['PAID', 'CANCELLED', 'CANCELLED', 'CANCELLED'])
        self.assertEqual((Payment.objects.count(), Student.objects.get().total_class_quota), (1, D(2)))
        # Stripe then reports the stop: expected, so no review flag and no state change.
        subscription['status'] = 'canceled'
        event = {'id': f'evt_{uuid.uuid4().hex}', 'livemode': False, 'type': 'customer.subscription.deleted', 'data': {'object': subscription}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event).status_code, 200)
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, agreement.billing_status), ('CANCELLED', 'PROVISIONED'))
        self.assertEqual(self.cancel(agreement, gateway, reason='A second attempt to cancel.').status_code, 200)
        self.assertEqual(gateway.v1.subscription_schedules.cancel.call_count, 1)

    def test_cancelled_before_provisioning_is_never_provisioned(self):
        agreement, gateway = self.ready()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.cancel(agreement, gateway, reason='Family moved before the first installment.').status_code, 200)
        gateway.v1.subscription_schedules.cancel.assert_not_called()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            billing.provision(agreement.pk)
            billing.provision_ready()
        gateway.v1.subscription_schedules.create.assert_not_called()
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, agreement.cancellation_source), ('CANCELLED', 'ADMIN'))

    def test_collection_stopped_in_stripe_is_recorded_and_reviewed(self):
        agreement, gateway, subscription = self.provisioned()
        subscription['status'] = 'canceled'
        event = {'id': f'evt_{uuid.uuid4().hex}', 'livemode': False, 'type': 'customer.subscription.deleted', 'data': {'object': subscription}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event).status_code, 200)
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, agreement.cancellation_source, agreement.billing_status), ('CANCELLED', 'STRIPE', 'REQUIRES_REVIEW'))
        self.assertIsNone(agreement.cancelled_by)

    def test_stripe_unavailable_during_cancellation_changes_nothing(self):
        import stripe
        agreement, gateway, _ = self.provisioned()
        self.client.force_authenticate(self.admin)
        gateway.v1.subscription_schedules.cancel.side_effect = stripe.APIConnectionError('fixture: no response')
        response = self.cancel(agreement, gateway, reason='Parent asked to stop Autopay.')
        self.assertEqual((response.status_code, response.json()['error']), (503, 'STRIPE_UNAVAILABLE'))
        agreement.refresh_from_db()
        self.assertEqual((agreement.status, agreement.cancelled_at), ('ACTIVE', None))
        self.assertFalse(AutopayAgreement.objects.filter(installments__status='CANCELLED').exists())
