"""Durable initial Checkout operations. Provider calls run after preparation commits.

This module creates no recurring payments and never marks tuition received.
"""
import copy
import uuid
from datetime import timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import payments
from .payment_models import Payment, Sale, StripeCheckoutOperation, StripeCustomer


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


def _lock(enquiry_id):
    from bookings.models import Lead
    Lead.objects.select_for_update().get(pk=enquiry_id)
    return Sale.objects.select_for_update().get(enquiry_id=enquiry_id)


def prepare(payment, agreement=None, attempt_id=None):
    """Called inside the durable business transaction; contains no provider IO."""
    operation_id = attempt_id or (uuid.uuid5(agreement.pk, 'checkout-1') if agreement else payment.pk)
    existing = StripeCheckoutOperation.objects.filter(pk=operation_id).first()
    if existing:
        if existing.payment_id != payment.pk:
            raise payments.refusal('IDEMPOTENCY_CONFLICT', 'The Checkout request belongs to another payment.', 409)
        return existing
    sale = payment.sale
    customer = StripeCustomer.objects.filter(enquiry_id=sale.enquiry_id).first()
    if customer and customer.livemode != settings.STRIPE_LIVE_MODE:
        raise payments.refusal('STRIPE_MODE_MISMATCH', 'This enquiry’s Customer belongs to a different Stripe mode.', 409)
    if customer is None:
        frozen = {'name': sale.enquiry.parent_name, 'phone': sale.enquiry.phone_key,
                  'metadata': {'enquiry_id': str(sale.enquiry_id), 'eduport_customer_request': str(sale.enquiry_id)}}
        if sale.parent_email:
            frozen['email'] = sale.parent_email
        customer = StripeCustomer.objects.create(enquiry_id=sale.enquiry_id, livemode=settings.STRIPE_LIVE_MODE,
                                                 creation_request=frozen)
    meta = {'payment_id': str(payment.pk), 'enquiry_id': str(sale.enquiry_id), 'sale_id': str(sale.pk),
            'purchase_id': str(payment.purchase_id or ''),
            'quote_id': str(payment.purchase.quote_id if payment.purchase_id else sale.original_quote_id or '')}
    params = {'mode': 'payment', 'client_reference_id': str(payment.pk),
        'line_items': [{'price_data': {'currency': 'aed', 'unit_amount': int(payment.amount) * 100,
            'product_data': {'name': 'Eduport Plus token reservation' if payment.purpose == 'TOKEN'
                             else f'Eduport Plus tuition · {payment.classes} classes'}}, 'quantity': 1}],
        'metadata': meta, 'payment_intent_data': {'metadata': meta},
        'success_url': f'{settings.HUB_URL.rstrip("/")}/payment-return?result=submitted',
        'cancel_url': f'{settings.HUB_URL.rstrip("/")}/payment-return?result=cancelled'}
    if agreement:
        from .autopay_stripe import checkout_options
        params.update(checkout_options(agreement, payment, operation_id))
    # Freeze the timestamped parent-review URL and every other parameter ONCE.
    params = copy.deepcopy(params)
    params['metadata']['checkout_operation_id'] = str(operation_id)
    params['payment_intent_data']['metadata']['checkout_operation_id'] = str(operation_id)
    return StripeCheckoutOperation.objects.create(id=operation_id, payment=payment,
        livemode=settings.STRIPE_LIVE_MODE, request=params,
        idempotency_key=f'eduport-checkout-operation-{operation_id}')


def _customer(operation, gateway):
    enquiry_id = operation.payment.sale.enquiry_id
    with transaction.atomic():
        _lock(enquiry_id)
        mapping = StripeCustomer.objects.select_for_update().get(enquiry_id=enquiry_id)
        if mapping.livemode != operation.livemode:
            raise ValueError('Checkout Customer environment does not match.')
        if mapping.customer_id:
            return mapping.customer_id
        if not mapping.creation_request:
            raise ValueError('The Customer has no durable creation request. Manual reconciliation is required.')
        started = mapping.creation_started_at
        if not started:
            mapping.creation_started_at = timezone.now()
            mapping.save(update_fields=['creation_started_at'])
    matches = []
    if started:
        # Recover by the frozen operation marker, never by email. Absence never
        # authorizes a new key after an uncertain expired request.
        matches = [data(row) for row in gateway.v1.customers.list({'limit': 100}).auto_paging_iter()
                   if data(row).get('metadata', {}).get('eduport_customer_request') == str(enquiry_id)]
    if len(matches) > 1:
        raise ValueError('Multiple Customers match this creation request. No automatic merge or creation is permitted.')
    if matches:
        remote = matches[0]
    elif started and started < timezone.now() - timedelta(hours=23):
        raise ValueError('Customer creation is unconfirmed beyond the safe idempotency window. Manual reconciliation is required.')
    else:
        remote = data(gateway.v1.customers.create(mapping.creation_request,
            options={'idempotency_key': f'eduport-customer-{enquiry_id}-{mapping.livemode}'}))
    if (not remote.get('id') or remote.get('deleted') or bool(remote.get('livemode')) != mapping.livemode
            or any(remote.get('metadata', {}).get(k) != v for k, v in mapping.creation_request['metadata'].items())):
        raise ValueError('The recovered Customer does not match the frozen enquiry request.')
    with transaction.atomic():
        _lock(enquiry_id)
        mapping = StripeCustomer.objects.select_for_update().get(enquiry_id=enquiry_id)
        if mapping.customer_id and mapping.customer_id != remote['id']:
            raise ValueError('Another Customer is already bound. Historical references were not changed.')
        mapping.customer_id = remote['id']
        mapping.save(update_fields=['customer_id'])
    return remote['id']


