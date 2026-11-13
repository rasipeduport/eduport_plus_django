"""Student-centric financial identity: accounts, Customers, Checkout identity, ledger and webhooks.

Stripe transport is mocked throughout; no request leaves the test process.
"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier
from types import SimpleNamespace
from unittest import mock

from django.db import DatabaseError, IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from students.models import Student
from . import customers, quotes
from .account_models import Guardian, StudentAccount, StudentGuardian, StudentIdentityCorrection
from .ledger_models import Dispute, Refund, StripeReviewItem
from .payment_models import Payment, StripeCustomer, StripeEvent
from .tests_lifecycle import account as user_account
from . import tests_payments as payment_helpers
from .tests_payments import account_for, stripe_catalogue
from .tests_quotes import QuoteTestCase, lead_of


def page(rows):
    return SimpleNamespace(auto_paging_iter=lambda: iter(rows))


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False,
                   LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class StudentAccountTests(QuoteTestCase, APITestCase):
    """The initial-sale fixtures (Bridge Course, 10 classes, AED 500, owned by self.bde), without re-running their tests."""
    setUp = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    url = payment_helpers.InitialPaymentTests.url
    start = payment_helpers.InitialPaymentTests.start
    payload = payment_helpers.InitialPaymentTests.payload
    collect = payment_helpers.InitialPaymentTests.collect
    stripe_transport = payment_helpers.InitialPaymentTests.stripe_transport
    event = payment_helpers.InitialPaymentTests.event
    webhook = payment_helpers.InitialPaymentTests.webhook

    def child(self, name, phone, email, collection_mode='PARTIAL'):
        lead = lead_of(self.bde, name, phone)
        lead.parent_name, lead.parent_email = 'Mohammed Rahman', email
        lead.save(update_fields=['parent_name', 'parent_email'])
        quotes.create_quote(self.bde, {'collection_mode': collection_mode, 'syllabus': self.bridge.pk, 'revision': 1,
                                       'plan_type': 'BRIDGE_COURSE', 'lead': lead.pk})
        return lead

    def start_for(self, lead, **extra):
        return self.client.post(f'/api/sales/enquiries/{lead.pk}/sale/', {'kind': 'NEW', **extra}, format='json')

    def link_for(self, lead, gateway, classes='6', mode='PARTIAL'):
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.client.post(f'/api/sales/enquiries/{lead.pk}/sale/payments/', {
                'request_id': str(uuid.uuid4()), 'method': 'STRIPE', 'purpose': 'TUITION', 'collection_mode': mode,
                'classes': classes}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return Payment.objects.get(pk=response.json()['payment']['id'])

    def transport(self):
        gateway, calls = self.stripe_transport()
        created = []

        def customer(params, options):
            created.append((params, options))
            return {'id': f'cus_{len(created)}', 'livemode': False, **params}
        gateway.v1.customers.create.side_effect = customer
        return gateway, calls, created

    def paid(self, payment, gateway, **overrides):
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            return self.webhook(self.event(payment, **overrides))

    # --- Customer identity -------------------------------------------------

    def test_siblings_sharing_parent_contacts_get_separate_accounts_customers_and_payments(self):
        aarav = self.child('Aarav Rahman', '509111001', 'mohammed@family.test')
        maya = self.child('Maya Rahman', '509111001', 'MOHAMMED@family.test')
        self.assertEqual(self.start_for(aarav).status_code, 201)
        # Same phone and email: nothing is linked or created until a person decides.
        refused = self.start_for(maya)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()['error'], 'FAMILY_CONFIRMATION_REQUIRED')
        family = refused.json()['candidates']
        self.assertEqual([child['student_name'] for child in family[0]['children']], ['Aarav Rahman'])
        self.assertEqual(sorted(family[0]['matched_on']), ['email', 'phone'])
        self.assertEqual(StudentAccount.objects.count(), 1)
        # A guardian outside the suggestions cannot be attached by ID.
        stranger = Guardian.objects.create(full_name='Unrelated Parent', email='other@family.test')
        self.assertEqual(self.start_for(maya, confirm_distinct_child=True, family={'mode': 'EXISTING_FAMILY', 'guardian_id': str(stranger.pk)})
                         .json()['error'], 'INVALID_FAMILY')
        joined = self.start_for(maya, confirm_distinct_child=True, family={'mode': 'EXISTING_FAMILY', 'guardian_id': family[0]['guardian_id']})
        self.assertEqual(joined.status_code, 201, joined.content)
        first, second = StudentAccount.objects.order_by('reference')
        self.assertEqual((first.student_name, second.student_name), ('Aarav Rahman', 'Maya Rahman'))
        self.assertRegex(first.reference, r'^SA-\d{6}$')
        self.assertNotEqual(first.reference, second.reference)
        self.assertEqual(first.billing_link().guardian_id, second.billing_link().guardian_id)
        self.assertEqual(second.billing_link().basis, 'EXISTING_FAMILY')

        gateway, _, created = self.transport()
        first_payment = self.link_for(aarav, gateway)
        second_payment = self.link_for(maya, gateway)
        self.assertEqual([params['name'] for params, _ in created], ['Aarav Rahman', 'Maya Rahman'])
        self.assertEqual({params['email'] for params, _ in created}, {'mohammed@family.test'})
        self.assertEqual([params['metadata']['eduport_account_ref'] for params, _ in created], [first.reference, second.reference])
        self.assertNotEqual(first_payment.stripe_customer_id, second_payment.stripe_customer_id)
        self.assertEqual(StripeCustomer.objects.get(account=first).customer_id, first_payment.stripe_customer_id)
        self.assertEqual(StripeCustomer.objects.get(account=second).customer_id, second_payment.stripe_customer_id)
        # A session on the sibling's Customer can never settle this child's payment.
        response = self.paid(first_payment, gateway, customer=second_payment.stripe_customer_id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Student.objects.exists())
        self.assertEqual(StripeReviewItem.objects.get().kind, 'INCONSISTENT')

    def test_every_payment_of_a_child_reuses_its_one_customer_and_creation_is_idempotent(self):
        self.lead = self.new_lead(collection_mode='FULL')
        self.start('TOKEN', expected_start_date='2099-01-01')
        gateway, calls, created = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            token = Payment.objects.get()
            self.assertEqual(self.webhook(self.event(token)).status_code, 200)
            tuition = self.client.post(self.url('payments/'), {'request_id': str(uuid.uuid4()), 'method': 'STRIPE', 'purpose': 'TUITION',
                                                              'collection_mode': 'FULL', 'classes': '10'}, format='json')
            self.assertEqual(tuition.status_code, 201, tuition.content)
            account = StudentAccount.objects.get()
            # Repeating resolution never creates or replaces the Customer.
            self.assertEqual(customers.customer_for(account.pk, gateway, False), token.stripe_customer_id)
        self.assertEqual(len(created), 1)
        self.assertEqual(StripeCustomer.objects.filter(account=account).count(), 1)
        self.assertEqual({payment.stripe_customer_id for payment in Payment.objects.all()}, {'cus_1'})
        self.assertEqual([call['line_items'][0]['price_data']['product'] for call in calls], ['eduport_plus_token', 'eduport_plus_tuition'])
        self.assertEqual(StripeCustomer.objects.get().stripe_account_id, 'acct_test_unit')
        with self.assertRaises(IntegrityError), transaction.atomic():
            StripeCustomer.objects.create(account=account, livemode=False, stripe_account_id='acct_test_unit')

    def test_legacy_enquiry_customer_is_verified_reused_and_never_renamed(self):
        self.start()
        account = StudentAccount.objects.get()
        legacy = StripeCustomer.objects.create(account=account, legacy_enquiry=self.lead, label_format='LEGACY_PARENT',
                                               customer_id='cus_legacy_parent', student_metadata_synced=True,
                                               creation_request={'name': self.lead.parent_name, 'metadata': {'enquiry_id': str(self.lead.pk)}})
        gateway, _, created = self.transport()
        gateway.v1.customers.retrieve.return_value = {'id': 'cus_legacy_parent', 'livemode': False, 'name': self.lead.parent_name}
        payment = self.link_for(self.lead, gateway)
        self.assertEqual(payment.stripe_customer_id, 'cus_legacy_parent')
        self.assertEqual(created, [])
        legacy.refresh_from_db()
        self.assertEqual(legacy.stripe_account_id, 'acct_test_unit')
        self.assertEqual(self.paid(payment, gateway).status_code, 200)
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            customers.sync_labels(legacy.pk)
        body = gateway.v1.customers.update.call_args.args[1]
        self.assertNotIn('name', body)
        self.assertEqual(body['metadata']['edp_student_id'], Student.objects.get().student_code)

    def test_existing_parent_email_is_prefilled_through_the_customer(self):
        self.start()
        gateway, calls, created = self.transport()
        self.link_for(self.lead, gateway)
        # Stripe prefills (and locks) the email of the Customer passed in; nothing else is sent.
        self.assertEqual(created[0][0]['email'], self.lead.parent_email)
        self.assertNotIn('customer_email', calls[0])

    def test_missing_parent_email_is_collected_on_checkout_and_saved_after_verified_payment(self):
        self.lead.parent_email = ''
        self.lead.save(update_fields=['parent_email'])
        self.start()
        gateway, calls, created = self.transport()
        payment = self.link_for(self.lead, gateway)  # Not blocked by the missing email.
        self.assertNotIn('email', created[0][0])  # Checkout asks for it and saves it on this Customer.
        account = StudentAccount.objects.get()
        # An abandoned or expired Checkout never makes its email a verified contact.
        self.assertEqual(self.paid(payment, gateway, event_type='checkout.session.expired',
                                   customer_details={'email': 'typed@parent.test'}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.parent_email, account.billing_link().guardian.email), ('', ''))
        second = self.link_for(self.lead, gateway)
        self.assertEqual(self.paid(second, gateway, customer_details={'email': ' Typed@Parent.TEST '}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.parent_email, account.billing_link().guardian.email), ('typed@parent.test', 'typed@parent.test'))
        self.assertEqual(StripeCustomer.objects.get().customer_id, second.stripe_customer_id)

    def test_a_checkout_email_never_overwrites_django_or_saves_an_invalid_address(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        self.assertEqual(self.paid(payment, gateway, customer_details={'email': 'someone-else@payer.test'}).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.parent_email, StudentAccount.objects.get().billing_link().guardian.email)
        self.assertNotEqual(self.lead.parent_email, 'someone-else@payer.test')
        payment.refresh_from_db()
        self.assertEqual(payment.payer_details['email'], 'someone-else@payer.test')  # Kept as payment evidence only.
        from .student_accounts import capture_checkout_email
        empty = self.child('Email Less', '509222001', '')
        self.assertEqual(self.start_for(empty).status_code, 201)
        self.assertEqual(capture_checkout_email(empty.initial_sale, 'not-an-email'), [])
        empty.refresh_from_db()
        self.assertEqual(empty.parent_email, '')

    # --- Normal one-time payments ------------------------------------------

    def test_full_payment_settles_the_sale(self):
        self.lead = self.new_lead(collection_mode='FULL')
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway, classes='10', mode='FULL')
        self.assertEqual(payment.amount, D(500))
        self.assertEqual(self.paid(payment, gateway).status_code, 200)
        state = self.client.get(self.url()).json()
        self.assertEqual((state['totals']['paid_amount'], state['totals']['outstanding_amount'], state['totals']['fully_paid']), ('500', '0', True))
        self.assertFalse(state['can_collect'])
        self.assertEqual(Student.objects.get().total_class_quota, D(10))

    def test_partial_payment_then_remaining_balance_link_on_the_same_sale(self):
        self.start()
        gateway, calls, created = self.transport()
        first = self.link_for(self.lead, gateway)
        self.assertEqual(self.paid(first, gateway).status_code, 200)
        student = Student.objects.get()
        self.assertEqual(student.total_class_quota, D(6))
        state = self.client.get(self.url()).json()
        self.assertTrue(state['can_collect'])
        self.assertEqual((state['totals']['outstanding_amount'], state['account']['student']['student_code']), ('200', student.student_code))
        # More than the remaining balance is refused before anything reaches Stripe.
        over = self.client.post(self.url('payments/'), {'request_id': str(uuid.uuid4()), 'method': 'STRIPE', 'purpose': 'TUITION',
                                                       'collection_mode': 'PARTIAL', 'classes': '6'}, format='json')
        self.assertEqual((over.status_code, over.json()['error']), (400, 'INVALID_ALLOCATION'))
        second = self.link_for(self.lead, gateway, classes='4')
        self.assertEqual((second.amount, second.sale_id, second.stripe_customer_id), (D(200), first.sale_id, first.stripe_customer_id))
        self.assertEqual(calls[-1]['metadata']['edp_student_id'], student.student_code)
        # A second link while one is pending is refused (no double collection).
        pending = self.client.post(self.url('payments/'), {'request_id': str(uuid.uuid4()), 'method': 'STRIPE', 'purpose': 'TUITION',
                                                          'collection_mode': 'PARTIAL', 'classes': '4'}, format='json')
        self.assertEqual(pending.json()['error'], 'PAYMENT_PENDING')
        event = self.event(second)
        self.assertEqual(self.paid(second, gateway).status_code, 200)
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event).status_code, 200)  # Re-delivery.
        student.refresh_from_db()
        # Two separate payments and Stripe transactions on one Sale and purchase; the
        # agreed AED 500 is unchanged. Class credit follows the existing rules only.
        self.assertEqual(student.total_class_quota, D(6))
        received = Payment.objects.filter(sale_id=first.sale_id, status='SUCCEEDED').order_by('verified_at')
        self.assertEqual([(row.amount, row.purchase_id) for row in received], [(D(300), first.purchase_id), (D(200), first.purchase_id)])
        self.assertNotEqual(received[0].stripe_payment_intent, received[1].stripe_payment_intent)
        self.assertEqual(len(created), 1)
        state = self.client.get(self.url()).json()
        self.assertEqual((state['totals']['package_amount'], state['totals']['outstanding_amount'], state['totals']['fully_paid'],
                          state['can_collect']), ('500', '0', True, False))
        self.assertEqual(state['totals']['classes_not_credited'], '4')

    # --- Checkout identity --------------------------------------------------

    def test_checkout_uses_django_identity_and_asks_the_parent_for_payment_details_only(self):
        self.start()
        gateway, calls, created = self.transport()
        payment = self.link_for(self.lead, gateway)
        params, account = calls[0], StudentAccount.objects.get()
        customer = created[0][0]
        self.assertEqual((customer['name'], customer['email'], customer['phone']), (self.lead.student_name, self.lead.parent_email, self.lead.phone_key))
        self.assertIn(self.lead.parent_name, customer['description'])
        self.assertEqual(customer['invoice_settings']['custom_fields'][0], {'name': 'Student ref', 'value': account.reference})
        self.assertEqual(params['customer'], payment.stripe_customer_id)
        self.assertEqual(params['allowed_payment_method_types'], ['card'])
        self.assertEqual(params['wallet_options'], {'link': {'display': 'never'}})  # Card only: Link stays hidden.
        for field in ('customer_update', 'customer_email', 'customer_creation', 'phone_number_collection', 'name_collection',
                      'billing_address_collection', 'shipping_address_collection', 'tax_id_collection', 'custom_fields'):
            self.assertNotIn(field, params)
        self.assertEqual(params['line_items'][0]['price_data']['product'], 'eduport_plus_tuition')
        self.assertNotIn('product_data', params['line_items'][0]['price_data'])
        self.assertIn(self.lead.student_name, params['custom_text']['submit']['message'])
        self.assertIn(account.reference, params['payment_intent_data']['description'])
        for meta in (params['metadata'], params['payment_intent_data']['metadata']):
            self.assertEqual((meta['eduport_account_id'], meta['sale_id']), (str(account.pk), str(payment.sale_id)))
        self.assertEqual(Payment.objects.get().status, 'PENDING')  # Only the signed webhook changes it.

    def test_payer_entered_details_are_evidence_only(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        gateway.v1.payment_intents.retrieve.return_value = {'id': f'pi_{payment.pk.hex}', 'latest_charge': {
            'id': 'ch_paid', 'billing_details': {'name': 'Uncle Paying'},
            'payment_method_details': {'card': {'brand': 'visa', 'last4': '4242', 'country': 'AE'}}}}
        response = self.paid(payment, gateway, customer_details={'name': 'Someone Else', 'email': 'other@payer.test'})
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.stripe_charge_id, 'ch_paid')
        self.assertEqual(payment.payer_details, {'name': 'Someone Else', 'email': 'other@payer.test', 'cardholder_name': 'Uncle Paying',
                                                 'card_brand': 'visa', 'card_last4': '4242', 'card_country': 'AE'})
        account = StudentAccount.objects.get()
        self.assertEqual((account.student_name, Student.objects.get().full_name), (self.lead.student_name, self.lead.student_name))
        self.assertEqual(account.billing_link().guardian.email, self.lead.parent_email)

    # --- Identity protection and corrections ---------------------------------

    def test_identity_is_locked_by_the_first_link_and_corrected_only_with_a_reason(self):
        self.start()
        account = StudentAccount.objects.get()
        self.client.force_authenticate(self.admin)
        # Before money: an enquiry correction still names the child.
        self.assertEqual(self.client.patch(f'/api/leads/{self.lead.pk}/', {'student_name': 'Phase Student One'}, format='json').status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.student_name, 'Phase Student One')
        self.client.force_authenticate(self.bde)
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        account.refresh_from_db()
        self.assertIsNotNone(account.identity_locked_at)
        self.client.force_authenticate(self.admin)
        locked = self.client.patch(f'/api/leads/{self.lead.pk}/', {'student_name': 'Another Child'}, format='json')
        self.assertEqual((locked.status_code, locked.json()['error']), (409, 'IDENTITY_LOCKED'))
        self.assertEqual(self.paid(payment, gateway).status_code, 200)
        student = Student.objects.get()
        edit = self.client.put('/api/students/', {'id': str(student.pk), 'full_name': 'Another Child'}, format='json')
        self.assertEqual((edit.status_code, edit.json()['error']), (409, 'IDENTITY_LOCKED'))
        url = f'/api/sales/accounts/{account.pk}/identity-correction/'
        self.client.force_authenticate(self.bde)
        self.assertEqual(self.client.post(url, {'student_name': 'Phase Student 1', 'reason': 'Spelling fixed by parent.'}, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(url, {'student_name': 'Phase Student 1', 'reason': 'typo'}, format='json').json()['error'], 'REASON_REQUIRED')
        fixed = self.client.post(url, {'student_name': 'Phase Student 1', 'reason': 'Spelling confirmed by the parent on a call.'}, format='json')
        self.assertEqual(fixed.status_code, 200, fixed.content)
        account.refresh_from_db(); student.refresh_from_db(); self.lead.refresh_from_db()
        self.assertEqual({account.student_name, student.full_name, self.lead.student_name}, {'Phase Student 1'})
        correction = StudentIdentityCorrection.objects.get()
        self.assertEqual(correction.changes['student_name'], {'old': 'Phase Student One', 'new': 'Phase Student 1'})
        self.assertEqual(account.reference, fixed.json()['reference'])
        with self.assertRaises(DatabaseError), transaction.atomic():
            StudentIdentityCorrection.objects.filter(pk=correction.pk).update(reason='rewritten')
        with self.assertRaises(DatabaseError), transaction.atomic():
            StudentAccount.objects.filter(pk=account.pk).update(student=None)

    # --- Webhooks ----------------------------------------------------------

    def test_signature_is_required_and_verified(self):
        raw = json.dumps({'id': 'evt_x', 'type': 'checkout.session.completed', 'data': {'object': {}}}).encode()
        missing = APIClient().post('/api/sales/webhooks/stripe/', raw, content_type='application/json')
        self.assertEqual((missing.status_code, missing.json()['error']), (400, 'INVALID_SIGNATURE'))
        self.assertEqual(self.webhook({'id': 'evt_x', 'type': 'charge.updated', 'livemode': False, 'data': {'object': {}}}, valid=False).status_code, 400)
        self.assertFalse(StripeEvent.objects.exists())

    def test_wrong_sale_account_amount_or_currency_never_credits_and_is_queued(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        other = account_for(self.new_lead())
        bad_meta = self.event(payment)['data']['object']['metadata']
        for overrides in [{'metadata': {**bad_meta, 'sale_id': str(uuid.uuid4())}},
                          {'metadata': {**bad_meta, 'eduport_account_id': str(other.pk)}},
                          {'amount_total': 29900}, {'currency': 'usd'}]:
            with self.subTest(overrides=list(overrides)):
                self.assertEqual(self.paid(payment, gateway, **overrides).status_code, 400)
        payment.refresh_from_db()
        self.assertEqual((payment.status, Student.objects.count()), ('PENDING', 0))
        self.assertEqual(StripeReviewItem.objects.filter(kind='INCONSISTENT').count(), 1)  # One item per Session.

    def test_out_of_order_and_duplicate_events_converge(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        completed = self.event(payment)
        self.assertEqual(self.paid(payment, gateway).status_code, 200)
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(completed).status_code, 200)
            self.assertEqual(self.webhook(self.event(payment, event_type='checkout.session.expired')).status_code, 200)
        payment.refresh_from_db()
        self.assertEqual((payment.status, Payment.objects.count(), Student.objects.get().total_class_quota), ('SUCCEEDED', 1, D(6)))

    def test_unmatched_and_payment_link_activity_is_queued_never_credited(self):
        def event(event_type, obj):
            return {'id': f'evt_{uuid.uuid4().hex}', 'type': event_type, 'livemode': False, 'data': {'object': obj}}
        gateway, _, _ = self.transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event('checkout.session.completed', {
                'id': 'cs_plink', 'object': 'checkout.session', 'payment_link': 'plink_manual', 'customer': 'cus_parent',
                'amount_total': 50000, 'currency': 'aed', 'payment_status': 'paid', 'metadata': {}})).status_code, 200)
            self.assertEqual(self.webhook(event('checkout.session.completed', {
                'id': 'cs_other', 'object': 'checkout.session', 'amount_total': 1000, 'currency': 'aed', 'metadata': {}})).status_code, 200)
            self.assertEqual(self.webhook(event('payment_link.created', {'id': 'plink_new', 'object': 'payment_link'})).status_code, 200)
            # A Billing product event carries autopay metadata but is not a payment event.
            product = self.webhook(event('product.created', {'id': 'eduport_plus_tuition', 'object': 'product', 'metadata': {'autopay_id': str(uuid.uuid4())}}))
            self.assertEqual((product.status_code, product.json()['outcome']), (200, 'IGNORED'))
        kinds = dict(StripeReviewItem.objects.values_list('object_id', 'kind'))
        self.assertEqual(kinds, {'cs_plink': 'PAYMENT_LINK_PAYMENT', 'cs_other': 'UNMATCHED_CHECKOUT', 'plink_new': 'PAYMENT_LINK_CREATED'})
        self.assertEqual(StripeReviewItem.objects.get(object_id='cs_plink').amount, D('500.00'))
        self.assertFalse(Payment.objects.exists())

    def test_failed_attempt_details_and_charge_are_recorded_without_changing_status(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        def intent(event_type, **fields):
            return {'id': f'evt_{uuid.uuid4().hex}', 'type': event_type, 'livemode': False, 'data': {'object': {
                'id': f'pi_{payment.pk.hex}', 'object': 'payment_intent', 'customer': payment.stripe_customer_id,
                'metadata': {'payment_id': str(payment.pk)}, **fields}}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.webhook(intent('payment_intent.payment_failed', last_payment_error={'code': 'card_declined', 'decline_code': 'insufficient_funds', 'message': 'Your card has insufficient funds.'}))
            payment.refresh_from_db()
            self.assertEqual((payment.status, payment.failure_code, payment.failure_message), ('PENDING', 'insufficient_funds', 'Your card has insufficient funds.'))
            self.webhook(intent('payment_intent.succeeded', latest_charge='ch_late'))
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.stripe_charge_id), ('PENDING', 'ch_late'))

    # --- Refunds and disputes ------------------------------------------------

    def test_refunds_and_disputes_are_tracked_once_without_touching_classes(self):
        self.start()
        gateway, _, _ = self.transport()
        payment = self.link_for(self.lead, gateway)
        self.assertEqual(self.paid(payment, gateway).status_code, 200)
        payment.refresh_from_db()
        refund = {'id': 're_1', 'object': 'refund', 'amount': 10050, 'currency': 'aed', 'charge': 'ch_1',
                  'payment_intent': payment.stripe_payment_intent, 'status': 'pending', 'reason': 'requested_by_customer', 'created': 1700000000}
        gateway.v1.refunds.list.return_value = page([refund])
        def event(event_type, obj):
            return {'id': f'evt_{uuid.uuid4().hex}', 'type': event_type, 'livemode': False, 'data': {'object': obj}}
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.assertEqual(self.webhook(event('charge.refunded', {'id': 'ch_1', 'object': 'charge'})).status_code, 200)
            gateway.v1.refunds.list.return_value = page([{**refund, 'status': 'succeeded'}])
            self.assertEqual(self.webhook(event('refund.updated', {**refund, 'status': 'succeeded'})).status_code, 200)
            gateway.v1.disputes.retrieve.return_value = {'id': 'dp_1', 'object': 'dispute', 'amount': 30000, 'currency': 'aed', 'charge': 'ch_1',
                                                         'payment_intent': payment.stripe_payment_intent, 'status': 'needs_response',
                                                         'reason': 'fraudulent', 'created': 1700000100, 'evidence_details': {'due_by': 1700500000}}
            self.webhook(event('charge.dispute.created', {'id': 'dp_1', 'object': 'dispute'}))
            gateway.v1.disputes.retrieve.return_value = {**gateway.v1.disputes.retrieve.return_value, 'status': 'won'}
            self.webhook(event('charge.dispute.closed', {'id': 'dp_1', 'object': 'dispute'}))
            gateway.v1.refunds.list.return_value = page([{**refund, 'id': 're_unknown', 'payment_intent': 'pi_elsewhere', 'charge': 'ch_elsewhere'}])
            self.webhook(event('charge.refunded', {'id': 'ch_elsewhere', 'object': 'charge'}))
        saved = Refund.objects.get()
        self.assertEqual((saved.amount, saved.status, saved.payment_id, saved.classes_effect), (D('100.50'), 'succeeded', payment.pk, 'NONE'))
        dispute = Dispute.objects.get()
        self.assertEqual((dispute.status, dispute.amount), ('won', D('300.00')))
        self.assertIsNotNone(dispute.closed_at)
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.amount, Student.objects.get().total_class_quota), ('SUCCEEDED', D(300), D(6)))
        self.assertEqual(StripeReviewItem.objects.get().kind, 'UNMATCHED_REFUND')
        totals = self.client.get(self.url()).json()['totals']
        self.assertEqual((totals['refunded_amount'], totals['net_collected'], totals['outstanding_amount']), ('100.5', '199.5', '200'))

    # --- Review queue --------------------------------------------------------

    def test_only_administrators_resolve_review_items_once(self):
        from .ledger_models import ReviewKind
        from . import review
        item = review.record(ReviewKind.UNMATCHED_CHECKOUT, {'id': 'cs_manual', 'object': 'checkout.session', 'amount_total': 100, 'currency': 'aed'})
        self.start()
        account = StudentAccount.objects.get()
        url = f'/api/sales/stripe-review/{item.pk}/resolve/'
        self.assertEqual(self.client.get('/api/sales/stripe-review/').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.client.get('/api/sales/stripe-review/?status=OPEN').json()['items']), 1)
        linked = self.client.post(url, {'action': 'LINK', 'account_reference': account.reference, 'note': 'Parent paid via an old link.'}, format='json')
        self.assertEqual((linked.status_code, linked.json()['status'], linked.json()['account']['reference']), (200, 'LINKED', account.reference))
        self.assertEqual(self.client.post(url, {'action': 'DISMISS', 'note': 'Again'}, format='json').status_code, 409)
        self.assertFalse(Payment.objects.exists())


@override_settings(STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_LIVE_MODE=False)
class CustomerConcurrencyTests(TransactionTestCase):
    def test_simultaneous_preparations_create_one_customer_row(self):
        owner = user_account('concurrency_bde', 'BDE')
        lead = lead_of(owner, 'Concurrent Child', '506000001')
        account = account_for(lead, email='concurrent@family.test')
        barrier = Barrier(2)

        def prepare():
            close_old_connections()
            try:
                with transaction.atomic():
                    barrier.wait(timeout=15)
                    return customers.prepared_mapping(StudentAccount.objects.get(pk=account.pk)).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: prepare(), range(2)))
        self.assertEqual(len(set(rows)), 1)
        self.assertEqual(StripeCustomer.objects.filter(account=account).count(), 1)

    def test_customer_creation_is_never_duplicated_for_one_account(self):
        owner = user_account('creation_bde', 'BDE')
        account = account_for(lead_of(owner, 'Single Customer', '506000002'), email='single@family.test')
        with transaction.atomic():
            customers.prepared_mapping(account)
        gateway = stripe_catalogue(mock.MagicMock())
        gateway.v1.customers.create.side_effect = lambda params, options: {'id': 'cus_only', 'livemode': False, **params}
        first = customers.customer_for(account.pk, gateway, False)
        second = customers.customer_for(account.pk, gateway, False)
        self.assertEqual((first, second, gateway.v1.customers.create.call_count), ('cus_only', 'cus_only', 1))
        options = gateway.v1.customers.create.call_args.kwargs['options']
        self.assertEqual(options['idempotency_key'], f'eduport-customer-{StripeCustomer.objects.get().pk}')
