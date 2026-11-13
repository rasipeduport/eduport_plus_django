"""Frozen allocations shared by native Billing and historical PI agreements."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from . import payments, quotes
from .autopay_models import AutopayAgreement, AutopayAttempt, AutopayInstallment
from .payment_models import Payment, Purchase, Sale, StripeCustomer
from .pricing import plain

REVIEW_SALT = 'eduport-autopay-review-v1'
ACTION_SALT = 'eduport-autopay-action-v1'
DEFAULT_COLLECTION_ENGINE = 'STRIPE_BILLING'


def configured():
    prefix = 'pk_live_' if settings.STRIPE_LIVE_MODE else 'pk_test_'
    try:
        url = urlparse(settings.AUTOPAY_TERMS_URL)
    except ValueError:
        return False
    terms_ok = url.scheme == 'https' and bool(url.netloc)
    if settings.DEBUG and url.hostname in ('localhost', '127.0.0.1'):
        terms_ok = url.scheme in ('http', 'https')
    return payments.stripe_configured() and settings.STRIPE_PUBLISHABLE_KEY.startswith(prefix) and terms_ok


def billing_zone():
    try:
        return ZoneInfo(settings.SALES_BILLING_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise payments.refusal('BILLING_TIMEZONE_INVALID', 'Configure a valid billing timezone.', 503) from exc


def due_instant(value, zone):
    try:
        # A collection time must be explicitly chosen, never invented from a date.
        if 'T' not in value:
            raise ValueError()
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.tzinfo is None:
            first, second = value.replace(tzinfo=zone, fold=0), value.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise ValueError('Ambiguous or nonexistent local time; supply an explicit offset.')
            value = first
        return value.astimezone(dt_timezone.utc)
    except (TypeError, ValueError) as exc:
        raise payments.refusal('INVALID_DUE_DATE', 'Choose a valid collection date and time in the billing timezone; ambiguous times need an explicit offset.') from exc


def preview(actor, enquiry_id, data, request=None):
    lead = payments.accessible_lead(actor, enquiry_id, request)
    sale = Sale.objects.filter(enquiry=lead).first()
    if not sale or sale.kind != 'NEW':
        raise payments.refusal('NEW_SALE_REQUIRED', 'Initial Autopay is available only for New Sale.')
    if sale.student_id:
        raise payments.refusal('ALREADY_ENROLLED', 'BDE setup ends at enrollment.', 403)
    if Purchase.objects.filter(sale=sale).exists():
        raise payments.refusal('PURCHASE_LOCKED', 'Collection already pinned this purchase. Continue its existing payment agreement.', 409)
    quote = payments.current_quote(actor, lead, request)
    if str(quote.pk) != str(data['quote_id']):
        raise payments.refusal('PLAN_CHANGED', 'The quote changed. Review the current quote.', 409)
    payments.require_compatible_quote(lead, quote, sale.kind)
    amount, classes = payments.purchase_terms(quote, 'PARTIAL', intention='AUTOPAY')
    zone = billing_zone()
    paid = {'amount': Decimal(0), 'classes': Decimal(0)}
    rows = []
    initial_amount, initial_classes = payments.allocation(amount, classes, paid, data['initial_classes'], 'PARTIAL')
    if initial_classes >= classes or not data['installments']:
        raise payments.refusal('INVALID_SCHEDULE', 'Autopay needs an initial payment and at least one future installment. Use complete payment for the whole package.')
    rows.append({'position': 0, 'classes': plain(initial_classes), 'amount': plain(initial_amount), 'due_at': None})
    paid = {'amount': initial_amount, 'classes': initial_classes}
    previous = timezone.now()
    for position, item in enumerate(data['installments'], 1):
        due = due_instant(item['due_at'], zone)
        if due <= previous:
            raise payments.refusal('INVALID_DUE_DATE', 'Collection dates must be future, unique and in strictly increasing order.')
        due_amount, due_classes = payments.allocation(amount, classes, paid, item['classes'], 'PARTIAL')
        rows.append({'position': position, 'classes': plain(due_classes), 'amount': plain(due_amount), 'due_at': due.isoformat()})
        paid = {'amount': paid['amount'] + due_amount, 'classes': paid['classes'] + due_classes}
        previous = due
    if paid != {'amount': amount, 'classes': classes}:
        raise payments.refusal('INVALID_SCHEDULE', 'Initial and future installments must cover exactly the package classes and amount.')
    if DEFAULT_COLLECTION_ENGINE == 'STRIPE_BILLING':
        from .billing import phase_terms
        phase_terms(rows[1:])  # Reject unsupported native terms before taking money.
    snapshot = {'quote_id': str(quote.pk), 'billing_timezone': str(zone), 'package_amount': plain(amount),
                'classes': plain(classes), 'terms_url': settings.AUTOPAY_TERMS_URL, 'installments': rows,
                'collection_engine': DEFAULT_COLLECTION_ENGINE}
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    token = signing.dumps({'digest': digest, 'actor': str(actor.pk), 'enquiry': str(enquiry_id)}, salt=REVIEW_SALT)
    return {**snapshot, 'schedule_digest': digest, 'review_token': token, 'checkout_available': configured()}


def begin(actor, enquiry_id, data, request=None):
    with transaction.atomic(durable=True):
        agreement = _prepare_begin(actor, enquiry_id, data, request)
    from .stripe_gateway import create_checkout
    initial = agreement.installments.get(position=0)
    create_checkout(initial.payment, agreement=agreement, attempt_id=initial.attempts.order_by('-number').first().pk)
    agreement.refresh_from_db()
    return agreement


@transaction.atomic
def _prepare_begin(actor, enquiry_id, data, request=None):
    lead = payments.accessible_lead(actor, enquiry_id, request, lock=True)
    existing = AutopayAgreement.objects.filter(pk=data['request_id'], purchase__sale__enquiry=lead, created_by=actor).first()
    if existing:
        # An unchanged review token identifies the immutable schedule on transport retry.
        try:
            signed = signing.loads(data['review_token'], salt=REVIEW_SALT)
        except signing.BadSignature as exc:
            raise payments.refusal('INVALID_REVIEW', 'Review the schedule again.') from exc
        if signed.get('digest') != existing.schedule_digest or signed.get('actor') != str(actor.pk) or signed.get('enquiry') != str(lead.pk):
            raise payments.refusal('IDEMPOTENCY_CONFLICT', 'That request ID belongs to another agreement.', 409)
        frozen = list(existing.installments.all())
        same = (str(data['quote_id']) == str(existing.purchase.quote_id) and data['initial_classes'] == frozen[0].classes
                and len(data['installments']) == len(frozen) - 1)
        if same:
            for item, row in zip(data['installments'], frozen[1:]):
                same = same and item['classes'] == row.classes and due_instant(item['due_at'], ZoneInfo(existing.billing_timezone)) == row.due_at
        if not same:
            raise payments.refusal('IDEMPOTENCY_CONFLICT', 'That request ID already froze another schedule.', 409)
        return existing
    if AutopayAgreement.objects.filter(pk=data['request_id']).exists():
        raise payments.refusal('IDEMPOTENCY_CONFLICT', 'That request ID is already in use.', 409)
    snapshot = preview(actor, enquiry_id, data, request)
    try:
        signed = signing.loads(data['review_token'], salt=REVIEW_SALT, max_age=1800)
    except signing.BadSignature as exc:
        raise payments.refusal('INVALID_REVIEW', 'Review the complete schedule again before generating Checkout.') from exc
    if signed != {'digest': snapshot['schedule_digest'], 'actor': str(actor.pk), 'enquiry': str(enquiry_id)}:
        raise payments.refusal('INVALID_REVIEW', 'The reviewed schedule changed. Review it again.')
    if not configured():
        raise payments.refusal('AUTOPAY_NOT_CONFIGURED', 'Configure matching Stripe keys, webhook secret and approved Autopay terms before creating Checkout.', 503)
    payments._prepare_collection(actor, enquiry_id, {'request_id': data['request_id'], 'method': 'STRIPE', 'purpose': 'TUITION',
        'collection_mode': 'PARTIAL', 'classes': Decimal(snapshot['installments'][0]['classes']),
        '_autopay_snapshot': snapshot}, request)
    return AutopayAgreement.objects.get(pk=data['request_id'])


def restart_initial(actor, agreement_id, request_id, request=None):
    with transaction.atomic(durable=True):
        agreement = _prepare_restart(actor, agreement_id, request_id, request)
    from .stripe_gateway import create_checkout
    create_checkout(agreement.installments.get(position=0).payment, agreement=agreement, attempt_id=request_id)
    agreement.refresh_from_db()
    return agreement


@transaction.atomic
def _prepare_restart(actor, agreement_id, request_id, request=None):
    agreement = AutopayAgreement.objects.select_related('purchase__sale').filter(pk=agreement_id).first()
    if not agreement:
        raise payments.refusal('NOT_FOUND', 'No such initial agreement.', 404)
    lead = payments.accessible_lead(actor, agreement.purchase.sale.enquiry_id, request, lock=True)
    if agreement.purchase.sale.student_id:
        raise payments.refusal('ALREADY_ENROLLED', 'BDE payment management ends at enrollment.', 403)
    if not configured():
        raise payments.refusal('AUTOPAY_NOT_CONFIGURED', 'Restore the Stripe and approved terms configuration before restarting Checkout.', 503)
    payments.current_quote(actor, lead, request)
    agreement, initial = lock_installment(agreement.installments.get(position=0).pk)
    previous = AutopayAttempt.objects.filter(pk=request_id).first()
    if previous:
        if previous.installment_id != initial.pk:
            raise payments.refusal('IDEMPOTENCY_CONFLICT', 'That request ID belongs to another collection.', 409)
        return agreement
    if initial.payment.status not in ('FAILED', 'EXPIRED'):
        raise payments.refusal('PAYMENT_PENDING', 'Resolve the existing initial payment before generating another Checkout.', 409)
    if agreement.installments.filter(position__gt=0, due_at__lte=timezone.now()).exists():
        raise payments.refusal('SCHEDULE_OVERDUE', 'An agreed collection date has passed. Admin review is needed; the historical schedule cannot be silently changed.', 409)
    payment = initial.payment
    AutopayAttempt.objects.create(id=request_id, installment=initial, number=initial.attempts.count() + 1,
        status='PENDING')
    from .checkout import prepare
    prepare(payment, agreement=agreement, attempt_id=request_id)
    # The original Payment references stay immutable; each new Checkout is an attempt.
    payment.status = initial.status = 'PENDING'
    payment.save(update_fields=['status'])
    initial.save(update_fields=['status'])
    payments.audit('autopay.initial_checkout_restarted', payment.sale, actor, request, agreement=str(agreement.pk), attempt=str(request_id))
    return agreement


def persist_schedule(payment, snapshot):
    consent = (f'I authorize Eduport Plus to save this card and automatically collect the remaining AED '
               f'{Decimal(snapshot["package_amount"]) - payment.amount} according to agreement {payment.pk}. '
               f'The initial payment covers {plain(payment.classes)} classes. Future collections follow the agreed schedule.')
    agreement = AutopayAgreement.objects.create(id=payment.pk, purchase=payment.purchase, created_by=payment.recorded_by,
        creator_role=payment.recorded_by.role, source='BDE_INITIAL', billing_timezone=snapshot['billing_timezone'],
        terms_url=snapshot['terms_url'], consent_text=consent, schedule_digest=snapshot['schedule_digest'],
        livemode=settings.STRIPE_LIVE_MODE, collection_engine=snapshot['collection_engine'])
    AutopayInstallment.objects.bulk_create([AutopayInstallment(agreement=agreement, position=row['position'],
        classes=Decimal(row['classes']), amount=Decimal(row['amount']),
        due_at=datetime.fromisoformat(row['due_at']) if row['due_at'] else None) for row in snapshot['installments']])
    return agreement


def link_initial(agreement, payment):
    initial = agreement.installments.get(position=0)
    initial.payment = payment
    initial.status = 'PENDING'
    initial.save(update_fields=['payment', 'status'])
    AutopayAttempt.objects.create(id=uuid.uuid5(agreement.pk, 'checkout-1'), installment=initial, number=1,
        status='PENDING', stripe_checkout_id=payment.stripe_checkout_id, checkout_url=payment.payment_url)
    agreement.stripe_customer_id = payment.stripe_customer_id
    agreement.save(update_fields=['stripe_customer_id'])
    payments.audit('autopay.created', payment.sale, payment.recorded_by, agreement=str(agreement.pk), digest=agreement.schedule_digest)


def metadata(agreement, installment, attempt_id):
    purchase = agreement.purchase
    return {'payment_id': str(installment.payment_id), 'enquiry_id': str(purchase.sale.enquiry_id),
            'sale_id': str(purchase.sale_id), 'purchase_id': str(purchase.pk), 'quote_id': str(purchase.quote_id),
            'autopay_id': str(agreement.pk), 'installment_id': str(installment.pk), 'attempt_id': str(attempt_id)}


def action_token(attempt):
    return signing.dumps({'attempt': str(attempt.pk)}, salt=ACTION_SALT)


def agreement_data(agreement, include_actions=False):
    if not agreement:
        return None
    from .payments import received
    purchase = agreement.purchase
    rows = []
    for installment in agreement.installments.select_related('payment').prefetch_related('attempts'):
        attempts = []
        for attempt in installment.attempts.all():
            attempts.append({'id': str(attempt.pk), 'number': attempt.number, 'status': attempt.status,
                'created_at': attempt.created_at.isoformat(), 'error_code': attempt.error_code,
                'stripe_payment_intent_id': attempt.stripe_payment_intent_id or None,
                'stripe_checkout_id': attempt.stripe_checkout_id,
                'stripe_charge_id': attempt.stripe_charge_id or None,
                'stripe_invoice_payment_id': attempt.stripe_invoice_payment_id or None,
                'action_url': (installment.stripe_invoice_url if agreement.collection_engine == 'STRIPE_BILLING'
                               else f'{settings.HUB_URL.rstrip("/")}/autopay/confirm/{action_token(attempt)}')
                              if include_actions and attempt.status == 'REQUIRES_CUSTOMER_ACTION' else None})
        rows.append({'id': str(installment.pk), 'position': installment.position, 'classes': plain(installment.classes),
            'amount': plain(installment.amount), 'due_at': installment.due_at.isoformat() if installment.due_at else None,
            'status': installment.status, 'payment_id': str(installment.payment_id) if installment.payment_id else None,
            'paid_at': installment.paid_at.isoformat() if installment.paid_at else None, 'attempts': attempts,
            'stripe_invoice_id': installment.stripe_invoice_id, 'stripe_invoice_status': installment.stripe_invoice_status,
            'stripe_invoice_number': installment.stripe_invoice_number,
            'stripe_invoice_url': installment.stripe_invoice_url if include_actions else None,
            'next_payment_attempt': installment.stripe_next_payment_attempt.isoformat() if installment.stripe_next_payment_attempt else None})
    billing = agreement.collection_engine == 'STRIPE_BILLING'
    unpaid = next((row for row in rows if row['position'] > 0 and row['status'] != 'PAID'), None)
    upcoming = next((row for row in rows if row['position'] > 0 and row['status'] != 'PAID'
                     and row['due_at'] and datetime.fromisoformat(row['due_at']) > timezone.now()), None) if billing else unpaid
    attention = next((row['status'] for row in rows if row['status'] in
        ('FAILED', 'REQUIRES_CUSTOMER_ACTION', 'REQUIRES_RECONCILIATION', 'UNKNOWN', 'VOID', 'UNCOLLECTIBLE')), None)
    if billing and agreement.billing_status in ('REQUIRES_REVIEW', 'ERROR', 'UNKNOWN'):
        attention = agreement.billing_status
    return {'id': str(agreement.pk), 'status': agreement.status, 'setup_status': agreement.setup_status,
        'setup_message': agreement.setup_message, 'billing_timezone': agreement.billing_timezone,
        'creator': {'id': str(agreement.created_by_id), 'name': agreement.created_by.full_name or agreement.created_by.username,
                    'role': agreement.creator_role}, 'source': agreement.source,
        'package_amount': plain(purchase.amount), 'remaining_amount': plain(purchase.amount - received(purchase.sale)['amount']),
        'next_collection_at': upcoming['due_at'] if upcoming else None, 'installments': rows,
        'attention_status': attention,
        'stripe_customer_id': agreement.stripe_customer_id or None, 'stripe_payment_method_id': agreement.stripe_payment_method_id or None,
        'card_brand': agreement.card_brand, 'card_last4': agreement.card_last4, 'livemode': agreement.livemode,
        'initial_paid_at': agreement.initial_paid_at.isoformat() if agreement.initial_paid_at else None,
        'ready_at': agreement.ready_at.isoformat() if agreement.ready_at else None,
        'retry_policy_status': 'STRIPE_NATIVE' if billing else 'LEGACY_NO_RETRY_POLICY',
        'collection_engine': agreement.collection_engine, 'billing_status': agreement.billing_status,
        'billing_message': agreement.billing_message, 'stripe_subscription_id': agreement.stripe_subscription_id,
        'stripe_subscription_status': agreement.stripe_subscription_status,
        'stripe_schedule_id': agreement.stripe_schedule_id, 'stripe_schedule_status': agreement.stripe_schedule_status,
        'next_retry_at': min((row['next_payment_attempt'] for row in rows if row['next_payment_attempt']), default=None),
        'terms_url': agreement.terms_url, 'consent_text': agreement.consent_text,
        'cancelled_at': agreement.cancelled_at.isoformat() if agreement.cancelled_at else None,
        'cancellation_source': agreement.cancellation_source or None, 'cancellation_reason': agreement.cancellation_reason or None,
        'cancelled_by': (agreement.cancelled_by.full_name or agreement.cancelled_by.username) if agreement.cancelled_by_id else None}


def lock_installment(installment_id):
    installment = AutopayInstallment.objects.select_related('agreement__purchase__sale').get(pk=installment_id)
    from .stripe_gateway import lock_sale
    lock_sale(installment.agreement.purchase.sale)
    agreement = AutopayAgreement.objects.select_for_update().select_related('purchase__sale').get(pk=installment.agreement_id)
    installment = AutopayInstallment.objects.select_for_update(of=('self',)).select_related('payment').get(pk=installment_id)
    return agreement, installment


def attempt_state(attempt, status, error_code=''):
    if attempt.status == 'SUCCEEDED':
        return
    previous = attempt.status
    attempt.status, attempt.error_code = status, error_code[:100]
    attempt.save(update_fields=['status', 'error_code', 'stripe_payment_intent_id', 'updated_at'])
    payments.audit('autopay.attempt', attempt.installment.agreement.purchase.sale, None,
                   attempt=str(attempt.pk), previous=previous, status=status, error_code=attempt.error_code)


@transaction.atomic
def prepare_due(installment_id):
    agreement, installment = lock_installment(installment_id)
    if agreement.collection_engine != 'LEGACY_PI':
        return None
    if installment.position == 0 or installment.status == 'PAID' or not agreement.initial_paid_at:
        return None
    if agreement.setup_status != 'READY' or agreement.status != 'ACTIVE' or not agreement.purchase.sale.student_id:
        return None
    if installment.due_at > timezone.now() or agreement.installments.filter(position__lt=installment.position).exclude(status='PAID').exists():
        return None
    previous = installment.attempts.order_by('-number').first()
    if previous:
        # Only transport reconciliation of the SAME attempt. Charge retries await policy.
        if previous.status not in ('SUBMITTING', 'UNKNOWN'):
            return None
        if previous.created_at < timezone.now() - timedelta(hours=23):
            attempt_state(previous, 'REQUIRES_RECONCILIATION', 'idempotency_window')
            installment.status = 'REQUIRES_RECONCILIATION'
            installment.save(update_fields=['status'])
            return None
        return previous.pk
    payment_id = uuid.uuid5(installment.pk, 'payment')
    payment = Payment.objects.create(id=payment_id, request_id=payment_id, sale=agreement.purchase.sale,
        purchase=agreement.purchase, purpose='TUITION', method='STRIPE', collection_mode='PARTIAL', amount=installment.amount,
        classes=installment.classes, recorded_by=agreement.created_by, stripe_customer_id=agreement.stripe_customer_id)
    installment.payment, installment.status = payment, 'PENDING'
    installment.save(update_fields=['payment', 'status'])
    attempt = AutopayAttempt.objects.create(installment=installment, number=1)
    payments.audit('autopay.collection_started', payment.sale, None, agreement=str(agreement.pk), installment=str(installment.pk), attempt=str(attempt.pk))
    return attempt.pk


def collect_due(now=None):
    from .autopay_stripe import submit_attempt, refresh_setup
    from .checkout import reconcile_pending
    reconcile_pending()  # Only initial Checkout transport reconciliation.
    # Readiness reconciliation is not a payment retry and cannot grant quota.
    for agreement in AutopayAgreement.objects.filter(initial_paid_at__isnull=False, setup_status__in=['PENDING', 'INCOMPLETE']):
        refresh_setup(agreement.pk)
    from .billing import provision_ready
    provision_ready()  # Provisioning only; Stripe owns Billing collection/retries.
    ids = list(AutopayInstallment.objects.filter(position__gt=0, due_at__lte=now or timezone.now(),
        agreement__collection_engine='LEGACY_PI', agreement__status='ACTIVE', agreement__setup_status='READY').exclude(status__in=['PAID', 'FAILED', 'REQUIRES_CUSTOMER_ACTION', 'REQUIRES_RECONCILIATION']).values_list('pk', flat=True))
    for installment_id in ids:
        attempt_id = prepare_due(installment_id)
        if attempt_id:
            submit_attempt(attempt_id)