def _bind_customer(operation, customer_id):
    with transaction.atomic():
        _lock(operation.payment.sale.enquiry_id)
        payment = Payment.objects.select_for_update().get(pk=operation.payment_id)
        if payment.stripe_customer_id and payment.stripe_customer_id != customer_id:
            raise ValueError('Payment Customer is already fixed to another identity.')
        if not payment.stripe_customer_id:
            payment.stripe_customer_id = customer_id
            payment.save(update_fields=['stripe_customer_id'])
        from .autopay_models import AutopayAgreement
        agreement = AutopayAgreement.objects.filter(purchase_id=payment.purchase_id).first() if payment.purchase_id else None
        if agreement and not agreement.stripe_customer_id:
            agreement.stripe_customer_id = customer_id
            agreement.save(update_fields=['stripe_customer_id'])


def validate(operation, remote, customer_id):
    request = operation.request
    if (not remote.get('id') or remote.get('customer') != customer_id
            or bool(remote.get('livemode')) != operation.livemode or remote.get('mode') != 'payment'
            or remote.get('currency') != 'aed' or remote.get('client_reference_id') != str(operation.payment_id)
            or remote.get('amount_total') != request['line_items'][0]['price_data']['unit_amount']
            or any(remote.get('metadata', {}).get(k) != v for k, v in request['metadata'].items())):
        raise ValueError('Checkout response differs from the durable request, amount or Customer.')


@transaction.atomic
def bind(operation_id, remote):
    operation = StripeCheckoutOperation.objects.select_related('payment__sale').get(pk=operation_id)
    _lock(operation.payment.sale.enquiry_id)
    operation = StripeCheckoutOperation.objects.select_for_update().select_related('payment').get(pk=operation_id)
    customer_id = StripeCustomer.objects.get(enquiry_id=operation.payment.sale.enquiry_id).customer_id
    validate(operation, remote, customer_id)
    if operation.stripe_checkout_id and operation.stripe_checkout_id != remote['id']:
        raise ValueError('Another Session is already bound to this Checkout operation.')
    operation.stripe_checkout_id = remote['id']
    operation.checkout_url = operation.checkout_url or remote.get('url') or ''
    operation.status, operation.message = 'BOUND', ''
    operation.save(update_fields=['stripe_checkout_id', 'checkout_url', 'status', 'message'])
    from .autopay_models import AutopayAttempt
    attempt = AutopayAttempt.objects.filter(pk=operation.pk, installment__payment_id=operation.payment_id).first()
    if attempt and attempt.status != 'SUCCEEDED':
        attempt.stripe_checkout_id = operation.stripe_checkout_id
        attempt.checkout_url = operation.checkout_url
        attempt.save(update_fields=['stripe_checkout_id', 'checkout_url'])
    payment = Payment.objects.select_for_update().get(pk=operation.payment_id)
    # Restart attempts have their own origin. Never overwrite the original one.
    if not payment.stripe_checkout_id and payment.status != 'SUCCEEDED':
        payment.stripe_checkout_id, payment.payment_url = operation.stripe_checkout_id, operation.checkout_url
        payment.save(update_fields=['stripe_checkout_id', 'payment_url'])
    return operation


def accept_webhook(obj):
    """Bind a lost response before normal signed-webhook settlement validation."""
    try:
        operation_id = uuid.UUID(obj.get('metadata', {}).get('checkout_operation_id', ''))
    except (ValueError, TypeError, AttributeError):
        return
    if StripeCheckoutOperation.objects.filter(pk=operation_id).exists():
        bind(operation_id, obj)


