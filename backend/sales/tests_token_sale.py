"""
Token Sale through the API the Hub uses. Chosen with its tuition plan in Plan Choosing
(sales.token_sales): AED 100 first, then the remaining tuition in one payment by its balance
deadline, never the single-payment discount. Reservations made before -- from Sales & Payment,
without a quote or a deadline -- keep working through their own path.
"""
import uuid
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal as D
from unittest import mock

from django.db import DatabaseError, transaction
from django.template.loader import render_to_string
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from bookings.models import Lead
from bookings.scheduling import BOOKING_TIMEZONE
from communications import followups
from students.models import Student
from . import quotes, services
from . import tests_payments as payment_helpers
from .account_models import StudentGuardian
from .enrollment import next_number
from .models import Quote
from .payment_models import Payment, Purchase, Sale
from .pdf import TEMPLATE, pdf_context
from .tests_quotes import QuoteTestCase, lead_of


@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='],
    STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class TokenSaleWorkflowTests(QuoteTestCase, APITestCase):
    setUp = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    url = payment_helpers.InitialPaymentTests.url
    start = payment_helpers.InitialPaymentTests.start
    token_sale = payment_helpers.InitialPaymentTests.token_sale
    reserve_token = payment_helpers.InitialPaymentTests.reserve_token
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

    def reminders(self, now=None, user=None):
        """The enquiry's token reminder in ``user``'s follow-ups (the BDE's by default), as at ``now``."""
        items = followups.open_items(user or self.bde, now or timezone.now(), enquiry=self.lead.pk)
        return [item for item in items if item.type == followups.FollowUpType.TOKEN_TUITION]

    def legacy_reservation(self, quote=None, **dates):
        """A Token Sale reserved before Plan Choosing chose them: from Sales & Payment, with no balance deadline."""
        return Sale.objects.create(account=payment_helpers.account_for(self.lead), enquiry=self.lead, original_bde=self.bde,
            created_by=self.bde, original_quote=quote, kind='TOKEN', reservation_reference=f'TOK{next_number("TOKEN"):06d}',
            **{'expected_start_date': timezone.localdate() + timedelta(days=10), **dates})

    def overdue_reservation(self):
        """A reservation made days ago whose balance deadline has passed (the API takes only today or later)."""
        latest = quotes.latest_quote(self.lead)
        quote = quotes.create_quote(self.bde, {'syllabus': self.bridge.pk, 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'lead': self.lead.pk,
                                               'replaces': latest.pk if latest else None, 'collection_mode': 'TOKEN'}, reserving=True)
        today = timezone.localdate()
        return self.legacy_reservation(quote, expected_start_date=today - timedelta(days=1), balance_due_date=today - timedelta(days=2))

    def test_token_sale_is_quoted_and_reserved_together_without_the_single_payment_discount(self):
        # A 5% single-payment privilege: AED 475 paid at once, AED 500 as a Token Sale.
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(60), 'offer_fee': D(50),
            'single_payment_percent': D(5), 'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': ''})
        previous = quotes.latest_quote(self.lead)
        today = timezone.localdate()
        response = self.reserve_token(expected_start_date=(today + timedelta(days=12)).isoformat(),
                                      balance_due_date=(today + timedelta(days=9)).isoformat())
        self.assertEqual(response.status_code, 201, response.content)
        quote = Quote.objects.get(pk=response.json()['quote']['id'])
        self.assertEqual((quote.collection_mode, quote.supersedes_id, quote.single_payment_saving, quote.collection_amount, quote.created_by),
                         ('TOKEN', previous.pk, D(0), D(500), self.bde))
        self.assertTrue(quote.collection_intention_confirmed)
        self.assertTrue(all(line.single_payment_price is None for line in quote.lines.all()))
        self.assertEqual((response.json()['quote']['collection_mode'], response.json()['quote']['collection_discount']), ('TOKEN', '0'))
        sale = Sale.objects.get(enquiry=self.lead)
        self.assertEqual((sale.kind, sale.original_quote_id, sale.original_bde, sale.expected_start_date, sale.balance_due_date),
                         ('TOKEN', quote.pk, self.bde, today + timedelta(days=12), today + timedelta(days=9)))
        self.assertRegex(sale.reservation_reference, r'^TOK\d{6}$')
        # The enquiry's own parent details are the billing contact: nothing more was asked.
        contact = StudentGuardian.objects.get(account=sale.account, is_billing_contact=True).guardian
        self.assertEqual((contact.full_name, contact.email, contact.phone), (self.lead.parent_name, self.lead.parent_email, self.lead.phone_key))
        state = response.json()['state']
        self.assertEqual((state['sale']['balance_due_date'], state['sale']['deadline_status'], state['sale']['token_status']),
                         ((today + timedelta(days=9)).isoformat(), 'UPCOMING', 'AWAITING_PAYMENT'))
        self.assertEqual((state['totals']['package_amount'], state['totals']['outstanding_amount'], state['can_collect']), ('500', '500', True))
        self.assertEqual((Payment.objects.count(), Purchase.objects.count(), Student.objects.count()), (0, 0, 0))
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.plan_changes_locked_at)
        logged = ActivityLog.objects.get(action='sale.create', entity_id=str(sale.pk)).context
        self.assertEqual((logged['kind'], logged['quote'], logged['balance_due_date']), ('TOKEN', str(quote.pk), sale.balance_due_date.isoformat()))
        self.assertTrue(ActivityLog.objects.filter(action='quote.create', entity_id=str(quote.pk)).exists())

    def test_token_sale_quote_pdf_says_token_sale(self):
        quote = Quote.objects.get(pk=self.reserve_token().json()['quote']['id'])
        content, rates, cards, selected, reference = quotes.quote_pdf_parts(quote)
        html = render_to_string(TEMPLATE, pdf_context(content, rates, cards=cards, selected=selected, quote=reference))
        self.assertIn('<p class="quote-ref">Token Sale</p>', html)
        self.assertNotIn('Single / Complete Payment', html)

    def test_token_sale_needs_both_dates_and_a_package_beyond_the_token(self):
        today = timezone.localdate()
        quoted = Quote.objects.count()
        for response, refusal in [
            (self.token_sale(expected_start_date=(today + timedelta(days=10)).isoformat()), (400, 'BALANCE_DUE_DATE_REQUIRED')),
            (self.reserve_token(balance_due_date=(today - timedelta(days=1)).isoformat()), (400, 'BALANCE_DUE_DATE_REQUIRED')),
            (self.token_sale(balance_due_date=(today + timedelta(days=3)).isoformat()), (400, 'START_DATE_REQUIRED')),
            (self.reserve_token(expected_start_date=(today - timedelta(days=1)).isoformat()), (400, 'START_DATE_REQUIRED')),
            # One Bridge Course day: AED 50, no balance beyond the AED 100 token.
            (self.reserve_token(chapter_ids=[str(self.days[0])]), (409, 'TOKEN_EXCEEDS_PACKAGE')),
            # A stale page: the plan changed meanwhile.
            (self.reserve_token(replaces=None), (409, 'PLAN_CHANGED')),
        ]:
            self.assertEqual((response.status_code, response.json()['error']), refusal)
        self.assertEqual((Quote.objects.count(), Sale.objects.count(), Payment.objects.count()), (quoted, 0, 0))
        self.assertEqual(self.reserve_token(expected_start_date=today.isoformat(), balance_due_date=today.isoformat()).status_code, 201)

    def test_token_sale_is_the_enquiry_owner_s_or_an_administrator_s(self):
        from .tests_lifecycle import account
        other = APIClient(); other.force_authenticate(self.other_bde)
        body = {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE', 'replaces': str(quotes.latest_quote(self.lead).pk),
                'expected_start_date': timezone.localdate().isoformat(), 'balance_due_date': timezone.localdate().isoformat()}
        url = f'/api/sales/enquiries/{self.lead.pk}/token-sale/'
        self.assertEqual(other.post(url, body, format='json').status_code, 404)
        for role in ['MENTOR', 'TUTOR']:
            staff = APIClient(); staff.force_authenticate(account(f'token-{role.lower()}', role))
            self.assertEqual(staff.post(url, body, format='json').status_code, 403)
        self.assertFalse(Sale.objects.exists())
        admin = APIClient(); admin.force_authenticate(self.admin)
        response = admin.post(url, body, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get()
        self.assertEqual((sale.original_bde, sale.created_by, sale.original_quote.created_by), (self.bde, self.admin, self.admin))
        # The BDE cannot collect against the administrator's quote: their reminder says an administrator reviews it.
        [item] = self.reminders()
        self.assertEqual((item.reservation['admin_review'], item.reservation['admin_review_reason']), (True, 'PLAN_OWNER'))
        self.assertEqual(self.client.get(self.url()).json()['error'], 'PLAN_OWNER_CHANGED')
        # Cancelled, the administrator's quote still blocks the BDE's Sales & Payment: still flagged.
        quotes.cancel_quote(self.admin, sale.original_quote_id, 'Chosen again by the BDE.')
        self.assertEqual(self.client.get(self.url()).json()['error'], 'PLAN_OWNER_CHANGED')
        self.assertEqual(self.reminders()[0].reservation['admin_review_reason'], 'PLAN_OWNER')
        # An enquiry nobody owns has no BDE to attribute the sale to.
        self.lead = lead_of(self.bde, 'Unowned', '509448001')
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=None, owner_assigned_at=None)
        response = admin.post(f'/api/sales/enquiries/{self.lead.pk}/token-sale/', {**body, 'replaces': None}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (400, 'BDE_REQUIRED'))

    def test_a_family_already_known_is_confirmed_never_assumed(self):
        self.assertEqual(self.reserve_token().status_code, 201)
        first = Sale.objects.get(enquiry=self.lead)
        guardian = StudentGuardian.objects.get(account=first.account).guardian
        # A sibling's enquiry from the same parent phone.
        self.lead = lead_of(self.bde, 'Token Sibling', self.lead.phone_number)
        quoted = Quote.objects.count()
        refused = self.reserve_token()
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'FAMILY_CONFIRMATION_REQUIRED'))
        self.assertEqual([row['guardian_id'] for row in refused.json()['candidates']], [str(guardian.pk)])
        self.assertEqual((Quote.objects.count(), Sale.objects.count()), (quoted, 1))
        response = self.reserve_token(family={'mode': 'EXISTING_FAMILY', 'guardian_id': str(guardian.pk)}, confirm_distinct_child=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(StudentGuardian.objects.get(account=Sale.objects.get(enquiry=self.lead).account).guardian, guardian)

    def test_token_never_enrolls_and_the_balance_is_one_payment_for_every_class(self):
        self.assertEqual(self.reserve_token().status_code, 201)
        # The token comes first: no tuition is priced or collected before it is received.
        for response in [self.amount(purpose='TUITION', collection_mode='FULL', classes='10'),
                         self.collect(collection_mode='FULL', classes='10', amount='500'),
                         self.collect(method='STRIPE', collection_mode='FULL', classes='10')]:
            self.assertEqual((response.status_code, response.json()['error']), (400, 'TOKEN_UNPAID'))
        self.assertEqual((Purchase.objects.count(), Payment.objects.count(), Student.objects.count()), (0, 0, 0))
        token = self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
        self.assertEqual(token.status_code, 201, token.content)
        state = token.json()['state']
        self.assertEqual((state['sale']['token_status'], state['sale']['token_paid'], state['totals']['paid_classes'], state['totals']['available_quota']),
                         ('UPCOMING', '100', '0', '0'))
        self.assertEqual((state['totals']['package_amount'], state['totals']['paid_amount'], state['totals']['outstanding_amount']), ('500', '100', '400'))
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        again = self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
        self.assertEqual((again.status_code, again.json()['error']), (400, 'INVALID_TOKEN'))
        # Never part of the balance, never on Partial terms.
        for params, code in [({'collection_mode': 'FULL', 'classes': '6'}, 'TOKEN_FULL_BALANCE_REQUIRED'),
                             ({'collection_mode': 'FULL', 'classes': '9.5'}, 'TOKEN_FULL_BALANCE_REQUIRED'),
                             ({'collection_mode': 'PARTIAL', 'classes': '10'}, 'COLLECTION_MODE_LOCKED')]:
            with self.subTest(**params):
                response = self.amount(purpose='TUITION', **params)
                self.assertEqual((response.status_code, response.json()['error']), (409, code))
                for method in ['TRANSFER', 'STRIPE']:
                    self.assertEqual(self.collect(method=method, amount='400', **params).json()['error'], code)
        self.assertEqual(self.amount(purpose='TUITION', collection_mode='FULL', classes='10').json()['amount'], '400')
        mismatch = self.collect(collection_mode='FULL', classes='10', amount='500')
        self.assertEqual((mismatch.status_code, mismatch.json()['error']), (400, 'AMOUNT_MISMATCH'))
        self.assertEqual((Student.objects.count(), Payment.objects.count(), Purchase.objects.count()), (0, 1, 0))
        paid = self.collect(collection_mode='FULL', classes='10', amount='400')
        self.assertEqual(paid.status_code, 201, paid.content)
        student = Student.objects.get()
        self.assertEqual((student.total_class_quota, student.quota_source), (D(10), 'PAYMENTS'))
        state = paid.json()['state']
        self.assertEqual((state['totals']['paid_amount'], state['totals']['outstanding_amount'], state['totals']['fully_paid']), ('500', '0', True))
        self.assertEqual((Purchase.objects.get().collection_mode, state['sale']['token_status'], state['sale']['deadline_status']), ('FULL', 'ENROLLED', None))
        self.assertEqual([(row['purpose'], row['amount'], row['classes'], row['status']) for row in state['payments']],
                         [('TOKEN', '100', '0', 'SUCCEEDED'), ('TUITION', '400', '10', 'SUCCEEDED')])
        self.assertEqual(self.collect(collection_mode='FULL', classes='10', amount='400').json()['error'], 'ALREADY_ENROLLED')

    def test_balance_link_and_direct_receipt_keep_working_after_the_deadline(self):
        self.overdue_reservation()
        state = self.state()
        self.assertEqual((state['sale']['deadline_status'], state['sale']['token_status']), ('OVERDUE', 'AWAITING_PAYMENT'))
        [reminder] = self.reminders()
        self.assertEqual(reminder.state, followups.FollowUpState.OVERDUE)
        gateway, calls = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            self.assertEqual(self.webhook(self.event(Payment.objects.get())).status_code, 200)
            self.assertEqual(self.state()['sale']['token_status'], 'OVERDUE')
            response = self.collect(method='STRIPE', collection_mode='FULL', classes='10')
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(calls[-1]['line_items'][0]['price_data']['unit_amount'], 40000)
            # A link sent is not the balance received: the reminder stays, overdue, and nothing enrolls -- nor once it expires.
            link = Payment.objects.get(pk=response.json()['payment']['id'])
            self.assertEqual((self.reminders()[0].state, Student.objects.count()), (followups.FollowUpState.OVERDUE, 0))
            self.assertEqual(self.client.post(f'/api/sales/payments/{link.pk}/expire/').status_code, 200)
            self.assertEqual((len(self.reminders()), Student.objects.count()), (1, 0))
            response = self.collect(method='STRIPE', collection_mode='FULL', classes='10')
            self.assertEqual(response.status_code, 201, response.content)
            event = self.event(Payment.objects.get(pk=response.json()['payment']['id']))
            for _ in range(2):
                self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual((Student.objects.count(), Student.objects.get().total_class_quota), (1, D(10)))
        self.assertEqual(Payment.objects.filter(status='SUCCEEDED').count(), 2)
        self.assertEqual(self.reminders(), [])
        # And by direct receipt, recorded after the deadline.
        self.lead = self.new_lead()
        self.overdue_reservation()
        self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
        response = self.collect(collection_mode='FULL', classes='10', amount='400')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Student.objects.get(sales__enquiry=self.lead).total_class_quota, D(10))

    def test_follow_up_runs_from_reservation_until_the_full_balance_is_verified(self):
        deadline = timezone.localdate() + timedelta(days=7)
        self.reserve_token(balance_due_date=deadline.isoformat())
        reference = Sale.objects.get().reservation_reference
        [item] = self.reminders()
        self.assertEqual((item.state, item.due_at), (followups.FollowUpState.PENDING,
                         datetime.combine(deadline - timedelta(days=3), time(hour=9), tzinfo=BOOKING_TIMEZONE)))
        self.assertEqual({key: item.reservation[key] for key in ('reference', 'balance_due_date', 'token_status', 'token_paid', 'payment_status',
                                                                  'remaining_amount', 'admin_review', 'admin_review_reason')},
                         {'reference': reference, 'balance_due_date': deadline.isoformat(), 'token_status': 'AWAITING_PAYMENT', 'token_paid': False,
                          'payment_status': None, 'remaining_amount': '500', 'admin_review': False, 'admin_review_reason': None})
        gateway, _ = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            self.assertEqual(self.reminders()[0].reservation['payment_status'], 'PENDING')
            self.webhook(self.event(Payment.objects.get()))
        [item] = self.reminders()
        self.assertEqual((item.reservation['payment_status'], item.reservation['token_paid'], item.reservation['remaining_amount']), ('SUCCEEDED', True, '400'))
        # Due three days before the deadline, overdue after it -- and still listed, however late.
        def at(day):
            return datetime.combine(day, time(hour=10), tzinfo=BOOKING_TIMEZONE)
        self.assertEqual(self.reminders(at(deadline - timedelta(days=1)))[0].state, followups.FollowUpState.DUE_TODAY)
        for late in (1, 30):
            [item] = self.reminders(at(deadline + timedelta(days=late)))
            self.assertEqual(item.state, followups.FollowUpState.OVERDUE)
        rows = [row for row in self.client.get(f'/api/bde/follow-ups/?enquiry={self.lead.pk}').json()['results'] if row['type'] == 'TOKEN_TUITION']
        self.assertEqual([(row['reservation']['reference'], row['reservation']['balance_due_date']) for row in rows], [(reference, deadline.isoformat())])
        # Only the full balance, verified, clears it.
        self.assertEqual(self.collect(collection_mode='FULL', classes='10', amount='400').status_code, 201)
        self.assertEqual(self.reminders(at(deadline + timedelta(days=30))), [])

    def test_a_reassigned_reservation_stays_with_its_current_bde_for_admin_review(self):
        self.reserve_token()
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.other_bde)
        self.assertEqual(self.reminders(user=self.bde), [])
        [item] = self.reminders(user=self.other_bde)
        self.assertEqual((item.reservation['admin_review'], item.reservation['admin_review_reason']), (True, 'REASSIGNED'))
        # The current BDE cannot collect against the earlier owner's quote: an administrator reviews it.
        other = APIClient(); other.force_authenticate(self.other_bde)
        response = other.get(self.url())
        self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_OWNER_CHANGED'))
        admin = APIClient(); admin.force_authenticate(self.admin)
        self.assertEqual(admin.get(self.url()).status_code, 200)

    def test_choosing_the_plan_again_keeps_the_reservation_and_credits_the_token_once(self):
        today = timezone.localdate()
        self.reserve_token()
        sale = Sale.objects.get(enquiry=self.lead)
        first = sale.original_quote
        self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
        # Its dates are the reservation's: only the plan is chosen again.
        fixed = self.token_sale(chapter_ids=[str(day) for day in self.days[:4]], balance_due_date=(today + timedelta(days=20)).isoformat())
        self.assertEqual((fixed.status_code, fixed.json()['error']), (409, 'RESERVATION_DATES_FIXED'))
        # Four Bridge Course days: five classes, AED 250.
        replanned = self.token_sale(chapter_ids=[str(day) for day in self.days[:4]])
        self.assertEqual(replanned.status_code, 201, replanned.content)
        quote = Quote.objects.get(pk=replanned.json()['quote']['id'])
        self.assertEqual((quote.collection_mode, quote.supersedes_id, quote.collection_amount, quote.classes), ('TOKEN', first.pk, D(250), D(5)))
        sale.refresh_from_db()
        self.assertEqual((Sale.objects.count(), sale.original_quote_id, sale.balance_due_date), (1, first.pk, today + timedelta(days=7)))
        state = replanned.json()['state']
        self.assertEqual((state['quote']['id'], state['totals']['package_amount'], state['totals']['paid_amount'], state['totals']['outstanding_amount']),
                         (str(quote.pk), '250', '100', '150'))
        # The sale stays a Token Sale: no New Sale quote, no New Sale.
        response = self.client.post('/api/sales/quotes/', {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
            'lead': str(self.lead.pk), 'replaces': str(quote.pk), 'collection_mode': 'FULL'}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_SALE_QUOTE_REQUIRED'))
        response = self.start()
        self.assertEqual((response.status_code, response.json()['error']), (409, 'SALE_EXISTS'))
        # The token is credited once, against the plan now chosen.
        paid = self.collect(collection_mode='FULL', classes='5', amount='150')
        self.assertEqual(paid.status_code, 201, paid.content)
        self.assertEqual((Student.objects.get().total_class_quota, paid.json()['state']['totals']['paid_amount']), (D(5), '250'))
        self.assertEqual(Purchase.objects.get().quote_id, quote.pk)
        locked = self.token_sale(chapter_ids=[str(day) for day in self.days[:3]])
        self.assertEqual(locked.json()['error'], 'PLAN_LOCKED')

    def quote(self, collection_mode, **extra):
        """The Full Bridge Course quoted from Plan Choosing as a New Sale quote."""
        return self.client.post('/api/sales/quotes/', {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                                'collection_mode': collection_mode, 'lead': str(self.lead.pk), **extra}, format='json')

    def test_new_sale_keeps_autopay_quotes(self):
        self.lead = self.unquoted_lead()
        created = self.quote('AUTOPAY')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(self.start().status_code, 201)
        self.assertEqual(self.state()['quote']['collection_mode'], 'AUTOPAY')
        # Once the New Sale has started, its plan can still be replaced with any intention: the guards are the Token Sale's only.
        for mode in ['AUTOPAY', 'FULL', 'PARTIAL', 'AUTOPAY']:
            replaced = self.quote(mode, replaces=self.state()['quote']['id'])
            self.assertEqual(replaced.status_code, 201, replaced.content)
            self.assertEqual((self.state()['quote']['id'], self.state()['quote']['collection_mode']), (replaced.json()['id'], mode))

    def test_the_sale_type_is_fixed_once_a_new_sale_starts(self):
        self.assertEqual(self.start().status_code, 201)
        quoted = Quote.objects.count()
        refused = self.reserve_token()
        self.assertEqual((refused.status_code, refused.json()['error']), (409, 'SALE_EXISTS'))
        self.assertEqual((Quote.objects.count(), Sale.objects.get().kind), (quoted, 'NEW'))

    def test_token_sale_replaces_a_quote_of_any_intention_before_a_sale_starts(self):
        for mode in ['AUTOPAY', 'FULL']:
            with self.subTest(mode=mode):
                self.lead = self.new_lead(collection_mode=mode)
                previous = quotes.latest_quote(self.lead)
                response = self.reserve_token()
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual((response.json()['quote']['collection_mode'], response.json()['quote']['supersedes']), ('TOKEN', str(previous.pk)))
                self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
                # No AutoPay for a Token Sale.
                preview = self.client.post(self.url('autopay/preview/'), {'quote_id': response.json()['quote']['id'], 'initial_classes': '2',
                    'installments': [{'classes': '8', 'due_at': (timezone.now() + timedelta(days=2)).isoformat()}]}, format='json')
                self.assertEqual(preview.json()['error'], 'NEW_SALE_REQUIRED')

    def test_an_existing_reservation_without_a_quote_keeps_its_path(self):
        self.lead = self.unquoted_lead()
        sale = self.legacy_reservation()
        state = self.state()
        self.assertIsNone(state['quote'])
        self.assertEqual((state['sale']['token_status'], state['sale']['balance_due_date'], state['sale']['deadline_status'], state['can_collect']),
                         ('AWAITING_PAYMENT', None, 'UPCOMING', True))
        self.assertEqual((state['totals']['package_amount'], state['totals']['outstanding_amount']), (None, None))
        # Its reminder from the start, dated by its expected start: it has no balance deadline.
        [item] = self.reminders()
        self.assertEqual(item.due_at, datetime.combine(sale.expected_start_date - timedelta(days=3), time(hour=9), tzinfo=BOOKING_TIMEZONE))
        self.assertEqual((item.reservation['balance_due_date'], item.reservation['remaining_amount']), (None, None))
        gateway, calls = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.collect(method='STRIPE', purpose='TOKEN', classes='0', collection_mode='FULL', amount='100')
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(calls[0]['line_items'][0]['price_data']['unit_amount'], 10000)
            self.assertEqual(self.webhook(self.event(Payment.objects.get())).status_code, 200)
        paid = self.state()
        self.assertEqual((paid['sale']['token_status'], paid['totals']['paid_classes']), ('UPCOMING', '0'))
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        refused = self.amount(purpose='TUITION', collection_mode='FULL', classes='10')
        self.assertEqual((refused.status_code, refused.json()['error']), (400, 'QUOTE_REQUIRED'))
        # Its plan is chosen in Plan Choosing, as a Token Sale; the reservation's dates stay as they are.
        dated = self.token_sale(balance_due_date=(timezone.localdate() + timedelta(days=5)).isoformat())
        self.assertEqual((dated.status_code, dated.json()['error']), (409, 'RESERVATION_DATES_FIXED'))
        for mode in ['FULL', 'PARTIAL', 'AUTOPAY']:
            response = self.client.post('/api/sales/quotes/', {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                                                               'lead': str(self.lead.pk), 'collection_mode': mode}, format='json')
            self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_SALE_QUOTE_REQUIRED'))
        chosen = self.token_sale()
        self.assertEqual(chosen.status_code, 201, chosen.content)
        self.assertEqual(chosen.json()['quote']['collection_mode'], 'TOKEN')
        sale.refresh_from_db()
        self.assertEqual((sale.original_quote_id, sale.balance_due_date), (None, None))
        self.assertEqual((chosen.json()['state']['totals']['package_amount'], chosen.json()['state']['totals']['outstanding_amount']), ('500', '400'))
        partial = self.collect(collection_mode='FULL', classes='6', amount='200')
        self.assertEqual((partial.status_code, partial.json()['error']), (409, 'TOKEN_FULL_BALANCE_REQUIRED'))
        response = self.collect(collection_mode='FULL', classes='10', amount='400')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Student.objects.get().total_class_quota, D(10))
        self.assertEqual(self.reminders(), [])

    def test_an_existing_reservation_with_its_quote_collects_the_balance_in_one_payment(self):
        self.lead = self.new_lead(collection_mode='FULL')
        original = Quote.objects.get(lead=self.lead)
        self.legacy_reservation(original)
        self.assertEqual(self.state()['totals']['outstanding_amount'], '500')
        self.assertEqual(self.collect(purpose='TOKEN', classes='0', collection_mode='FULL', amount='100').status_code, 201)
        self.assertEqual(self.state()['totals']['outstanding_amount'], '400')
        partial = self.collect(collection_mode='FULL', classes='6', amount='240')
        self.assertEqual((partial.status_code, partial.json()['error']), (409, 'TOKEN_FULL_BALANCE_REQUIRED'))
        self.assertEqual((Student.objects.count(), Purchase.objects.count()), (0, 0))
        self.assertEqual(self.collect(collection_mode='FULL', classes='10', amount='400').status_code, 201)
        self.assertEqual(Student.objects.get().total_class_quota, D(10))
        self.assertEqual((Purchase.objects.get().quote_id, Quote.objects.filter(lead=self.lead).count()), (original.pk, 1))

    def test_the_database_holds_the_token_sale_rules(self):
        self.assertEqual(self.reserve_token().status_code, 201)
        sale = Sale.objects.get(enquiry=self.lead)
        quote = quotes.latest_quote(self.lead)
        with self.assertRaisesMessage(DatabaseError, 'collected in full'), transaction.atomic():
            Purchase.objects.create(sale=sale, quote=quote, collection_mode='PARTIAL', amount=quote.collection_amount, classes=quote.classes)
        purchase = Purchase.objects.create(sale=sale, quote=quote, collection_mode='FULL', amount=quote.collection_amount, classes=quote.classes)
        # Before enrollment, a Token Sale's tuition payment covers every class of its purchase.
        with self.assertRaisesMessage(DatabaseError, 'one payment for every class'), transaction.atomic():
            Payment.objects.create(request_id=uuid.uuid4(), sale=sale, purchase=purchase, purpose='TUITION', method='STRIPE',
                                   collection_mode='FULL', amount=D(240), classes=D(6), recorded_by=self.bde)
        # The deadline is fixed with the reservation, and a Token Sale's alone.
        with self.assertRaises(DatabaseError), transaction.atomic():
            Sale.objects.filter(pk=sale.pk).update(balance_due_date=sale.balance_due_date + timedelta(days=1))
        other = self.new_lead()
        with self.assertRaisesMessage(DatabaseError, 'sales_balance_due_date_token_only'), transaction.atomic():
            Sale.objects.create(account=payment_helpers.account_for(other), enquiry=other, original_bde=self.bde, created_by=self.bde,
                                kind='NEW', balance_due_date=timezone.localdate())
        self.lead = self.new_lead()
        self.assertEqual(self.start().status_code, 201)
        new_sale = Sale.objects.get(enquiry=self.lead)
        # A Token Sale quote is never a New Sale's purchase.
        snapshot = quotes.quote_snapshot(self.bde, syllabus_id=self.bridge.pk, revision=1, plan_type='BRIDGE_COURSE',
                                         lead_id=self.lead.pk, collection_mode='TOKEN')
        token_quote = quotes.issue(replace(snapshot, supersedes=quotes.latest_quote(self.lead)))
        with self.assertRaisesMessage(DatabaseError, 'on its own Token Sale only'), transaction.atomic():
            Purchase.objects.create(sale=new_sale, quote=token_quote, collection_mode='FULL', amount=token_quote.collection_amount,
                                    classes=token_quote.classes)
