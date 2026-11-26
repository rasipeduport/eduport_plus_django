"""Additional hours paid through Stripe Checkout (sales.additional_hours_stripe).

Stripe transport is mocked throughout; no request leaves the test process. Every
payment is recorded by a signed webhook through the real webhook endpoint.
"""
import uuid
from decimal import Decimal as D
from unittest import mock

import stripe
from django.db import DatabaseError, IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from students.models import Student
from . import tests_payments as payment_helpers
from .allocation_models import AdditionalHoursAllocation, AdditionalHoursCheckout, AdditionalHoursPayment
from .ledger_models import ReviewKind, StripeReviewItem
from . import tests_additional_hours as hours_tests
from .tests_additional_hours import SETTINGS, in_days
from .tests_quotes import QuoteTestCase


# The additional-hours fixtures, borrowed without re-running their tests.
H = hours_tests.AdditionalHoursTests


@override_settings(**SETTINGS)
class AdditionalHoursStripeTests(QuoteTestCase, APITestCase):
    """A Bridge Course plan (10 classes, AED 500) paid in full, with 3 additional hours for AED 150 to pay."""
    payment_setup, new_lead, payload = H.payment_setup, H.new_lead, H.payload
    as_user, enroll, plan, add, added, pay, quota = H.as_user, H.enroll, H.plan, H.add, H.added, H.pay, H.quota
    webhook = payment_helpers.InitialPaymentTests.webhook

    def setUp(self):
        H.setUp(self)
        self.gateway = mock.MagicMock()
        payment_helpers.stripe_catalogue(self.gateway)
        self.customers = []
        self.sessions = []

        def customer(params, options):
            self.customers.append(params)
            return {'id': f'cus_{len(self.customers)}', 'livemode': False, **params}

        def session(params, options):
            self.sessions.append((params, options))
            return {'id': f'cs_test_hours_{len(self.sessions)}', 'object': 'checkout.session', 'livemode': False, 'currency': 'aed',
                    'url': f'https://checkout.stripe.com/c/pay/hours{len(self.sessions)}',
                    'amount_total': params['line_items'][0]['price_data']['unit_amount'], **params}
        self.gateway.v1.customers.create.side_effect = customer
        self.gateway.v1.checkout.sessions.create.side_effect = session
        self.gateway.v1.payment_intents.retrieve.return_value = {'id': 'pi_x', 'latest_charge': {
            'id': 'ch_hours', 'billing_details': {'name': 'Riya Nair'}, 'payment_method_details': {'card': {'brand': 'visa', 'last4': '4242'}}}}
        patcher = mock.patch('sales.stripe_gateway.client', return_value=self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.student = self.enroll()
        self.allocation = self.added(self.student)

    def link(self, user=None, allocation=None, **extra):
        body = {'request_id': str(uuid.uuid4()), **extra}
        return self.as_user(user or self.admin).post(
            f'/api/sales/additional-hours/{(allocation or self.allocation)["id"]}/stripe-links/', body, format='json')

    def linked(self, **extra):
        response = self.link(**extra)
        self.assertEqual(response.status_code, 201, response.content)
        return AdditionalHoursCheckout.objects.get(pk=response.json()['checkout']['id'])

    def event(self, checkout, event_type='checkout.session.completed', **overrides):
        checkout.refresh_from_db()
        obj = {'id': checkout.stripe_checkout_id, 'object': 'checkout.session', 'mode': 'payment', 'livemode': False,
               'customer': checkout.stripe_customer_id, 'amount_total': int(checkout.amount) * 100, 'currency': 'aed',
               'client_reference_id': str(checkout.pk), 'payment_status': 'paid', 'payment_intent': f'pi_{checkout.pk.hex}',
               'metadata': dict(checkout.request['metadata']), 'customer_details': {'email': 'parent@family.test'}, **overrides}
        return {'id': f'evt_{uuid.uuid4().hex}', 'object': 'event', 'type': event_type, 'livemode': False, 'data': {'object': obj}}

    def detail(self, user=None):
        return self.as_user(user or self.admin).get(f'/api/sales/additional-hours/{self.allocation["id"]}/').json()

    # --- generating a link ---------------------------------------------------

    def test_an_administrator_generates_one_checkout_session_for_what_is_still_due(self):
        response = self.link()
        self.assertEqual(response.status_code, 201, response.content)
        checkout = AdditionalHoursCheckout.objects.get()
        self.assertEqual((checkout.status, checkout.amount, checkout.stripe_checkout_id), ('OPEN', D(150), 'cs_test_hours_1'))
        params, options = self.sessions[0]
        self.assertEqual(options, {'idempotency_key': f'eduport-additional-hours-checkout-{checkout.pk}'})
        self.assertEqual(params['line_items'], [{'price_data': {'currency': 'aed', 'unit_amount': 15000,
                                                                'product': 'eduport_plus_tuition'}, 'quantity': 1}])
        self.assertEqual((params['mode'], params['customer'], params['client_reference_id'], params['allowed_payment_method_types']),
                         ('payment', 'cus_1', str(checkout.pk), ['card']))
        self.assertEqual(params['metadata']['additional_hours_checkout_id'], str(checkout.pk))
        self.assertEqual(params['metadata']['additional_hours_ref'], self.allocation['reference'])
        self.assertEqual(params['metadata']['edp_student_id'], self.student.student_code)
        self.assertEqual(params['payment_intent_data']['metadata'], params['metadata'])
        self.assertTrue(params['success_url'].endswith('/payment-return?result=submitted'))
        body = response.json()
        self.assertEqual(body['checkout']['checkout_url'], 'https://checkout.stripe.com/c/pay/hours1')
        self.assertEqual(body['allocation']['open_checkout']['id'], str(checkout.pk))
        self.assertEqual((body['allocation']['can_record_payment'], body['allocation']['can_generate_link']), (False, False))
        self.assertTrue(ActivityLog.objects.filter(action='additional_hours.stripe_link').exists())
        # The same request again is the same link: Stripe is not asked twice.
        again = self.link(request_id=str(checkout.pk))
        self.assertEqual((again.status_code, again.json()['checkout']['id'], len(self.sessions)), (200, str(checkout.pk), 1))
        # One live link per allocation.
        refused = self.link()
        self.assertEqual((refused.status_code, refused.json()['error'], refused.json()['checkout_id']), (409, 'STRIPE_LINK_OPEN', str(checkout.pk)))
        self.assertEqual(self.quota(self.student), D(13))

    def test_the_students_own_mentor_generates_and_expires_a_link_and_no_one_else(self):
        self.assertEqual(self.link(user=self.other_mentor).status_code, 404)
        self.assertEqual(self.link(user=self.tutor).status_code, 403)
        self.assertEqual(self.link(user=self.bde).status_code, 403)
        response = self.link(user=self.mentor, amount='60')
        self.assertEqual(response.status_code, 201, response.content)
        checkout = AdditionalHoursCheckout.objects.get()
        self.assertEqual((checkout.amount, checkout.created_by, self.sessions[0][0]['line_items'][0]['price_data']['unit_amount']),
                         (D(60), self.mentor, 6000))
        expire_url = f'/api/sales/additional-hours/{self.allocation["id"]}/stripe-links/{checkout.pk}/expire/'
        self.assertEqual(self.as_user(self.other_mentor).post(expire_url).status_code, 404)
        self.gateway.v1.checkout.sessions.expire.side_effect = stripe.InvalidRequestError('Session is complete', None)
        refused = self.as_user(self.mentor).post(expire_url)
        self.assertEqual((refused.status_code, refused.json()['error']), (503, 'STRIPE_UNAVAILABLE'))
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'OPEN', 'only Stripe’s confirmation closes a link')
        self.gateway.v1.checkout.sessions.expire.side_effect = None
        expired = self.as_user(self.mentor).post(expire_url)
        self.assertEqual(expired.status_code, 200, expired.content)
        self.gateway.v1.checkout.sessions.expire.assert_called_with('cs_test_hours_1')
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'EXPIRED')
        self.assertEqual(self.as_user(self.mentor).post(expire_url).json()['error'], 'CHECKOUT_NOT_OPEN')
        self.assertEqual(self.link(user=self.mentor).status_code, 201, 'a new link once the last one is closed')
        # Mentors never gain the administrators' actions.
        self.assertEqual(self.as_user(self.mentor).post(f'/api/sales/additional-hours/{self.allocation["id"]}/waive/', {'reason': 'x'}).status_code, 403)

    def test_a_link_is_for_at_most_what_is_still_due_on_open_hours_with_stripe_configured(self):
        refused = self.link(amount='151')
        self.assertEqual((refused.status_code, refused.json()['error'], refused.json()['outstanding']), (409, 'EXCEEDS_OUTSTANDING', '150'))
        self.assertEqual(self.link(amount='0').status_code, 400)
        self.assertEqual(self.link(amount='10.5').status_code, 400)
        with override_settings(STRIPE_SECRET_KEY=''):
            self.assertEqual(self.link().json()['error'], 'STRIPE_NOT_CONFIGURED')
        self.assertEqual(self.pay(self.allocation['id'], amount='150').status_code, 201)
        self.assertEqual(self.link().json()['error'], 'ALLOCATION_PAID')
        other = self.added(self.student, hours='1', amount='50', confirm_duplicate=True)
        self.as_user(self.admin).post(f'/api/sales/additional-hours/{other["id"]}/waive/', {'reason': 'Goodwill.'}, format='json')
        self.assertEqual(self.link(allocation=other).json()['error'], 'ALLOCATION_CLOSED')
        self.assertFalse(AdditionalHoursCheckout.objects.exists())
        self.assertEqual(self.sessions, [])

    # --- the verified webhook -------------------------------------------------

    def test_only_the_verified_webhook_records_the_payment_once_without_touching_the_quota(self):
        checkout = self.linked()
        # The parent coming back from Checkout proves nothing; nothing is recorded until Stripe's signed event.
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        self.assertEqual(self.webhook(self.event(checkout), valid=False).status_code, 400)
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        event = self.event(checkout)
        response = self.webhook(event)
        self.assertEqual((response.status_code, response.json()['outcome']), (200, 'PROCESSED'))
        payment = AdditionalHoursPayment.objects.get()
        self.assertEqual((payment.method, payment.amount, payment.proof.name, payment.stripe_checkout_id, payment.stripe_payment_intent_id,
                          payment.transaction_reference, payment.recorded_by, payment.stripe_charge_id),
                         ('STRIPE', D(150), '', 'cs_test_hours_1', f'pi_{checkout.pk.hex}', f'pi_{checkout.pk.hex}', self.admin, 'ch_hours'))
        self.assertEqual(payment.payer_details['card_last4'], '4242')
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'PAID')
        state = self.detail(self.mentor)
        self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount'], state['open_checkout']), ('PAID', '150', '0', None))
        row = state['payments'][0]
        self.assertEqual((row['source'], row['method'], row['proof_url'], row['stripe_payment_intent_id']),
                         ('STRIPE', 'STRIPE', None, f'pi_{checkout.pk.hex}'))
        self.assertEqual(self.quota(self.student), D(13), 'a payment never changes the quota')
        # Stripe delivering the same event again, or another event for the same Session, records nothing more.
        self.assertEqual(self.webhook(event).json()['outcome'], 'PROCESSED')
        self.assertEqual(self.webhook(self.event(checkout, 'checkout.session.async_payment_succeeded')).json()['outcome'], 'DUPLICATE')
        self.assertEqual(AdditionalHoursPayment.objects.count(), 1)
        self.assertFalse(StripeReviewItem.objects.exists(), 'never mistaken for a Checkout Django did not create')
        self.assertTrue(ActivityLog.objects.filter(action='additional_hours.payment_record', context__method='STRIPE').exists())

    def test_unpaid_failed_and_expired_sessions_record_nothing_and_free_the_link(self):
        checkout = self.linked()
        self.assertEqual(self.webhook(self.event(checkout, payment_status='unpaid')).json()['outcome'], 'AWAITING_PAYMENT')
        self.assertEqual(self.webhook(self.event(checkout, 'checkout.session.async_payment_failed')).json()['outcome'], 'PROCESSED')
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'FAILED')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        second = self.linked()
        self.assertEqual(self.webhook(self.event(second, 'checkout.session.expired', payment_status='unpaid')).json()['outcome'], 'PROCESSED')
        second.refresh_from_db()
        self.assertEqual(second.status, 'EXPIRED')
        self.assertEqual(self.webhook(self.event(second, 'checkout.session.expired', payment_status='unpaid')).json()['outcome'], 'DUPLICATE')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        state = self.detail()
        self.assertEqual((state['status'], state['outstanding_amount'], state['can_generate_link']), ('PENDING', '150', True))
        self.assertEqual([row['status'] for row in state['checkouts']], ['EXPIRED', 'FAILED'])
        self.assertIsNone(state['checkouts'][0]['checkout_url'], 'a closed link is never shown to share')

    def test_partial_payments_by_any_route_and_the_remaining_balance(self):
        self.assertEqual(self.pay(self.allocation['id'], amount='50').status_code, 201)
        first = self.linked(amount='60')
        self.webhook(self.event(first))
        state = self.detail()
        self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount']), ('PARTIALLY_PAID', '110', '40'))
        # Without an amount, a link is for all that is still due.
        rest = self.linked()
        self.assertEqual(rest.amount, D(40))
        self.webhook(self.event(rest))
        state = self.detail()
        self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount']), ('PAID', '150', '0'))
        self.assertEqual([row['method'] for row in state['payments']], ['TRANSFER', 'STRIPE', 'STRIPE'])
        self.assertEqual(self.quota(self.student), D(13))

    def test_an_open_link_holds_what_is_owed_until_it_is_paid_or_expired(self):
        checkout = self.linked()
        admin = self.as_user(self.admin)
        url = f'/api/sales/additional-hours/{self.allocation["id"]}/'
        self.assertEqual(self.pay(self.allocation['id']).json()['error'], 'STRIPE_LINK_OPEN')
        self.assertEqual(admin.patch(url, {'amount': '100', 'change_reason': 'x'}, format='json').json()['error'], 'STRIPE_LINK_OPEN')
        self.assertEqual(admin.post(f'{url}waive/', {'reason': 'x'}, format='json').json()['error'], 'STRIPE_LINK_OPEN')
        self.assertEqual(admin.post(f'{url}withdraw/', {'reason': 'x'}, format='json').json()['error'], 'STRIPE_LINK_OPEN')
        # The due date is not what is owed: it may still move.
        self.assertEqual(admin.patch(url, {'due_date': in_days(30), 'change_reason': 'Parent asked.'}, format='json').status_code, 200)
        self.webhook(self.event(checkout, 'checkout.session.expired', payment_status='unpaid'))
        self.assertEqual(self.pay(self.allocation['id']).status_code, 201)

    def test_a_payment_the_hours_can_no_longer_take_is_queued_for_review_never_applied(self):
        checkout = self.linked()
        # Waived meanwhile (the API refuses while the link is open, so straight in the database).
        AdditionalHoursAllocation.objects.filter(pk=self.allocation['id']).update(
            waived_at=timezone.now(), waived_by=self.admin, waive_reason='Forced for the test.')
        response = self.webhook(self.event(checkout))
        self.assertEqual((response.status_code, response.json()['outcome']), (200, 'REVIEW'), 'acknowledged: Stripe must not retry it')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'REQUIRES_REVIEW')
        self.assertIn('after what was still due was waived: not recorded', checkout.message)
        item = StripeReviewItem.objects.get()
        self.assertEqual((item.kind, item.object_id, item.amount), (ReviewKind.INCONSISTENT, checkout.stripe_checkout_id, D(150)))
        self.assertIn(self.allocation['reference'], item.summary)
        self.assertEqual(self.webhook(self.event(checkout)).json()['outcome'], 'DUPLICATE')
        self.assertEqual(StripeReviewItem.objects.count(), 1)
        self.assertEqual(self.detail()['checkouts'][0]['message'], checkout.message)

        # Withdrawn meanwhile: the same. The quota moves with the withdrawal, never with the payment.
        other = self.added(self.student, hours='1', amount='50', confirm_duplicate=True)
        second = self.linked(allocation=other)
        with transaction.atomic():
            Student.objects.filter(pk=self.student.pk).update(total_class_quota=D(13))
            AdditionalHoursAllocation.objects.filter(pk=other['id']).update(
                withdrawn_at=timezone.now(), withdrawn_by=self.admin, withdraw_reason='Forced.', withdrawn_quota_before=D(14))
        self.assertEqual(self.webhook(self.event(second)).json()['outcome'], 'REVIEW')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        self.assertEqual(self.quota(self.student), D(13))

    def test_a_payment_more_than_is_still_due_is_never_recorded(self):
        checkout = self.linked()
        # A direct payment slipped in beside the open link (the API refuses it; straight in the database).
        AdditionalHoursPayment.objects.create(request_id=uuid.uuid4(), allocation_id=self.allocation['id'], amount=D(100), method='TRANSFER',
                                              payment_date=timezone.localdate(), received_confirmed=True, proof='additional-hours-proofs/x.png',
                                              recorded_by=self.admin)
        self.assertEqual(self.webhook(self.event(checkout)).json()['outcome'], 'REVIEW')
        checkout.refresh_from_db()
        self.assertIn('only AED 50 was still due', checkout.message)
        self.assertEqual(AdditionalHoursPayment.objects.filter(method='STRIPE').count(), 0)
        self.assertEqual(self.detail()['paid_amount'], '100')

    def test_a_session_that_does_not_match_its_link_is_rejected_for_review(self):
        checkout = self.linked()
        for changes in ({'amount_total': 14900}, {'currency': 'usd'}, {'customer': 'cus_other'}, {'client_reference_id': 'other'}):
            with self.subTest(changes=changes):
                response = self.webhook(self.event(checkout, **changes))
                self.assertEqual((response.status_code, response.json()['outcome']), (400, 'REJECTED'))
        unknown = self.event(checkout)
        unknown['data']['object']['metadata']['additional_hours_checkout_id'] = str(uuid.uuid4())
        self.assertEqual(self.webhook(unknown).json()['outcome'], 'REJECTED')
        self.assertFalse(AdditionalHoursPayment.objects.exists())
        self.assertTrue(StripeReviewItem.objects.filter(kind=ReviewKind.INCONSISTENT).exists())
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'OPEN')

    def test_a_lost_creation_response_is_recovered_never_duplicated(self):
        self.gateway.v1.checkout.sessions.create.side_effect = stripe.APIConnectionError('timed out')
        request_id = str(uuid.uuid4())
        refused = self.link(request_id=request_id)
        self.assertEqual((refused.status_code, refused.json()['error']), (503, 'STRIPE_UNAVAILABLE'))
        checkout = AdditionalHoursCheckout.objects.get()
        self.assertEqual(checkout.status, 'UNKNOWN')
        self.assertEqual(self.link().json()['error'], 'STRIPE_LINK_OPEN', 'no second link while Stripe may have made the first')
        # Stripe had created it: the retry finds it by its own metadata and creates nothing.
        remote = {'id': 'cs_test_recovered', 'object': 'checkout.session', 'livemode': False, 'currency': 'aed', 'mode': 'payment',
                  'customer': 'cus_1', 'url': 'https://checkout.stripe.com/c/pay/recovered', 'client_reference_id': request_id,
                  'amount_total': 15000, 'metadata': dict(checkout.request['metadata'])}
        self.gateway.v1.checkout.sessions.list.return_value = mock.MagicMock(auto_paging_iter=lambda: iter([remote]))
        self.gateway.v1.checkout.sessions.create.reset_mock()
        again = self.link(request_id=request_id)
        self.assertEqual((again.status_code, again.json()['checkout']['checkout_url']), (200, 'https://checkout.stripe.com/c/pay/recovered'))
        self.gateway.v1.checkout.sessions.create.assert_not_called()
        checkout.refresh_from_db()
        self.assertEqual((checkout.status, checkout.stripe_checkout_id), ('OPEN', 'cs_test_recovered'))

    def test_a_signed_event_recovers_a_link_whose_response_was_lost(self):
        self.gateway.v1.checkout.sessions.create.side_effect = stripe.APIConnectionError('timed out')
        request_id = str(uuid.uuid4())
        self.link(request_id=request_id)
        checkout = AdditionalHoursCheckout.objects.get()
        event = self.event(checkout, id='cs_test_lost', customer='cus_1')
        self.assertEqual(self.webhook(event).json()['outcome'], 'PROCESSED')
        checkout.refresh_from_db()
        self.assertEqual((checkout.status, checkout.stripe_checkout_id), ('PAID', 'cs_test_lost'))
        self.assertEqual(AdditionalHoursPayment.objects.get().amount, D(150))

    def test_the_database_keeps_links_and_stripe_payments_honest(self):
        checkout = self.linked()
        with self.assertRaises(IntegrityError), transaction.atomic():
            # A second live link for the same hours.
            AdditionalHoursCheckout.objects.create(id=uuid.uuid4(), allocation_id=self.allocation['id'], amount=D(10), livemode=False,
                                                   request={}, idempotency_key='second', created_by=self.admin)
        with self.assertRaises(DatabaseError), transaction.atomic():
            # A Stripe payment without its paid Checkout.
            AdditionalHoursPayment.objects.create(request_id=uuid.uuid4(), allocation_id=self.allocation['id'], amount=D(150), method='STRIPE',
                                                  payment_date=timezone.localdate(), recorded_by=self.admin, checkout=checkout,
                                                  stripe_checkout_id=checkout.stripe_checkout_id, stripe_payment_intent_id='pi_forged')
        with self.assertRaises(DatabaseError), transaction.atomic():
            # A direct payment without its receipt.
            AdditionalHoursPayment.objects.create(request_id=uuid.uuid4(), allocation_id=self.allocation['id'], amount=D(10), method='TRANSFER',
                                                  payment_date=timezone.localdate(), received_confirmed=True, recorded_by=self.admin)
        for change in (lambda: AdditionalHoursCheckout.objects.filter(pk=checkout.pk).update(amount=D(1)),
                       lambda: AdditionalHoursCheckout.objects.filter(pk=checkout.pk).update(stripe_checkout_id='cs_other'),
                       lambda: AdditionalHoursCheckout.objects.filter(pk=checkout.pk).delete()):
            with self.subTest(change=change), self.assertRaises(DatabaseError), transaction.atomic():
                change()
        self.webhook(self.event(checkout))
        with self.assertRaises(DatabaseError), transaction.atomic():
            AdditionalHoursCheckout.objects.filter(pk=checkout.pk).update(status='EXPIRED')
        with self.assertRaises(DatabaseError), transaction.atomic():
            AdditionalHoursPayment.objects.filter(method='STRIPE').update(amount=D(1))

    # --- one payment history -------------------------------------------------

    def test_every_recorded_payment_by_any_method_is_listed_and_never_a_link(self):
        hours_id = self.allocation['id']
        payments_url = f'/api/sales/additional-hours/{hours_id}/payments/'
        self.assertEqual(self.pay(hours_id, amount='20', transaction_reference='UTR-1').status_code, 201)
        uae = self.pay(hours_id, amount='10', method='AJAS_UAE', transaction_reference='UAE-1').json()['payment']
        self.assertEqual(self.pay(hours_id, amount='15', method='AJAS_INDIA').status_code, 201)
        voided = self.as_user(self.admin).post(f'{payments_url}{uae["id"]}/void/', {'kind': 'ERROR', 'reason': 'Entered twice.'}, format='json')
        self.assertEqual(voided.status_code, 200, voided.content)
        # Links that failed or expired, and one generated but not yet paid: none of them is a payment.
        failed = self.linked(amount='30')
        self.webhook(self.event(failed, 'checkout.session.async_payment_failed'))
        expired = self.linked(amount='30')
        self.webhook(self.event(expired, 'checkout.session.expired', payment_status='unpaid'))
        paid = self.linked(amount='40')
        self.assertEqual(len(self.detail()['payments']), 3, 'a link is not a payment')
        self.webhook(self.event(paid))
        for user in (self.admin, self.mentor):
            with self.subTest(role=user.role):
                state = self.detail(user)
                rows = state['payments']
                self.assertEqual([(row['method'], row['amount'], row['voided']) for row in rows],
                                 [('TRANSFER', '20', False), ('AJAS_UAE', '10', True), ('AJAS_INDIA', '15', False), ('STRIPE', '40', False)])
                # Only payments not voided count: 20 + 15 + 40 of 150.
                self.assertEqual((state['status'], state['paid_amount'], state['outstanding_amount']), ('PARTIALLY_PAID', '75', '75'))
                self.assertEqual(rows[1]['void']['reason'], 'Entered twice.')
                for row in rows[:3]:
                    self.assertEqual((row['source'], row['recorded_by']['id']), ('DIRECT', str(self.mentor.pk)))
                    self.assertIsNotNone(row['proof_url'])
                self.assertEqual((rows[3]['source'], rows[3]['method_label'], rows[3]['proof_url'], rows[3]['transaction_reference']),
                                 ('STRIPE', 'Stripe', None, f'pi_{paid.pk.hex}'))
                self.assertEqual(sorted(checkout['status'] for checkout in state['checkouts']), ['EXPIRED', 'FAILED', 'PAID'])
        self.assertEqual(AdditionalHoursPayment.objects.count(), 4)

    def test_closed_hours_keep_their_payment_history_for_the_administrator_and_their_mentor_only(self):
        hours_id = self.allocation['id']
        url = f'/api/sales/additional-hours/{hours_id}/'
        admin = self.as_user(self.admin)
        self.assertEqual(self.pay(hours_id, amount='50').status_code, 201)
        self.webhook(self.event(self.linked(amount='40')))
        self.assertEqual(admin.post(url + 'waive/', {'reason': 'Goodwill after a missed class.'}, format='json').status_code, 200)
        proof_url = self.detail()['payments'][0]['proof_url']
        for user in (self.admin, self.mentor):
            with self.subTest(role=user.role):
                state = self.detail(user)
                self.assertEqual((state['status'], state['paid_amount'], state['waived_amount'], state['outstanding_amount'],
                                  state['can_record_payment'], state['can_generate_link']), ('WAIVED', '90', '60', '0', False, False))
                self.assertEqual([row['method'] for row in state['payments']], ['TRANSFER', 'STRIPE'])
                self.assertEqual(self.as_user(user).get(proof_url).status_code, 200, 'the receipt still downloads')
        self.assertEqual(self.as_user(self.other_mentor).get(url).status_code, 404)
        self.assertEqual(self.as_user(self.other_mentor).get(proof_url).status_code, 404)
        for user in (self.tutor, self.bde):
            with self.subTest(role=user.role):
                self.assertEqual(self.as_user(user).get(url).status_code, 403)
                self.assertEqual(self.as_user(user).get(proof_url).status_code, 403)
        self.assertIn(APIClient().get(url).status_code, (401, 403))

        # Withdrawn once its only payment was voided: the voided payment stays listed and counts for nothing.
        other = self.added(self.student, hours='1', amount='50', confirm_duplicate=True)
        other_url = f'/api/sales/additional-hours/{other["id"]}/'
        payment = self.pay(other['id'], amount='50', transaction_reference='UTR-W').json()['payment']
        self.assertEqual(admin.post(f'{other_url}payments/{payment["id"]}/void/', {'kind': 'REFUNDED', 'reason': 'Money returned.'},
                                    format='json').status_code, 200)
        self.assertEqual(admin.post(other_url + 'withdraw/', {'reason': 'Given by mistake.'}, format='json').status_code, 200)
        state = self.as_user(self.mentor).get(other_url).json()
        self.assertEqual((state['status'], state['hours_status'], state['paid_amount'], state['can_record_payment']),
                         ('CANCELLED', 'WITHDRAWN', '0', False))
        self.assertEqual([(row['id'], row['voided'], row['void']['kind']) for row in state['payments']], [(payment['id'], True, 'REFUNDED')])
