"""A parent chooses collection terms before an immutable quote is issued."""
from decimal import Decimal as D

from django.db import DatabaseError, transaction
from django.template.loader import render_to_string
from django.test import override_settings
from rest_framework.test import APITestCase

from . import payments, quotes, services
from .models import Quote
from .payment_models import Payment, Purchase, Sale
from .pdf import TEMPLATE, pdf_context
from .tests_payments import InitialPaymentTests
from .tests_quotes import QuoteTestCase


@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='])
class CollectionIntentionTests(QuoteTestCase, APITestCase):
    setUp = InitialPaymentTests.setUp
    new_lead = InitialPaymentTests.new_lead
    url = InitialPaymentTests.url
    start = InitialPaymentTests.start
    payload = InitialPaymentTests.payload
    collect = InitialPaymentTests.collect

    def data(self, mode=None, **extra):
        return {'syllabus': str(self.bridge.pk), 'revision': 1, 'plan_type': 'BRIDGE_COURSE',
                'lead': str(self.lead.pk), 'replaces': str(quotes.latest_quote(self.lead).pk),
                **({'collection_mode': mode} if mode else {}), **extra}

    def priced(self):
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(300),
            'offer_fee': D('276.5'), 'single_payment_percent': D(5),
            'single_payment_plan_types': ['BRIDGE_COURSE', 'REGULAR'], 'note': ''})

    def replacement_url(self):
        return f'/api/sales/enquiries/{self.lead.pk}/installment-quote/'

    def test_intention_is_required_by_api_and_service(self):
        for mode in [None, '', 'OTHER', 'partial']:
            with self.subTest(mode=mode):
                body = self.data()
                if mode is not None:
                    body['collection_mode'] = mode
                response = self.client.post('/api/sales/quotes/', body, format='json')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn('collection_mode', response.json()['fields'])
                with self.assertRaises(services.SalesError):
                    quotes.create_quote(self.bde, body)
        self.assertEqual(Quote.objects.count(), 1)

    def test_all_three_prices_are_backend_calculated_and_snapshot_is_immutable(self):
        self.priced()
        for mode, amount, saving in [('FULL', '2627', '138'), ('PARTIAL', '2765', '0'), ('AUTOPAY', '2765', '0')]:
            with self.subTest(mode=mode):
                response = self.client.post('/api/sales/quotes/', self.data(mode,
                    payable_amount='1', collection_amount='1', single_payment_saving='2764'), format='json')
                self.assertEqual(response.status_code, 201, response.content)
                row = response.json()
                self.assertEqual((row['collection_mode'], row['collection_amount'], row['single_payment_saving']), (mode, amount, saving))
                self.assertTrue(row['collection_intention_confirmed'])
                self.assertEqual(row['total_fee'], '2765')
                quote = Quote.objects.get(pk=row['id'])
                self.assertEqual(quote.lines.get().single_payment_price, D(amount) if mode == 'FULL' else None)
                for change in [{'collection_mode': 'FULL' if mode != 'FULL' else 'PARTIAL'}, {'collection_intention_confirmed': False}]:
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        Quote.objects.filter(pk=quote.pk).update(**change)

    def test_payment_mode_is_locked_even_without_any_discount(self):
        self.start()
        self.assertEqual(self.collect(collection_mode='FULL', classes='10', amount='500').json()['error'], 'COLLECTION_MODE_LOCKED')
        self.assertEqual((Purchase.objects.count(), Payment.objects.count()), (0, 0))
        # Correct original intention needs no replacement quote.
        self.assertEqual(self.collect().status_code, 201)
        self.assertEqual(Quote.objects.count(), 1)

    def test_autopay_quote_cannot_be_collected_through_manual_or_plain_stripe_endpoint(self):
        self.lead = self.new_lead(collection_mode='AUTOPAY')
        self.start()
        for mode in ['FULL', 'PARTIAL']:
            for method in ['TRANSFER', 'STRIPE']:
                response = self.collect(collection_mode=mode, method=method, classes='10', amount='500')
                self.assertEqual((response.status_code, response.json()['error']), (409, 'COLLECTION_MODE_LOCKED'))
        self.assertEqual((Purchase.objects.count(), Payment.objects.count()), (0, 0))

    def test_explicit_replacement_supports_each_mode_using_frozen_original_pricing(self):
        self.priced()
        original = quotes.create_quote(self.bde, self.data('FULL'))
        original_data = quotes.quote_data(original)
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(500), 'offer_fee': D(400),
            'single_payment_percent': D(25), 'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': ''})
        for mode, expected in [('PARTIAL', '2765'), ('AUTOPAY', '2765'), ('FULL', '2627')]:
            old = quotes.latest_quote(self.lead)
            body = {'quote_id': str(old.pk), 'collection_mode': mode}
            preview = self.client.get(self.replacement_url(), body)
            self.assertEqual(preview.status_code, 200, preview.content)
            self.assertEqual(preview.json()['collection_amount'], expected)
            self.assertEqual(quotes.latest_quote(self.lead).pk, old.pk, 'Review must not issue a quote')
            response = self.client.post(self.replacement_url(), body, format='json')
            self.assertEqual(response.status_code, 201, response.content)
            new = Quote.objects.get(pk=response.json()['id'])
            self.assertEqual((str(new.supersedes_id), new.collection_amount, new.pricing_version_id),
                             (str(old.pk), D(expected), original.pricing_version_id))
            self.assertEqual(list(new.chapters.values_list('chapter_id', 'classes')),
                             list(original.chapters.values_list('chapter_id', 'classes')))
        after = quotes.quote_data(original)
        for dynamic in ['is_current', 'selection_status']:
            after.pop(dynamic); original_data.pop(dynamic)
        self.assertEqual(after, original_data)

    def test_replacement_requires_explicit_mode_current_quote_and_unlocked_purchase(self):
        old = quotes.latest_quote(self.lead)
        self.assertEqual(self.client.post(self.replacement_url(), {'quote_id': str(old.pk)}, format='json').status_code, 400)
        self.start()
        self.assertEqual(self.collect().status_code, 201)
        for method in [self.client.get, self.client.post]:
            response = method(self.replacement_url(), {'quote_id': str(old.pk), 'collection_mode': 'FULL'})
            self.assertEqual((response.status_code, response.json()['error']), (409, 'PLAN_LOCKED'))

    def test_quote_pdf_and_sales_summary_show_the_issued_intention(self):
        labels = {'FULL': 'Single / Complete Payment', 'PARTIAL': 'Partial Payment', 'AUTOPAY': 'Autopay'}
        for mode, label in labels.items():
            quote = quotes.create_quote(self.bde, self.data(mode))
            content, rates, cards, selected, reference = quotes.quote_pdf_parts(quote)
            html = render_to_string(TEMPLATE, pdf_context(content, rates, cards=cards, selected=selected, quote=reference))
            self.assertIn(label, html)
            state = self.client.get(self.url()).json()
            self.assertEqual(state['quote']['collection_mode'], mode)
            self.assertEqual(state['quote']['collection_amount'], '500')

    def test_database_prevents_purchase_mode_bypass(self):
        self.start()
        with self.assertRaises(DatabaseError), transaction.atomic():
            Purchase.objects.create(sale=Sale.objects.get(), quote=quotes.latest_quote(self.lead),
                collection_mode='FULL', amount=D(500), classes=D(10))

    def test_database_requires_an_agreement_for_autopay_purchase(self):
        from django.db import connection
        self.lead = self.new_lead(collection_mode='AUTOPAY')
        self.start()
        with self.assertRaises(DatabaseError), transaction.atomic():
            Purchase.objects.create(sale=Sale.objects.get(), quote=quotes.latest_quote(self.lead),
                collection_mode='PARTIAL', amount=D(500), classes=D(10))
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def test_half_class_allocation_and_whole_aed_final_settlement_for_each_intention(self):
        self.priced()
        for mode in ['FULL', 'PARTIAL', 'AUTOPAY']:
            quote = quotes.create_quote(self.bde, self.data(mode, chapter_ids=[self.days[1]]))
            paid = {'amount': D(0), 'classes': D(0)}
            if mode == 'FULL':
                due, classes = payments.allocation(quote.collection_amount, quote.classes, paid, quote.classes, 'FULL')
                self.assertEqual(due, quote.collection_amount)
            else:
                for classes in [D('0.5'), quote.classes - D('0.5')]:
                    due, classes = payments.allocation(quote.collection_amount, quote.classes, paid, classes, 'PARTIAL')
                    self.assertEqual(due, payments.whole(due))
                    paid = {'amount': paid['amount'] + due, 'classes': paid['classes'] + classes}
                self.assertEqual(paid, {'amount': quote.collection_amount, 'classes': quote.classes})

    def test_non_complete_quotes_never_discount_either_regular_revision_package(self):
        self.price(plan_types=('REGULAR', 'REVISION', 'BRIDGE_COURSE'))
        for mode in ['PARTIAL', 'AUTOPAY']:
            quote = quotes.create_quote(self.bde, {'syllabus': self.grade6.pk, 'revision': 1,
                'plan_type': 'REGULAR_REVISION', 'collection_mode': mode})
            self.assertEqual(quote.single_payment_saving, D(0))
            self.assertEqual(quote.collection_amount, quote.total_fee)
            self.assertTrue(all(line.single_payment_price is None for line in quote.lines.all()))

    def test_intention_replacement_preserves_token_positive_tuition_balance_guard(self):
        from django.utils import timezone
        # Three selected classes at AED 35 = 105. A 10% complete-payment
        # discount would leave 95, less than the reservation's AED 100 credit.
        services.create_pricing_version(self.admin, {'currency': 'AED', 'standard_fee': D(45), 'offer_fee': D(35),
            'single_payment_percent': D(10), 'single_payment_plan_types': ['BRIDGE_COURSE'], 'note': ''})
        quote = quotes.create_quote(self.bde, self.data('PARTIAL', chapter_ids=[self.days[0], self.days[3]]))
        self.assertEqual(quote.collection_amount, D(105))
        self.assertEqual(self.start('TOKEN', expected_start_date=timezone.localdate().isoformat()).status_code, 201)
        for method in [self.client.get, self.client.post]:
            response = method(self.replacement_url(), {'quote_id': str(quote.pk), 'collection_mode': 'FULL'})
            self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_EXCEEDS_PACKAGE'))
        self.assertEqual(quotes.latest_quote(self.lead).pk, quote.pk)
