"""Real Stripe-hosted Checkout links bound to the student account's Customer."""
import logging
import uuid

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .payment_models import Payment, PaymentStatus, Sale, StripeEvent
from .payments import accessible_lead, audit, refusal, stripe_configured, succeed

logger = logging.getLogger(__name__)


def is_definitive_rejection(exc):
    # A concurrent/in-flight request is not proof that creation was rejected.
    return (isinstance(exc, stripe.InvalidRequestError) and exc.http_status in (400, 404, 422)
            and exc.code not in ('idempotency_key_in_use', 'idempotency_error', 'lock_timeout'))


def client():
    if not stripe_configured():
        raise refusal('STRIPE_NOT_CONFIGURED', 'Configure a matching Stripe test/live secret key and webhook secret before collecting through Stripe.', 503)
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY, max_network_retries=2,
                               http_client=stripe.RequestsClient(timeout=15))


def create_checkout(payment, agreement=None, attempt_id=None):
    from .checkout import fulfill
    operations = payment.checkout_operations.all()
    operation = operations.filter(pk=attempt_id).first() if attempt_id else operations.order_by('-created_at').first()
    if operation:
        fulfill(operation.pk)
        payment.refresh_from_db()
    elif not payment.stripe_checkout_id:
        # A historical unknown request has no reproducible body. Do not replace it.
        raise refusal('CHECKOUT_REVIEW_REQUIRED', 'No durable Checkout request exists. Review the historical payment before creating another link.', 409)


def verify_payload(raw_body, signature):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise refusal('STRIPE_NOT_CONFIGURED', 'Stripe webhooks are not configured.', 503)
    try:
        return stripe.Webhook.construct_event(raw_body, signature, settings.STRIPE_WEBHOOK_SECRET).to_dict()
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise refusal('INVALID_SIGNATURE', 'Invalid Stripe webhook signature.', 400) from exc


def _data(value):
    return value if isinstance(value, dict) else value.to_dict()


def _text(value):
    return value if isinstance(value, str) else ''


def _identifier(value):
    return _text(value.get('id')) if isinstance(value, dict) else _text(value)


def card_evidence(charge):
    """Charge ID and payer/card snapshot from an expanded Stripe charge. Evidence only."""
    if not isinstance(charge, dict):
        return _identifier(charge), {}
    card = (charge.get('payment_method_details') or {}).get('card') or {}
    billing = charge.get('billing_details') or {}
    payer = {'cardholder_name': _text(billing.get('name')), 'card_brand': _text(card.get('brand')),
             'card_last4': _text(card.get('last4')), 'card_country': _text(card.get('country'))}
    return _identifier(charge), {key: value for key, value in payer.items() if value}


def checkout_evidence(session):
    """Who paid, as Stripe reports it, plus the charge. Never used to identify a student."""
    details = session.get('customer_details') or {}
    payer = {'name': _text(details.get('name')), 'email': _text(details.get('email')), 'phone': _text(details.get('phone')),
             'country': _text((details.get('address') or {}).get('country'))}
    payer = {key: value for key, value in payer.items() if value}
    charge_id = ''
    try:
        intent = _data(client().v1.payment_intents.retrieve(session['payment_intent'], {'expand': ['latest_charge']}))
        charge_id, card = card_evidence(intent.get('latest_charge'))
        payer.update(card)
    except Exception:  # Evidence only: the charge is filled in later from payment_intent.succeeded.
        logger.warning('Charge evidence for Checkout %s will be completed from a later event', session.get('id'))
    return (charge_id if charge_id.startswith('ch_') else ''), payer


def _pending_evidence(event_type, obj):
    """Failure details and charge evidence on Django's own Stripe payments (Checkout PaymentIntents)."""
    payment_id = (obj.get('metadata') or {}).get('payment_id')
    if not payment_id or not event_type.startswith('payment_intent.'):
        return
    payment = Payment.objects.select_related('sale').filter(pk=payment_id, method='STRIPE').first() if _uuid(payment_id) else None
    if payment is None or obj.get('customer') != payment.stripe_customer_id:
        return
    # Same lock order as collection: enquiry (when the sale has one), sale, then payment.
    lock_sale(payment.sale)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    fields = []
    if event_type == 'payment_intent.payment_failed' and payment.status == PaymentStatus.PENDING:
        error = obj.get('last_payment_error') or {}
        payment.failure_code = _text(error.get('decline_code') or error.get('code'))[:100]
        payment.failure_message = _text(error.get('message'))[:255]
        fields += ['failure_code', 'failure_message']
    if event_type == 'payment_intent.succeeded' and not payment.stripe_charge_id:
        charge_id = _identifier(obj.get('latest_charge'))
        if charge_id.startswith('ch_') and (payment.status == PaymentStatus.PENDING or payment.stripe_payment_intent == obj.get('id')):
            payment.stripe_charge_id = charge_id
            fields.append('stripe_charge_id')
    if fields:
        payment.save(update_fields=fields)


