"""A student's finance after enrollment: their mentor's (or an administrator's) view and collection of every purchase.

Stripe transport is mocked throughout; no request leaves the test process.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from students.models import Student
from . import tests_additional_purchases as purchase_helpers, tests_student_accounts as account_helpers
from .payment_models import Payment, Purchase, Sale
from .tests_lifecycle import account as user_account
from .tests_quotes import QuoteTestCase

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
                   LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class StudentFinanceTests(QuoteTestCase, APITestCase):
    """The initial-sale fixtures (Bridge Course, 10 classes, AED 500), enrolled and given to self.mentor."""
    setUp = account_helpers.StudentAccountTests.setUp
    new_lead = account_helpers.StudentAccountTests.new_lead
    url = account_helpers.StudentAccountTests.url
    start = account_helpers.StudentAccountTests.start
    stripe_transport = account_helpers.StudentAccountTests.stripe_transport
    event = account_helpers.StudentAccountTests.event
    webhook = account_helpers.StudentAccountTests.webhook
    link_for = account_helpers.StudentAccountTests.link_for
    transport = account_helpers.StudentAccountTests.transport
    paid = account_helpers.StudentAccountTests.paid
    enrolled = purchase_helpers.AdditionalPurchaseTests.enrolled
    as_user = purchase_helpers.AdditionalPurchaseTests.as_user
    purchase = purchase_helpers.AdditionalPurchaseTests.purchase

    def finance(self, client=None):
        return (client or self.as_user()).get(f'/api/sales/students/{self.student.pk}/finance/')

    def link(self, sale_id, classes, client=None):
        with mock.patch('sales.stripe_gateway.client', return_value=self.gateway):
            return (client or self.as_user()).post(f'/api/sales/purchases/{sale_id}/payments/',
                                                   {'request_id': str(uuid.uuid4()), 'classes': classes}, format='json')

    def receipt(self, sale_id, client=None, **extra):
        body = {'request_id': str(uuid.uuid4()), 'method': 'TRANSFER', 'classes': '4', 'amount': '200', 'received_confirmed': True,
                'transaction_reference': 'UTR-123', 'proof': SimpleUploadedFile('receipt.png', PNG, content_type='image/png'), **extra}
        body = {key: value for key, value in body.items() if value is not None}
        return (client or self.as_user()).post(f'/api/sales/purchases/{sale_id}/payments/', body, format='multipart')

    def initial_sale(self):
        return Sale.objects.get(kind='NEW')

    def test_only_the_assigned_mentor_or_an_administrator_reaches_a_students_finance(self):
        self.enrolled(mode='PARTIAL', classes='6')
        sale = self.initial_sale()
        tutor = user_account('finance_tutor', 'TUTOR')
        self.assertEqual(self.finance().status_code, 200)
        self.assertEqual(self.finance(self.as_user(self.admin)).status_code, 200)
        # The BDE who sold the purchase holds no post-enrollment permission; neither does a tutor.
        for client, code in ((self.client, 403), (self.as_user(tutor), 403), (self.as_user(self.other_mentor), 404)):
            with self.subTest(code=code):
                self.assertEqual(self.finance(client).status_code, code)
                self.assertEqual(client.get(f'/api/sales/students/{self.student.pk}/payments/').status_code, code)
                self.assertEqual(client.get(f'/api/sales/purchases/{sale.pk}/').status_code, code)
                self.assertEqual(client.get(f'/api/sales/purchases/{sale.pk}/amount/', {'classes': '4'}).status_code, code)
                self.assertEqual(self.link(sale.pk, '4', client=client).status_code, code)
                self.assertEqual(self.receipt(sale.pk, client=client).status_code, code)
        self.assertEqual(Payment.objects.count(), 1)

    def test_summary_purchases_and_history_come_from_the_purchase_and_payment_records(self):
        self.enrolled()
        additional = self.purchase(collection_mode='PARTIAL').json()['sale']['id']
        self.assertEqual(self.receipt(additional).status_code, 201)
        data = self.finance().json()
        self.assertEqual(data['summary'], {
            'purchased_classes': '20', 'paid_classes': '14', 'pending_classes': '6', 'total_amount': '1000', 'paid_amount': '700',
            'pending_amount': '300', 'collectible_amount': '300', 'autopay_amount': '0', 'class_quota': '10',
            'classes_not_credited': '4', 'refunded_amount': '0'})
        initial, extra = data['purchases']
        self.assertEqual((initial['kind'], initial['payment_status'], initial['outstanding_amount'], initial['can_collect']),
                         ('NEW', 'PAID', '0', False))
        self.assertEqual((extra['id'], extra['kind'], extra['payment_status'], extra['outstanding_amount'], extra['outstanding_classes'],
                          extra['can_collect']), (additional, 'ADDITIONAL', 'PARTIALLY_PAID', '300', '6', True))
        self.assertEqual((initial['syllabus'], initial['plan_type']), (self.bridge.revisions.get(number=1).title, 'BRIDGE_COURSE'))
        self.assertEqual((data['autopay'], data['can_add'], data['can_collect']), ([], False, True))

        url = f'/api/sales/students/{self.student.pk}/payments/'
        history = self.as_user().get(url).json()
        self.assertEqual(history['count'], 2)
        newest, oldest = history['results']
        self.assertEqual((newest['payment_type'], newest['sale_id'], newest['purchase_reference'], newest['method'], newest['recorded_by']['name']),
                         ('ADDITIONAL', additional, Purchase.objects.get(sale_id=additional).quote.reference, 'TRANSFER',
                          self.mentor.full_name or self.mentor.username))
        self.assertEqual((oldest['payment_type'], oldest['method'], oldest['classes_credited']), ('INITIAL', 'STRIPE', True))
        self.assertEqual(newest['proof_url'], f'/api/sales/purchases/{additional}/payments/{newest["id"]}/proof/')
        self.assertEqual([row['id'] for row in self.as_user().get(url, {'sale': additional}).json()['results']], [newest['id']])
        self.assertEqual(self.as_user().get(url, {'method': 'STRIPE'}).json()['count'], 1)
        self.assertEqual(self.as_user().get(url, {'status': 'PENDING'}).json()['count'], 0)
        paged = self.as_user().get(url, {'page': 2, 'page_size': 1}).json()
        self.assertEqual((paged['count'], [row['id'] for row in paged['results']]), (2, [oldest['id']]))
        self.assertEqual(self.as_user().get(url, {'status': 'LOST'}).status_code, 400)

    def test_full_and_partial_collection_through_stripe_links_records_money_only(self):
        self.enrolled(mode='PARTIAL', classes='6')
        sale = self.initial_sale()
        self.assertEqual(self.as_user().get(f'/api/sales/purchases/{sale.pk}/amount/', {'classes': '2'}).json()['amount'], '100')
        for classes in ('2', '2'):
            response = self.link(sale.pk, classes)
            self.assertEqual(response.status_code, 201, response.content)
            payment = Payment.objects.get(pk=response.json()['payment']['id'])
            self.assertEqual((payment.amount, payment.sale_id, payment.recorded_by_id), (D(100), sale.pk, self.mentor.pk))
            event = self.event(payment)
            self.assertEqual(self.paid(payment, self.gateway).status_code, 200)
            with mock.patch('sales.stripe_gateway.client', return_value=self.gateway):
                self.assertEqual(self.webhook(event).status_code, 200)  # A re-delivered event changes nothing.
        state = self.as_user().get(f'/api/sales/purchases/{sale.pk}/').json()
        self.assertEqual((state['totals']['outstanding_amount'], state['totals']['fully_paid'], state['can_collect']), ('0', True, False))
        self.assertEqual([row['payment_type'] for row in state['payments']], ['INITIAL', 'BALANCE', 'BALANCE'])
        # Existing class-credit rules: enrollment credited the first 6 classes; balance payments record money only.
        self.student.refresh_from_db()
        self.assertEqual((self.student.total_class_quota, state['totals']['classes_not_credited']), (D(6), '4'))
        self.assertEqual(Payment.objects.filter(status='SUCCEEDED').count(), 3)
        done = self.link(sale.pk, '1')
        self.assertEqual((done.status_code, done.json()['error']), (400, 'INVALID_ALLOCATION'))

        # A Complete Payment purchase is collected whole, never in part.
        additional = self.purchase().json()['sale']['id']
        part = self.link(additional, '4')
        self.assertEqual((part.status_code, part.json()['error']), (409, 'FULL_PAYMENT_REQUIRED'))
        self.assertEqual(self.link(additional, '10').status_code, 201)

    def test_a_direct_payment_needs_confirmation_the_exact_amount_and_its_proof(self):
        self.enrolled(mode='PARTIAL', classes='6')
        sale = self.initial_sale()
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        svg = SimpleUploadedFile('evil.svg', b'<svg/>', content_type='image/svg+xml')
        for extra, error in (({'received_confirmed': False}, 'RECEIPT_NOT_CONFIRMED'), ({'amount': '201'}, 'AMOUNT_MISMATCH'),
                             ({'proof': None}, 'PROOF_REQUIRED'), ({'proof': svg}, 'INVALID_PROOF'),
                             ({'payment_date': future}, 'VALIDATION_ERROR'), ({'classes': '5', 'amount': '250'}, 'INVALID_ALLOCATION')):
            with self.subTest(error=error):
                response = self.receipt(sale.pk, **extra)
                self.assertEqual((response.status_code, response.json()['error']), (400, error))
        self.assertEqual(Payment.objects.count(), 1)

        request_id = str(uuid.uuid4())
        response = self.receipt(sale.pk, request_id=request_id)
        self.assertEqual(response.status_code, 201, response.content)
        payment = Payment.objects.get(pk=response.json()['payment']['id'])
        self.assertEqual((payment.status, payment.method, payment.amount, payment.classes, payment.transaction_reference, payment.recorded_by_id),
                         ('SUCCEEDED', 'TRANSFER', D(200), D(4), 'UTR-123', self.mentor.pk))
        self.assertTrue(payment.received_confirmed and payment.proof)
        # A retry with the same request ID returns the same payment; a changed one is a conflict.
        self.assertEqual(self.receipt(sale.pk, request_id=request_id).json()['payment']['id'], str(payment.pk))
        self.assertEqual(self.receipt(sale.pk, request_id=request_id, amount='199').status_code, 409)
        self.assertEqual(Payment.objects.count(), 2)
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, D(6))  # Money only.

        proof = f'/api/sales/purchases/{sale.pk}/payments/{payment.pk}/proof/'
        download = self.as_user().get(proof)
        self.assertEqual((download.status_code, b''.join(download.streaming_content)), (200, PNG))
        self.assertEqual(self.as_user(self.admin).get(proof).status_code, 200)
        self.assertEqual(self.as_user(self.other_mentor).get(proof).status_code, 404)
        self.assertEqual(self.client.get(proof).status_code, 403)
        # Stripe payments carry no receipt file.
        stripe_payment = Payment.objects.get(method='STRIPE')
        self.assertEqual(self.as_user().get(f'/api/sales/purchases/{sale.pk}/payments/{stripe_payment.pk}/proof/').status_code, 404)

    def test_an_open_link_or_a_settled_purchase_blocks_another_collection(self):
        self.enrolled(mode='PARTIAL', classes='6')
        sale = self.initial_sale()
        self.assertEqual(self.link(sale.pk, '2').status_code, 201)
        # One open link per sale: neither another link nor a receipt meanwhile.
        self.assertEqual(self.link(sale.pk, '2').json()['error'], 'PAYMENT_PENDING')
        self.assertEqual(self.receipt(sale.pk).json()['error'], 'PAYMENT_PENDING')
        summary = self.finance().json()
        self.assertEqual((summary['purchases'][0]['payment_status'], summary['purchases'][0]['can_collect'], summary['summary']['collectible_amount']),
                         ('LINK_PENDING', False, '0'))
        pending = Payment.objects.get(status='PENDING')
        with mock.patch('sales.stripe_gateway.client', return_value=self.gateway):
            expired = self.as_user().post(f'/api/sales/purchases/{sale.pk}/payments/{pending.pk}/expire/', {}, format='json')
        self.assertEqual(expired.status_code, 200)
        self.assertEqual(self.receipt(sale.pk).status_code, 201)
        again = self.receipt(sale.pk)
        self.assertEqual((again.status_code, again.json()['error']), (400, 'INVALID_ALLOCATION'))
        self.assertEqual(Payment.objects.filter(status='SUCCEEDED').count(), 2)
        self.student.refresh_from_db()
        self.assertEqual(self.student.total_class_quota, D(6))

    def test_a_student_without_an_account_has_no_finance(self):
        self.enrolled()
        sheet = Student.objects.create(profile=user_account('sheet_finance', 'STUDENT'), student_code='EDP09003', full_name='Sheet Student',
                                       mentor=self.mentor)
        refused = self.as_user().get(f'/api/sales/students/{sheet.pk}/finance/')
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'NO_STUDENT_ACCOUNT'))
