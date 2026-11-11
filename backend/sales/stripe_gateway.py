"""Real Stripe-hosted Checkout links bound to the stable enquiry Customer."""
import logging

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .payment_models import Payment, PaymentStatus, Sale, StripeCustomer, StripeEvent
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
    mapping = StripeCustomer.objects.filter(enquiry_id=payment.sale.enquiry_id).first()
    if mapping and mapping.livemode != settings.STRIPE_LIVE_MODE:
        raise refusal('STRIPE_MODE_MISMATCH', 'This enquiry’s Customer belongs to a different Stripe mode.', 409)
    operations = payment.checkout_operations.all()
    operation = operations.filter(pk=attempt_id).first() if attempt_id else operations.order_by('-created_at').first()
    if operation:
        fulfill(operation.pk)
        payment.refresh_from_db()
    elif not payment.stripe_checkout_id:
        # A historical unknown request has no reproducible body. Do not replace it.
        raise refusal('CHECKOUT_REVIEW_REQUIRED', 'No durable Checkout request exists. Review the historical payment before creating another link.', 409)


def sync_customer_metadata(enquiry_id):
    customer = StripeCustomer.objects.filter(enquiry_id=enquiry_id, student_metadata_synced=False, customer_id__isnull=False).first()
    sale = Sale.objects.select_related('student').filter(enquiry_id=enquiry_id, student__isnull=False).first()
    if not customer or not sale:
        return
    try:
        client().v1.customers.update(customer.customer_id, {'metadata': {'enquiry_id': str(enquiry_id),
                                    'student_id': str(sale.student_id), 'edp_student_id': sale.student.student_code}})
        StripeCustomer.objects.filter(pk=enquiry_id).update(student_metadata_synced=True)
    except Exception:
        # This callback runs after the enrollment transaction committed. Beat retries it.
        logger.exception('Stripe student metadata update will be retried for enquiry %s', enquiry_id)


def verify_payload(raw_body, signature):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise refusal('STRIPE_NOT_CONFIGURED', 'Stripe webhooks are not configured.', 503)
    try:
        return stripe.Webhook.construct_event(raw_body, signature, settings.STRIPE_WEBHOOK_SECRET).to_dict()
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise refusal('INVALID_SIGNATURE', 'Invalid Stripe webhook signature.', 400) from exc


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
    if (bool(event.get('livemode')) == settings.STRIPE_LIVE_MODE and event_type.startswith('checkout.session.')
            and obj.get('metadata', {}).get('checkout_operation_id')):
        from .checkout import accept_webhook
        try:
            accept_webhook(obj)
        except ValueError as exc:
            record.outcome, record.error = 'REJECTED', str(exc)[:255]
            record.save(update_fields=['outcome', 'error'])
            return record
    if bool(event.get('livemode')) != settings.STRIPE_LIVE_MODE:
        record.outcome, record.error = 'REJECTED', 'Stripe test/live mode mismatch.'
    elif event_type in BILLING_EVENTS:
        from .billing import process_event as process_billing_event
        process_billing_event(event, record)
    elif obj.get('metadata', {}).get('autopay_id'):
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
        else:
            # Same lock order as BDE collection: enquiry, sale, then payment.
            from bookings.models import Lead
            Lead.objects.select_for_update().get(pk=payment.sale.enquiry_id)
            sale = Sale.objects.select_for_update().get(pk=payment.sale_id)
            payment = Payment.objects.select_for_update(of=('self',)).select_related('sale__enquiry', 'purchase', 'recorded_by').get(pk=payment.pk)
            expected_meta = {'payment_id': str(payment.pk), 'enquiry_id': str(sale.enquiry_id), 'sale_id': str(sale.pk),
                             'purchase_id': str(payment.purchase_id or ''),
                             'quote_id': str(payment.purchase.quote_id if payment.purchase_id else sale.original_quote_id or '')}
            valid = (obj.get('customer') == payment.stripe_customer_id and obj.get('currency', '').lower() == 'aed'
                     and obj.get('amount_total') == int(payment.amount) * 100
                     and obj.get('client_reference_id') == str(payment.pk)
                     and all(obj.get('metadata', {}).get(key) == value for key, value in expected_meta.items()))
            if not valid:
                record.outcome, record.error = 'REJECTED', 'Payment amount, currency, customer or linked references do not match.'
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
                    succeed(payment, provider_id=obj['payment_intent'])
                    record.outcome = 'PROCESSED'
            elif payment.status != PaymentStatus.SUCCEEDED:
                payment.status = PaymentStatus.EXPIRED if event_type.endswith('expired') else PaymentStatus.FAILED
                payment.save(update_fields=['status'])
                record.outcome = 'PROCESSED'
            else:
                record.outcome = 'DUPLICATE'
    record.save(update_fields=['outcome', 'error'])
    return record


@transaction.atomic
def expire_checkout(actor, payment_id, request=None):
    payment = Payment.objects.select_related('sale').filter(pk=payment_id).first()
    if payment is None:
        raise refusal('NOT_FOUND', 'No such payment.', 404)
    accessible_lead(actor, payment.sale.enquiry_id, request, lock=True)
    from accounts.authz import has_app_permission
    if payment.recorded_by_id != actor.pk and not has_app_permission(actor, 'accounts.manage_sales_quotes', request):
        raise refusal('PLAN_OWNER_CHANGED', 'An administrator must review the previous owner’s payment link.', 409)
    payment = Payment.objects.select_for_update().select_related('sale').get(pk=payment.pk)
    if payment.sale.student_id:
        raise refusal('ALREADY_ENROLLED', 'BDE collection ends at enrollment.', 403)
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
