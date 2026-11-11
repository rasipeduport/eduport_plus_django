"""Run only with manage.py shell against a NEW disposable quote_intention DB."""
import json
import base64
import os
import uuid
from datetime import timedelta
from decimal import Decimal as D

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

if os.environ.get('COLLECTION_INTENTION_QA_DISPOSABLE') != '1':
    raise RuntimeError('Explicit disposable database acknowledgement is required.')
if not settings.DEBUG or not settings.DATABASES['default']['NAME'].startswith('quote_intention'):
    raise RuntimeError('A dedicated disposable quote_intention database is required.')

from sales.tests_quotes import QuoteTestCase, lead_of
from sales import services, quotes
from sales.tests_collection_compatibility import historical_copy
from sales.payment_models import Sale, Purchase, Payment
from bookings.models import Lead

w = QuoteTestCase()
w.make_world()
services.create_pricing_version(w.admin, {
    'currency': 'AED', 'standard_fee': D(300), 'offer_fee': D('276.5'),
    'single_payment_percent': D(5), 'single_payment_plan_types': ['BRIDGE_COURSE', 'REGULAR'], 'note': '',
})
leads = {}
for i, name in enumerate(['complete','partial','autopay'],1):
    lead = lead_of(w.bde, 'Collection ' + name.title(), f'50912340{i:02d}')
    leads[name] = {'id': str(lead.pk)}
for i, name in enumerate(['legacy_full', 'legacy_partial', 'legacy_autopay', 'token_auto_full', 'token_auto_partial', 'historical_purchase', 'historical_token'], 10):
    lead = lead_of(w.bde, 'Collection ' + name.replace('_', ' ').title(), f'50912340{i:02d}')
    mode = 'AUTOPAY' if name.startswith('token_auto') else 'PARTIAL' if name.startswith('historical_') else 'FULL'
    quote = quotes.create_quote(w.bde, {'lead': lead.pk, 'syllabus': w.bridge.pk, 'revision': 1,
                                      'plan_type': 'BRIDGE_COURSE', 'collection_mode': mode})
    if not name.startswith('token_auto'):
        quote = historical_copy(quote)
    leads[name] = {'id': str(lead.pk), 'quote_id': str(quote.pk)}
    if name.startswith('historical_'):
        token = name == 'historical_token'
        sale = Sale.objects.create(enquiry=lead, original_bde=w.bde, created_by=w.bde, original_quote=quote,
            kind='TOKEN' if token else 'NEW', **({'expected_start_date': timezone.localdate() + timedelta(days=20),
                                                'reservation_reference': 'TOK-BROWSER-HISTORY'} if token else {}))
        if token:
            # An existing verified direct token, not a simulated Stripe charge.
            Payment.objects.create(request_id=uuid.uuid4(), sale=sale, purpose='TOKEN', method='TRANSFER',
                collection_mode='FULL', amount=D(100), classes=D(0), status='SUCCEEDED',
                received_confirmed=True, verified_at=timezone.now(), proof=ContentFile(base64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jQXsAAAAASUVORK5CYII='), name='historical-token.png'), recorded_by=w.bde)
        else:
            Purchase.objects.create(sale=sale, quote=quote, collection_mode='PARTIAL', amount=quote.collection_amount,
                                    classes=quote.classes)
            Lead.objects.filter(pk=lead.pk).update(plan_changes_locked_at=timezone.now())
print(json.dumps({
    'disposable_collection_intention_qa': True, 'leads': leads,
    'bridge_id': str(w.bridge.pk), 'bridge_title': 'Grade 7 CBSE',
    'bde_username': w.bde.username, 'admin_username': w.admin.username,
}))
