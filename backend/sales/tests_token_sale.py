"""Token Sale through the API the Hub uses: reserved with or without a tuition quote, paid by Stripe, then credited against the later tuition package."""
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from students.models import Student
from . import tests_payments as payment_helpers
from .models import Quote
from .payment_models import Payment, Purchase
from .tests_quotes import QuoteTestCase, lead_of


@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='],
    STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class TokenSaleWorkflowTests(QuoteTestCase, APITestCase):
    setUp = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    url = payment_helpers.InitialPaymentTests.url
    start = payment_helpers.InitialPaymentTests.start
    payload = payment_helpers.InitialPaymentTests.payload
    collect = payment_helpers.InitialPaymentTests.collect
    stripe_transport = payment_helpers.InitialPaymentTests.stripe_transport
    event = payment_helpers.InitialPaymentTests.event
    webhook = payment_helpers.InitialPaymentTests.webhook

    def unquoted_lead(self):
        self.counter += 1
        lead = lead_of(self.bde, f'Token Student {self.counter}', f'509100{self.counter:03d}')
        lead.parent_email = f'token{self.counter}@phase1.test'
        lead.save(update_fields=['parent_email'])
        return lead

    def state(self):
        return self.client.get(self.url()).json()

    def amount(self, **params):
        return self.client.get(self.url('amount/'), params)

    def quote(self, collection_mode, **extra):
        """The Full Bridge Course (10 classes, AED 500) quoted from Plan Choosing."""
        return self.client.post('/api/sales/quotes/', {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                                'collection_mode': collection_mode, 'lead': str(self.lead.pk), **extra}, format='json')

    def test_unquoted_token_is_reserved_pending_then_paid_without_enrollment_quota_or_purchase(self):
        self.lead = self.unquoted_lead()
        started = self.start('TOKEN', expected_start_date=(timezone.localdate() + timedelta(days=10)).isoformat())
        self.assertEqual(started.status_code, 201, started.content)
        state = self.state()
        self.assertIsNone(state['quote'])
        self.assertEqual((state['sale']['kind'], state['sale']['token_status'], state['can_collect']), ('TOKEN', 'AWAITING_PAYMENT', True))
        self.assertEqual((state['totals']['package_amount'], state['totals']['outstanding_amount']), (None, None))
        self.assertEqual(self.amount(purpose='TOKEN', collection_mode='FULL', classes='0').json(), {'amount': '100', 'classes': '0', 'currency': 'AED'})
        gateway, calls = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(calls[0]['line_items'][0]['price_data']['unit_amount'], 10000)
            pending = self.state()
            self.assertEqual([(row['purpose'], row['status'], row['amount']) for row in pending['payments']], [('TOKEN', 'PENDING', '100')])
            self.assertEqual(pending['sale']['token_status'], 'AWAITING_PAYMENT')
            self.assertEqual(self.webhook(self.event(Payment.objects.get())).status_code, 200)
        paid = self.state()
        self.assertEqual((paid['sale']['token_status'], paid['sale']['token_paid']), ('UPCOMING', '100'))
        self.assertEqual((paid['totals']['paid_classes'], paid['totals']['available_quota']), ('0', '0'))
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        # Tuition needs its plan first.
        refused = self.amount(purpose='TUITION', collection_mode='FULL', classes='10')
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'QUOTE_REQUIRED'))

    def test_later_tuition_quote_for_a_paid_unquoted_token_is_never_autopay_and_credits_the_token(self):
        for mode, classes, due, quota in [('FULL', '10', '400', D(10)), ('PARTIAL', '6', '200', D(6))]:
            with self.subTest(mode=mode):
                self.lead = self.unquoted_lead()
                self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
                self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
                refused = self.quote('AUTOPAY')
                self.assertEqual((refused.status_code, refused.json()['error']), (409, 'TOKEN_AUTOPAY_NOT_ALLOWED'))
                self.assertFalse(Quote.objects.filter(lead=self.lead).exists())
                created = self.quote(mode)
                self.assertEqual(created.status_code, 201, created.content)
                state = self.state()
                self.assertEqual(state['quote']['id'], created.json()['id'])
                self.assertEqual((state['totals']['package_amount'], state['totals']['paid_amount'], state['totals']['outstanding_amount']), ('500', '100', '400'))
                self.assertFalse(Student.objects.filter(sales__enquiry=self.lead).exists())
                self.assertEqual(self.amount(purpose='TUITION', collection_mode=mode, classes=classes).json()['amount'], due)
                response = self.collect(collection_mode=mode, classes=classes, amount=due)
                self.assertEqual(response.status_code, 201, response.content)
                student = Student.objects.get(sales__enquiry=self.lead)
                self.assertEqual(student.total_class_quota, quota)
                self.assertEqual(response.json()['state']['totals']['paid_amount'], str(100 + int(due)))

    def test_token_with_an_eligible_quote_keeps_it_and_credits_the_token(self):
        self.lead = self.new_lead(collection_mode='FULL')
        original = Quote.objects.get(lead=self.lead)
        self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        state = self.state()
        self.assertEqual((state['sale']['original_quote_id'], state['totals']['outstanding_amount']), (str(original.pk), '500'))
        self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
        self.assertEqual(self.state()['totals']['outstanding_amount'], '400')
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        self.assertEqual(self.collect(collection_mode='FULL', classes='10', amount='400').status_code, 201)
        self.assertEqual(Student.objects.get().total_class_quota, D(10))
        self.assertEqual(Quote.objects.filter(lead=self.lead).count(), 1)

    def test_new_sale_keeps_autopay_quotes(self):
        self.lead = self.unquoted_lead()
        created = self.quote('AUTOPAY')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(self.start().status_code, 201)
        self.assertEqual(self.state()['quote']['collection_mode'], 'AUTOPAY')
        # Once the New Sale has started, its plan can still be replaced as AutoPay: the guard is the Token Sale's only.
        replaced = self.quote('AUTOPAY', replaces=created.json()['id'])
        self.assertEqual(replaced.status_code, 201, replaced.content)
        self.assertEqual((self.state()['quote']['id'], self.state()['quote']['collection_mode']), (replaced.json()['id'], 'AUTOPAY'))
