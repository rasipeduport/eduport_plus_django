"""Confirmed historical-quote and Token/Autopay compatibility decisions."""
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.db import transaction
from django.db.models import Max
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from bookings.models import Lead
from students.models import Student
from . import quotes, tests_collection_intention as intention_helpers, tests_payments as payment_helpers
from .models import Quote, QuoteChapter, QuoteLine
from .payment_models import Payment, Purchase, Sale
from .tests_quotes import QuoteTestCase, lead_of


@transaction.atomic
def historical_copy(original):
    """Insert the pre-0012 snapshot shape; never disable immutable triggers."""
    fields = {field.attname: getattr(original, field.attname) for field in Quote._meta.concrete_fields if not field.primary_key}
    fields.update(number=(Quote.objects.aggregate(n=Max('number'))['n'] or 0) + 1,
                  supersedes_id=original.pk, collection_intention_confirmed=False)
    historical = Quote.objects.create(**fields)
    for model, rows in [(QuoteLine, original.lines.all()), (QuoteChapter, original.chapters.all())]:
        model.objects.bulk_create([model(**{
            **{field.attname: getattr(row, field.attname) for field in model._meta.concrete_fields if not field.primary_key},
            'quote_id': historical.pk,
        }) for row in rows])
    return historical


@override_settings(LEARN_INVITATION_KEYS=['MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='],
    STRIPE_SECRET_KEY='sk_test_unit_only', STRIPE_WEBHOOK_SECRET='whsec_unit_only', STRIPE_LIVE_MODE=False)