def lock_sale(sale):
    """Collection lock order: the enquiry when the sale has one, then the sale."""
    if sale.enquiry_id:
        from bookings.models import Lead
        Lead.objects.select_for_update().get(pk=sale.enquiry_id)
    return Sale.objects.select_for_update().get(pk=sale.pk)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _matches(meta, expected):
    from .customers import same_metadata
    return same_metadata(meta, expected)


AUTOPAY_EVENT_PREFIXES = ('checkout.session.', 'payment_intent.')


@transaction.atomic
def process_event(event):
    event_id = event.get('id')
    event_type = event.get('type')
    if not event_id or not event_type:
        raise refusal('INVALID_EVENT', 'The Stripe event is incomplete.')
    obj = event.get('data', {}).get('object', {})
    record, created = StripeEvent.objects.get_or_create(event_id=event_id, defaults={'event_type': event_type, 'object_id': obj.get('id', '')})
    record = StripeEvent.objects.select_for_update().get(pk=record.pk)
    if not created and record.outcome != 'RECEIVED':
        return record
    from .billing import EVENTS as BILLING_EVENTS
    from .refunds import DISPUTE_EVENTS, REFUND_EVENTS
    from . import review
    from .ledger_models import ReviewKind
    livemode_ok = bool(event.get('livemode')) == settings.STRIPE_LIVE_MODE
    if livemode_ok and event_type.startswith('checkout.session.') and obj.get('metadata', {}).get('checkout_operation_id'):
        from .checkout import accept_webhook
        try:
            accept_webhook(obj)
        except ValueError as exc:
            record.outcome, record.error = 'REJECTED', str(exc)[:255]
            record.save(update_fields=['outcome', 'error'])
            review.record(ReviewKind.INCONSISTENT, obj, record, record.error)
            return record
    if livemode_ok:
        _pending_evidence(event_type, obj)
    if not livemode_ok:
        record.outcome, record.error = 'REJECTED', 'Stripe test/live mode mismatch.'
    elif event_type in BILLING_EVENTS:
        from .billing import process_event as process_billing_event
        process_billing_event(event, record)
    elif event_type in REFUND_EVENTS or event_type in DISPUTE_EVENTS:
        from .refunds import process as process_refund_event
        process_refund_event(event, record)
    elif event_type in ('payment_link.created', 'payment_link.updated'):
        # Tuition is collected only through Django-created Checkout. A Payment Link
        # is never credited; it is surfaced for Admin follow-up.
        review.record(ReviewKind.PAYMENT_LINK_CREATED, obj, record, 'A Stripe Payment Link was created or changed outside Django.')
        record.outcome = 'IGNORED'
    elif obj.get('metadata', {}).get('autopay_id') and event_type.startswith(AUTOPAY_EVENT_PREFIXES):
        from .autopay_stripe import process_event as process_autopay_event
        process_autopay_event(event, record)
    elif event_type == 'payment_method.detached':
        from .autopay_models import AutopayAgreement
        for agreement in AutopayAgreement.objects.filter(stripe_payment_method_id=obj.get('id'), livemode=settings.STRIPE_LIVE_MODE):
            agreement.setup_status, agreement.status = 'INCOMPLETE', 'SETUP_INCOMPLETE'
            agreement.setup_message = 'The saved payment method was detached. Admin follow-up is required.'
            agreement.save(update_fields=['setup_status', 'status', 'setup_message'])
        record.outcome = 'PROCESSED'
    elif event_type not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded',
                             'checkout.session.async_payment_failed', 'checkout.session.expired'):
        record.outcome = 'IGNORED'
    else:
        payment = Payment.objects.select_related('sale').filter(stripe_checkout_id=obj.get('id'), method='STRIPE').first()
        if payment is None:
            record.outcome, record.error = 'IGNORED', 'Checkout Session is not part of this sales ledger.'
            if event_type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
                review.record(review.checkout_kind(obj), obj, record, 'A completed Checkout that Django did not create was not credited.')
        else:
            # Same lock order as collection: enquiry (when the sale has one), sale, then payment.
            sale = lock_sale(payment.sale)
            payment = Payment.objects.select_for_update(of=('self',)).select_related('sale__enquiry', 'purchase', 'recorded_by').get(pk=payment.pk)
            expected_meta = {'payment_id': str(payment.pk), 'enquiry_id': str(sale.enquiry_id or ''), 'sale_id': str(sale.pk),
                             'purchase_id': str(payment.purchase_id or ''),
                             'quote_id': str(payment.purchase.quote_id if payment.purchase_id else sale.original_quote_id or '')}
            meta = obj.get('metadata') or {}
            # Sessions created before student accounts carry no account reference;
            # newer ones must name this sale's own account.
            account_ok = not meta.get('eduport_account_id') or meta.get('eduport_account_id') == str(sale.account_id)
            valid = (obj.get('customer') == payment.stripe_customer_id and obj.get('currency', '').lower() == 'aed'
                     and obj.get('amount_total') == int(payment.amount) * 100
                     and obj.get('client_reference_id') == str(payment.pk)
                     and _matches(meta, expected_meta) and account_ok)
            if not valid:
                record.outcome, record.error = 'REJECTED', 'Payment amount, currency, customer, student account or linked references do not match.'
            elif event_type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
                if obj.get('payment_status') != 'paid':
                    record.outcome = 'AWAITING_PAYMENT'
                elif not isinstance(obj.get('payment_intent'), str) or not obj['payment_intent'].startswith('pi_'):
                    record.outcome, record.error = 'REJECTED', 'A successful PaymentIntent reference is required.'
                elif payment.status == PaymentStatus.SUCCEEDED:
                    record.outcome = 'DUPLICATE'
                elif Payment.objects.filter(stripe_payment_intent=obj['payment_intent']).exclude(pk=payment.pk).exists():
                    record.outcome, record.error = 'REJECTED', 'PaymentIntent was already credited.'
                else:
                    charge_id, payer = checkout_evidence(obj)
                    succeed(payment, provider_id=obj['payment_intent'], charge_id=charge_id, payer=payer)
                    # Verified success only: a missing parent email typed on Checkout is kept.
                    from .student_accounts import capture_checkout_email
                    capture_checkout_email(sale, (obj.get('customer_details') or {}).get('email'), payment)
                    record.outcome = 'PROCESSED'
            elif payment.status != PaymentStatus.SUCCEEDED:
                payment.status = PaymentStatus.EXPIRED if event_type.endswith('expired') else PaymentStatus.FAILED
                payment.save(update_fields=['status'])
                record.outcome = 'PROCESSED'
            else:
                record.outcome = 'DUPLICATE'
    if record.outcome == 'REJECTED':
        review.record(ReviewKind.INCONSISTENT, obj, record, record.error or 'Rejected Stripe event.')
    record.save(update_fields=['outcome', 'error'])
    return record