@transaction.atomic
def rejected(operation_id):
    operation = StripeCheckoutOperation.objects.select_related('payment__sale').get(pk=operation_id)
    _lock(operation.payment.sale.enquiry_id)
    operation = StripeCheckoutOperation.objects.select_for_update().get(pk=operation_id)
    if operation.status == 'BOUND':
        return
    operation.status, operation.message = 'ERROR', 'Stripe rejected this Checkout request. Correct the configuration before starting an explicit replacement Checkout attempt.'
    operation.save(update_fields=['status', 'message'])
    payment = Payment.objects.select_for_update().get(pk=operation.payment_id)
    if payment.status == 'PENDING':
        payment.status = 'FAILED'
        payment.save(update_fields=['status'])
    from .autopay_models import AutopayAttempt
    attempt = AutopayAttempt.objects.filter(pk=operation.pk, installment__payment_id=payment.pk).first()
    if attempt and attempt.status != 'SUCCEEDED':
        from .autopay import attempt_state
        attempt_state(attempt, 'FAILED', 'checkout_request_rejected')
        attempt.installment.status = 'FAILED'
        attempt.installment.save(update_fields=['status'])


def fulfill(operation_id):
    from .stripe_gateway import client
    operation = StripeCheckoutOperation.objects.select_related('payment__sale').get(pk=operation_id)
    if operation.livemode != settings.STRIPE_LIVE_MODE:
        raise payments.refusal('STRIPE_MODE_MISMATCH', 'Checkout belongs to another Stripe environment.', 409)
    if operation.status == 'BOUND':
        return operation
    if operation.status in ('ERROR', 'REQUIRES_REVIEW'):
        raise payments.refusal('CHECKOUT_REVIEW_REQUIRED', operation.message, 409)
    try:
        gateway = client()
        customer_id = _customer(operation, gateway)
        _bind_customer(operation, customer_id)
        matches = [data(row) for row in gateway.v1.checkout.sessions.list(
            {'customer': customer_id, 'limit': 100}).auto_paging_iter()
            if data(row).get('metadata', {}).get('checkout_operation_id') == str(operation.pk)]
        if len(matches) > 1:
            raise ValueError('Multiple Sessions match this Checkout request. Manual reconciliation is required.')
        if matches:
            return bind(operation.pk, matches[0])
        with transaction.atomic():
            _lock(operation.payment.sale.enquiry_id)
            operation = StripeCheckoutOperation.objects.select_for_update().select_related('payment__sale').get(pk=operation_id)
            if operation.status == 'BOUND':
                return operation
            if operation.payment.status != 'PENDING' or operation.payment.sale.student_id:
                raise ValueError('This initial payment is closed. No new Checkout may be created.')
            if operation.started_at and operation.started_at < timezone.now() - timedelta(hours=23):
                raise ValueError('Checkout creation is unconfirmed beyond its safe idempotency window. No fresh Session was created.')
            operation.started_at = operation.started_at or timezone.now()
            operation.status = 'SUBMITTING'
            operation.save(update_fields=['started_at', 'status'])
        remote = data(gateway.v1.checkout.sessions.create({**operation.request, 'customer': customer_id},
            options={'idempotency_key': operation.idempotency_key}))
        return bind(operation.pk, remote)
    except ValueError as exc:
        StripeCheckoutOperation.objects.filter(pk=operation_id).exclude(status='BOUND').update(status='REQUIRES_REVIEW', message=str(exc)[:255])
        raise payments.refusal('CHECKOUT_REVIEW_REQUIRED', str(exc), 409) from exc
    except stripe.InvalidRequestError as exc:
        from .stripe_gateway import is_definitive_rejection
        if not is_definitive_rejection(exc):
            StripeCheckoutOperation.objects.filter(pk=operation_id).exclude(status='BOUND').update(
                status='UNKNOWN', message='Stripe has not established the Checkout outcome. Reconciliation will reuse the frozen request and key.')
            raise payments.refusal('STRIPE_UNAVAILABLE', 'Checkout is still unconfirmed; no replacement request was created.', 503) from exc
        rejected(operation_id)
        raise payments.refusal('STRIPE_CHECKOUT_REJECTED', 'Stripe rejected Checkout. Correct the configuration and review the existing failed attempt before replacing it.', 409) from exc
    except stripe.StripeError as exc:
        # Never discard the committed origin or generate another key on uncertainty.
        StripeCheckoutOperation.objects.filter(pk=operation_id).exclude(status='BOUND').update(
            status='UNKNOWN', message='Stripe response is unconfirmed. The same frozen Checkout request will be reconciled.')
        raise payments.refusal('STRIPE_UNAVAILABLE', 'Checkout response is unconfirmed. Retry the same request ID or refresh after reconciliation.', 503) from exc


def reconcile_pending():
    for operation_id in list(StripeCheckoutOperation.objects.filter(
            status__in=['PREPARED', 'SUBMITTING', 'UNKNOWN'], payment__status='PENDING').values_list('pk', flat=True)):
        try:
            fulfill(operation_id)
        except payments.SalesError:
            continue