class CollectionCompatibilityTests(QuoteTestCase, APITestCase):
    setUp = payment_helpers.InitialPaymentTests.setUp
    new_lead = payment_helpers.InitialPaymentTests.new_lead
    url = payment_helpers.InitialPaymentTests.url
    start = payment_helpers.InitialPaymentTests.start
    payload = payment_helpers.InitialPaymentTests.payload
    collect = payment_helpers.InitialPaymentTests.collect
    stripe_transport = payment_helpers.InitialPaymentTests.stripe_transport
    event = payment_helpers.InitialPaymentTests.event
    webhook = payment_helpers.InitialPaymentTests.webhook
    replacement_url = intention_helpers.CollectionIntentionTests.replacement_url

    def legacy(self):
        return historical_copy(quotes.latest_quote(self.lead))

    def fingerprint(self, quote):
        quote.refresh_from_db()
        return {**{field.attname: getattr(quote, field.attname) for field in Quote._meta.concrete_fields},
                'lines': list(quote.lines.order_by('position').values()),
                'chapters': list(quote.chapters.order_by('chapter__position').values())}

    def existing_sale(self, quote, kind='NEW'):
        return Sale.objects.create(enquiry=self.lead, original_bde=self.bde, created_by=self.bde, original_quote=quote,
            kind=kind, **({'expected_start_date': timezone.localdate() + timedelta(days=8),
                          'reservation_reference': 'TOK-' + uuid.uuid4().hex[:20]} if kind == 'TOKEN' else {}))

    def old_purchase(self, quote):
        sale = self.existing_sale(quote)
        purchase = Purchase.objects.create(sale=sale, quote=quote, collection_mode=quote.collection_mode,
                                          amount=quote.collection_amount, classes=quote.classes)
        Lead.objects.filter(pk=self.lead.pk).update(plan_changes_locked_at=timezone.now())
        return sale, purchase

    def test_uncollected_historical_quote_blocks_new_and_token_sales_without_assuming_full(self):
        old = self.legacy(); before = self.fingerprint(old)
        self.assertFalse(self.client.get(self.url()).json()['can_collect'])
        for kind in ['NEW', 'TOKEN']:
            response = self.start(kind, expected_start_date=timezone.localdate().isoformat())
            self.assertEqual((response.status_code, response.json()['error']), (409, 'COLLECTION_INTENTION_REQUIRED'))
        self.assertEqual((Sale.objects.count(), Purchase.objects.count(), Payment.objects.count(), Student.objects.count()), (0, 0, 0, 0))
        self.assertEqual(self.fingerprint(old), before)

    def test_each_explicit_replacement_mode_allows_new_sale_and_keeps_historical_snapshot(self):
        for mode in ['FULL', 'PARTIAL', 'AUTOPAY']:
            with self.subTest(mode=mode):
                self.lead = self.new_lead(); old = self.legacy(); before = self.fingerprint(old)
                body = {'quote_id': str(old.pk), 'collection_mode': mode}
                self.assertEqual(self.client.get(self.replacement_url(), body).status_code, 200)
                result = self.client.post(self.replacement_url(), body, format='json')
                self.assertEqual(result.status_code, 201, result.content)
                self.assertEqual((result.json()['collection_mode'], result.json()['supersedes']), (mode, str(old.pk)))
                self.assertTrue(result.json()['collection_intention_confirmed'])
                self.assertEqual(self.start().status_code, 201)
                self.assertEqual(self.fingerprint(old), before)

    def test_existing_empty_sale_cannot_bypass_historical_gate_via_any_collection_endpoint(self):
        old = self.legacy(); self.existing_sale(old)
        self.assertEqual(self.start().json()['error'], 'COLLECTION_INTENTION_REQUIRED')
        response = self.client.get(self.url('amount/'), {'purpose': 'TUITION', 'classes': '6', 'collection_mode': 'PARTIAL'})
        self.assertEqual((response.status_code, response.json()['error']), (409, 'COLLECTION_INTENTION_REQUIRED'))
        for method in ['TRANSFER', 'STRIPE']:
            self.assertEqual(self.collect(method=method).json()['error'], 'COLLECTION_INTENTION_REQUIRED')
        schedule = {'quote_id': str(old.pk), 'initial_classes': '2', 'installments': [
            {'classes': '8', 'due_at': (timezone.now() + timedelta(days=2)).isoformat()}]}
        response = self.client.post(self.url('autopay/preview/'), schedule, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'COLLECTION_INTENTION_REQUIRED'))
        self.assertEqual((Purchase.objects.count(), Payment.objects.count(), Student.objects.count()), (0, 0, 0))

    def test_existing_empty_token_reservation_requires_replacement_before_collecting_token(self):
        old = self.legacy(); sale = self.existing_sale(old, 'TOKEN')
        response = self.collect(purpose='TOKEN', collection_mode='FULL', classes='0', amount='100')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'COLLECTION_INTENTION_REQUIRED'))
        self.assertEqual(Sale.objects.get().reservation_reference, sale.reservation_reference)
        self.assertFalse(Payment.objects.exists())

    def test_existing_purchase_without_collection_retains_terms_and_can_enroll(self):
        old = self.legacy(); before = self.fingerprint(old); _, purchase = self.old_purchase(old)
        self.assertEqual(self.start().status_code, 201)
        self.assertTrue(self.client.get(self.url()).json()['can_collect'])
        result = self.collect()
        self.assertEqual(result.status_code, 201, result.content)
        self.assertEqual((Student.objects.get().total_class_quota, Purchase.objects.count()), (D(6), 1))
        purchase.refresh_from_db()
        self.assertEqual((purchase.quote_id, purchase.amount, purchase.classes), (old.pk, D(500), D(10)))
        self.assertEqual(self.fingerprint(old), before)

    def test_any_collection_status_preserves_historical_token_reservation_and_snapshot(self):
        for status in ['PENDING', 'FAILED', 'EXPIRED', 'SUCCEEDED']:
            with self.subTest(status=status):
                self.lead = self.new_lead(); old = self.legacy(); before = self.fingerprint(old)
                sale = self.existing_sale(old, 'TOKEN')
                payment = Payment.objects.create(request_id=uuid.uuid4(), sale=sale, purpose='TOKEN', method='STRIPE',
                    collection_mode='FULL', amount=D(100), classes=D(0), status=status, recorded_by=self.bde,
                    **({'verified_at': timezone.now(), 'stripe_payment_intent': 'pi_history_' + uuid.uuid4().hex} if status == 'SUCCEEDED' else {}))
                frozen = (sale.pk, sale.expected_start_date, sale.reservation_reference, sale.original_quote_id)
                self.assertTrue(self.client.get(self.url()).json()['can_collect'])
                response = self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
                self.assertEqual(response.status_code, 201, response.content)
                sale.refresh_from_db(); payment.refresh_from_db()
                self.assertEqual((sale.pk, sale.expected_start_date, sale.reservation_reference, sale.original_quote_id), frozen)
                self.assertEqual(payment.status, status)
                self.assertEqual(self.fingerprint(old), before)
        self.assertEqual(Student.objects.count(), 0)

    def test_historical_paid_token_continues_to_tuition_without_forced_replacement(self):
        old = self.legacy(); before = self.fingerprint(old); sale = self.existing_sale(old, 'TOKEN')
        token = Payment.objects.create(request_id=uuid.uuid4(), sale=sale, purpose='TOKEN', method='TRANSFER',
            collection_mode='FULL', amount=D(100), classes=D(0), status='SUCCEEDED', received_confirmed=True,
            verified_at=timezone.now(), proof=self.payload()['proof'], recorded_by=self.bde)
        response = self.collect(amount='200')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((Student.objects.get().total_class_quota, Payment.objects.count()), (D(6), 2))
        self.assertEqual(response.json()['state']['totals']['paid_amount'], '300')
        token.refresh_from_db(); self.assertEqual((token.amount, token.classes), (D(100), D(0)))
        self.assertEqual(self.fingerprint(old), before)

    def test_pending_historical_stripe_purchase_webhook_still_verifies_frozen_terms_once(self):
        old = self.legacy(); before = self.fingerprint(old); self.old_purchase(old)
        gateway, _ = self.stripe_transport()
        with mock.patch('sales.stripe_gateway.client', return_value=gateway):
            response = self.collect(method='STRIPE')
        self.assertEqual(response.status_code, 201, response.content)
        event = self.event(Payment.objects.get())
        self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual((Payment.objects.count(), Student.objects.count(), Student.objects.get().total_class_quota), (1, 1, D(6)))
        self.assertEqual(self.fingerprint(old), before)

    def test_autopay_quote_blocks_token_sale_before_reservation_or_collection_is_created(self):
        self.lead = self.new_lead(collection_mode='AUTOPAY')
        response = self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_AUTOPAY_NOT_ALLOWED'))
        self.assertEqual((Sale.objects.count(), Payment.objects.count(), Student.objects.count()), (0, 0, 0))
        self.assertEqual(self.start().status_code, 201, 'New Sale Autopay remains supported')

    def test_token_reservation_rejects_autopay_through_both_quote_replacement_paths(self):
        self.start('TOKEN', expected_start_date=timezone.localdate().isoformat())
        old = quotes.latest_quote(self.lead); before = self.fingerprint(old)
        for method in [self.client.get, self.client.post]:
            response = method(self.replacement_url(), {'quote_id': str(old.pk), 'collection_mode': 'AUTOPAY'})
            self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_AUTOPAY_NOT_ALLOWED'))
        response = self.client.post('/api/sales/quotes/', {'syllabus': str(self.bridge.pk), 'revision': 1,
            'plan_type': 'BRIDGE_COURSE', 'lead': str(self.lead.pk), 'replaces': str(old.pk), 'collection_mode': 'AUTOPAY'}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_AUTOPAY_NOT_ALLOWED'))
        self.assertEqual(self.fingerprint(old), before)
        self.assertEqual(quotes.latest_quote(self.lead).pk, old.pk)

    def test_old_token_autopay_draft_cannot_collect_until_full_or_partial_replacement(self):
        for mode in ['FULL', 'PARTIAL']:
            self.lead = self.new_lead(collection_mode='AUTOPAY'); old = quotes.latest_quote(self.lead)
            self.existing_sale(old, 'TOKEN')
            self.assertFalse(self.client.get(self.url()).json()['can_collect'])
            response = self.collect(purpose='TOKEN', collection_mode='FULL', classes='0', amount='100')
            self.assertEqual((response.status_code, response.json()['error']), (409, 'TOKEN_AUTOPAY_NOT_ALLOWED'))
            response = self.client.post(self.replacement_url(), {'quote_id': str(old.pk), 'collection_mode': mode}, format='json')
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(self.collect(purpose='TOKEN', collection_mode='FULL', classes='0', amount='100').status_code, 201)
        self.assertEqual(Student.objects.count(), 0)

    def test_token_without_quote_still_reserves_aed_100_without_enrollment(self):
        self.lead = lead_of(self.bde, 'Unquoted token', '509449992')
        self.assertEqual(self.start('TOKEN', expected_start_date=timezone.localdate().isoformat()).status_code, 201)
        response = self.collect(purpose='TOKEN', collection_mode='FULL', classes='0', amount='100')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((Payment.objects.get().amount, Student.objects.count()), (D(100), 0))

    def test_foreign_bde_cannot_read_or_replace_historical_quote(self):
        old = self.legacy(); other = APIClient(); other.force_authenticate(self.other_bde)
        self.assertEqual(other.get(self.url()).status_code, 404)
        self.assertEqual(other.post(self.url(), {'kind': 'NEW'}, format='json').status_code, 404)
        self.assertEqual(other.post(self.replacement_url(), {'quote_id': str(old.pk), 'collection_mode': 'FULL'}, format='json').status_code, 404)