@transaction.atomic
def expire_checkout(actor, payment_id, request=None):
    payment = Payment.objects.select_related('sale').filter(pk=payment_id).first()
    if payment is None or not payment.sale.enquiry_id:
        raise refusal('NOT_FOUND', 'No such payment.', 404)
    accessible_lead(actor, payment.sale.enquiry_id, request, lock=True)
    from accounts.authz import has_app_permission
    if payment.recorded_by_id != actor.pk and not has_app_permission(actor, 'accounts.manage_sales_quotes', request):
        raise refusal('PLAN_OWNER_CHANGED', 'An administrator must review the previous owner’s payment link.', 409)
    payment = Payment.objects.select_for_update().select_related('sale').get(pk=payment.pk)
    return expire_locked(actor, payment, request)


def expire_locked(actor, payment, request=None):
    """Caller holds the sale (and enquiry) locks and authorized ``actor``."""
    if payment.status != PaymentStatus.PENDING or payment.method != 'STRIPE':
        raise refusal('PAYMENT_NOT_PENDING', 'Only an unpaid Stripe link can be expired.', 409)
    try:
        from .autopay_models import AutopayInstallment
        initial = AutopayInstallment.objects.filter(payment=payment, position=0).first()
        attempt = initial.attempts.order_by('-number').first() if initial else None
        client().v1.checkout.sessions.expire(attempt.stripe_checkout_id if attempt else payment.stripe_checkout_id)
    except stripe.StripeError as exc:
        raise refusal('STRIPE_UNAVAILABLE', 'Stripe could not confirm expiry. The payment remains pending.', 503) from exc
    payment.status = PaymentStatus.EXPIRED
    payment.save(update_fields=['status'])
    if attempt:
        from .autopay import attempt_state
        attempt_state(attempt, 'EXPIRED')
        initial.status = 'EXPIRED'
        initial.save(update_fields=['status'])
    audit('payment.expired', payment.sale, actor, request, payment=str(payment.pk))
    return payment
