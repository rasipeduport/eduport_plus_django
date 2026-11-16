"""Mentor-initiated additional purchases: a new Sale on the student's existing account.

Stripe transport is mocked throughout; no request leaves the test process.
"""
import dataclasses
import uuid
from decimal import Decimal as D
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from students.models import Student
from . import quotes, tests_student_accounts as account_helpers
from .account_models import StudentAccount
from .models import Quote
from .payment_models import Payment, Purchase, Sale, StripeCustomer
from .tests_lifecycle import account as user_account
from .tests_payments import account_for
from .tests_quotes import QuoteTestCase


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
                   LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class AdditionalPurchaseTests(QuoteTestCase, APITestCase):
    """The initial-sale fixtures (Bridge Course, 10 classes, AED 500), without re-running their tests."""
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

    def enrolled(self, mode='FULL', classes='10'):
        """A student enrolled through a verified Stripe payment, assigned to self.mentor."""
        self.lead = self.new_lead(collection_mode=mode)
        self.assertEqual(self.start().status_code, 201)
        self.gateway, self.calls, self.created = self.transport()
        first = self.link_for(self.lead, self.gateway, classes=classes, mode=mode)
        self.assertEqual(self.paid(first, self.gateway).status_code, 200)
        self.mentor = user_account('purchase_mentor', 'MENTOR')
        self.other_mentor = user_account('other_mentor', 'MENTOR')
        Student.objects.update(mentor=self.mentor)
        self.student = Student.objects.get()
        return first

    def as_user(self, user=None):
        client = APIClient()
        client.force_authenticate(user or self.mentor)
        return client

    def purchase(self, client=None, **extra):
        body = {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'collection_mode': 'FULL',
                'request_id': str(uuid.uuid4()), **extra}
        return (client or self.as_user()).post(f'/api/sales/students/{self.student.pk}/purchases/', body, format='json')

    def link(self, sale_id, client=None, classes='10'):
        with mock.patch('sales.stripe_gateway.client', return_value=self.gateway):
            return (client or self.as_user()).post(f'/api/sales/purchases/{sale_id}/payments/',
                                                   {'request_id': str(uuid.uuid4()), 'classes': classes}, format='json')

    def test_only_the_students_mentor_or_an_administrator_can_add_a_purchase(self):
        self.enrolled()
        url = f'/api/sales/students/{self.student.pk}/purchases/'
        # The BDE who sold the first purchase holds no additional-purchase permission.
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.purchase(client=self.client).status_code, 403)
        # Another mentor's student does not exist for this mentor.
        self.assertEqual(self.as_user(self.other_mentor).get(url).status_code, 404)
        self.assertEqual(self.purchase(client=self.as_user(self.other_mentor)).status_code, 404)
        overview = self.as_user().get(url).json()
        self.assertEqual((overview['account']['reference'], overview['can_add'], len(overview['sales'])),
                         (StudentAccount.objects.get().reference, True, 1))
        self.assertTrue(overview['sales'][0]['fully_paid'])
        self.assertIn(str(self.bridge.pk), [row['id'] for row in overview['catalogue']])
        self.assertEqual(self.as_user(self.admin).get(url).status_code, 200)
        self.assertEqual(Sale.objects.count(), 1)

    def test_additional_purchase_is_a_new_sale_on_the_same_account_and_customer(self):
        first = self.enrolled()
        before = {model: list(model.objects.order_by('pk').values()) for model in (Sale, Purchase, Payment)}
        preview = self.purchase(preview=True)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual((preview.json()['preview']['classes'], preview.json()['preview']['collection_amount'], Sale.objects.count()),
                         ('10', '500', 1))
        reviewed = preview.json()['preview']['pricing_version']
        stale = self.purchase(pricing_version=reviewed + 1)
        self.assertEqual((stale.status_code, stale.json()['error'], Sale.objects.count()), (400, 'PRICING_CHANGED', 1))
        request_id = str(uuid.uuid4())
        created = self.purchase(request_id=request_id, pricing_version=reviewed)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(self.purchase(request_id=request_id).status_code, 201)  # A retry returns the same purchase.
        additional = Sale.objects.get(kind='ADDITIONAL')
        account = StudentAccount.objects.get()
        self.assertEqual((str(additional.pk), additional.account_id, additional.student_id, additional.enquiry_id, additional.created_by_id),
                         (request_id, account.pk, self.student.pk, None, self.mentor.pk))
        quote = Quote.objects.get(pk=created.json()['quote']['id'])
        self.assertEqual((quote.account_id, quote.lead_id, quote.created_by_id), (account.pk, None, self.mentor.pk))
        self.assertEqual(Purchase.objects.get(sale=additional).amount, D(500))
        # The earlier sale, its purchase and its payment are untouched.
        for model, rows in before.items():
            self.assertEqual(list(model.objects.filter(pk__in=[row['id'] for row in rows]).order_by('pk').values()), rows)

        client = self.as_user()
        self.assertEqual(client.get(f'/api/sales/purchases/{additional.pk}/amount/', {'classes': '10'}).json()['amount'], '500')
        link = self.link(additional.pk)
        self.assertEqual(link.status_code, 201, link.content)
        payment = Payment.objects.get(pk=link.json()['payment']['id'])
        # The student's one Customer is reused; a new Sale never creates another.
        self.assertEqual((payment.stripe_customer_id, len(self.created), StripeCustomer.objects.count()), (first.stripe_customer_id, 1, 1))
        sent = self.calls[-1]
        self.assertEqual((sent['metadata']['sale_id'], sent['metadata']['eduport_account_id'], sent['metadata']['edp_student_id']),
                         (str(additional.pk), str(account.pk), self.student.student_code))
        self.assertNotIn('enquiry_id', sent['metadata'])  # No enquiry: Stripe stores no empty value.
        self.assertEqual((sent['customer'], sent['allowed_payment_method_types']), (first.stripe_customer_id, ['card']))
        # Stripe returns the Session's metadata exactly as it was sent.
        settled = self.paid(payment, self.gateway, metadata=sent['metadata'], mode='payment')
        self.assertEqual(settled.status_code, 200, settled.content)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'SUCCEEDED')
        state = client.get(f'/api/sales/purchases/{additional.pk}/').json()
        self.assertEqual((state['totals']['outstanding_amount'], state['totals']['fully_paid'], state['can_collect']), ('0', True, False))
        # No existing class-credit rule covers an additional purchase: the quota is unchanged.
        self.student.refresh_from_db()
        self.assertEqual((self.student.total_class_quota, state['totals']['classes_not_credited']), (D(10), '10'))
        self.assertEqual(Sale.objects.count(), 2)

    def test_a_mentor_expires_an_unpaid_link_of_their_students_purchase(self):
        self.enrolled()
        sale_id = self.purchase().json()['sale']['id']
        payment_id = self.link(sale_id).json()['payment']['id']
        url = f'/api/sales/purchases/{sale_id}/payments/{payment_id}/expire/'
        with mock.patch('sales.stripe_gateway.client', return_value=self.gateway):
            self.assertEqual(self.as_user(self.other_mentor).post(url, {}, format='json').status_code, 404)
            # The enquiry route that expires initial-sale links does not reach an additional purchase.
            self.assertEqual(self.client.post(f'/api/sales/payments/{payment_id}/expire/', {}, format='json').status_code, 404)
            self.assertEqual(self.as_user().post(url, {}, format='json').status_code, 200)
        self.assertEqual(Payment.objects.get(pk=payment_id).status, 'EXPIRED')

    def test_cases_without_an_established_rule_are_refused_until_decided(self):
        self.enrolled(mode='PARTIAL', classes='6')
        refused = self.purchase()
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'EARLIER_BALANCE_OUTSTANDING'))
        overview = self.as_user().get(f'/api/sales/students/{self.student.pk}/purchases/').json()
        self.assertEqual((overview['can_add'], overview['blockers'][0]['code']), (False, 'EARLIER_BALANCE_OUTSTANDING'))
        refused = self.purchase(collection_mode='AUTOPAY', preview=True)
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'AUTOPAY_PENDING_DECISION'))
        self.assertEqual(Sale.objects.count(), 1)
        # A student enrolled outside Eduport Plus payments has no account to add to.
        sheet = Student.objects.create(profile=user_account('sheet_learner', 'STUDENT'), student_code='EDP09001', full_name='Sheet Student',
                                       mentor=self.mentor)
        refused = self.as_user().get(f'/api/sales/students/{sheet.pk}/purchases/')
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'NO_STUDENT_ACCOUNT'))

    def test_the_database_keeps_a_purchase_on_its_own_students_account(self):
        self.enrolled()
        account = StudentAccount.objects.get()
        other_account = account_for(self.new_lead())
        snapshot = quotes.quote_snapshot(self.mentor, syllabus_id=self.bridge.pk, revision=1, plan_type='BRIDGE_COURSE', collection_mode='FULL')
        foreign = quotes.issue(dataclasses.replace(snapshot, account=other_account))
        sale = Sale.objects.create(account=account, kind='ADDITIONAL', student=self.student, created_by=self.mentor)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Purchase.objects.create(sale=sale, quote=foreign, student=self.student, collection_mode='FULL', amount=D(500), classes=D(10))
        stranger = Student.objects.create(profile=user_account('stranger_learner', 'STUDENT'), student_code='EDP09002', full_name='Stranger')
        with self.assertRaises(DatabaseError), transaction.atomic():
            Sale.objects.create(account=account, kind='ADDITIONAL', student=stranger, created_by=self.mentor)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Sale.objects.create(account=other_account, kind='ADDITIONAL', student=self.student, created_by=self.mentor)
