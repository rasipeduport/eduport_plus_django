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
from .pricing import plain


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


def _lock(sale_id):
    """Collection lock order: the sale's enquiry (when it has one), then the sale."""
    from .stripe_gateway import lock_sale
    return lock_sale(Sale.objects.get(pk=sale_id))


# Payment methods offered on hosted Checkout. Card only for now; Stripe Link is
# hidden as well. Extend this list (and its wallet options) to add methods later.
PAYMENT_METHOD_TYPES = ['card']
WALLET_OPTIONS = {'link': {'display': 'never'}}


def account_metadata(account):
    meta = {'eduport_account_id': str(account.pk), 'eduport_account_ref': account.reference}
    if account.student_id:
        meta.update(student_id=str(account.student_id), edp_student_id=account.student.student_code)
    return meta


def labels(payment, account, guardian):
    """What the parent sees on hosted Checkout, and how the payment is named in Stripe."""
    refs = account.reference + (f' · {account.student.student_code}' if account.student_id else '')
    if payment.purpose == 'TOKEN':
        what = 'admission token (AED 100, no classes)'
        description = f'Eduport Plus admission token — {account.student_name} ({refs})'
    else:
        quote = payment.purchase.quote
        what = f'tuition, {plain(payment.classes)} of {plain(payment.purchase.classes)} classes · quote {quote.reference}'
        description = f'Eduport Plus tuition — {account.student_name} ({refs}) · {plain(payment.classes)} classes · {quote.reference}'
    contact = f' Billing contact: {guardian.full_name}.' if guardian and guardian.full_name else ''
    message = (f'You are paying for {account.student_name} ({refs}): Eduport Plus {what}.{contact} '
               'Student and purchase details are managed by Eduport Plus.')
    return description[:1000], message[:1200]


def prepare(payment, agreement=None, attempt_id=None):
    """Called inside the durable business transaction; contains no provider IO."""
    operation_id = attempt_id or (uuid.uuid5(agreement.pk, 'checkout-1') if agreement else payment.pk)
    existing = StripeCheckoutOperation.objects.filter(pk=operation_id).first()
    if existing:
        if existing.payment_id != payment.pk:
            raise payments.refusal('IDEMPOTENCY_CONFLICT', 'The Checkout request belongs to another payment.', 409)
        return existing
    sale = payment.sale
    account = sale.account
    from .customers import PRODUCTS, prepared_mapping
    from .student_accounts import billing_guardian
    # Django's parent email is on the Customer when known: Checkout then prefills
    # it and does not let it be edited. Without one, Checkout asks for it and the
    # verified webhook saves it (student_accounts.capture_checkout_email).
    guardian = billing_guardian(account)
    # The student's own Customer for this mode: reused by every sale and by Autopay.
    prepared_mapping(account)
    meta = {key: value for key, value in {
        'payment_id': str(payment.pk), 'enquiry_id': str(sale.enquiry_id or ''), 'sale_id': str(sale.pk),
        'purchase_id': str(payment.purchase_id or ''),
        'quote_id': str(payment.purchase.quote_id if payment.purchase_id else sale.original_quote_id or '')}.items() if value}
    meta.update(account_metadata(account))
    description, message = labels(payment, account, guardian)
    params = {'mode': 'payment', 'client_reference_id': str(payment.pk),
        # Card (with wallets) only. Django supplies the Customer, so Checkout asks
        # for no name, phone, address or email; customer_update stays at its
        # default ("never"), so nothing typed at Checkout can rename the student.
        'allowed_payment_method_types': list(PAYMENT_METHOD_TYPES), 'wallet_options': WALLET_OPTIONS,
        'line_items': [{'price_data': {'currency': 'aed', 'unit_amount': int(payment.amount) * 100,
                                       'product': PRODUCTS['TOKEN' if payment.purpose == 'TOKEN' else 'TUITION'][0]}, 'quantity': 1}],
        'metadata': meta, 'payment_intent_data': {'metadata': meta, 'description': description},
        'custom_text': {'submit': {'message': message}},
        'success_url': f'{settings.HUB_URL.rstrip("/")}/payment-return?result=submitted',
        'cancel_url': f'{settings.HUB_URL.rstrip("/")}/payment-return?result=cancelled'}
    if agreement:
        from .autopay_stripe import checkout_options
        options = checkout_options(agreement, payment, operation_id)
        combined = {**options['metadata'], **account_metadata(account)}
        params['metadata'] = combined
        params['payment_intent_data'] = {**options['payment_intent_data'], 'metadata': combined, 'description': description}
        params['allowed_payment_method_types'] = options['allowed_payment_method_types']
        params['wallet_options'] = WALLET_OPTIONS
        params['consent_collection'] = options['consent_collection']
        params['custom_text'] = {**params['custom_text'], **options['custom_text']}
    # Freeze the timestamped parent-review URL and every other parameter ONCE.
    params = copy.deepcopy(params)
    params['metadata']['checkout_operation_id'] = str(operation_id)
    params['payment_intent_data']['metadata']['checkout_operation_id'] = str(operation_id)
    return StripeCheckoutOperation.objects.create(id=operation_id, payment=payment,
        livemode=settings.STRIPE_LIVE_MODE, request=params,
        idempotency_key=f'eduport-checkout-operation-{operation_id}')


def _bind_customer(operation, customer_id):
    with transaction.atomic():
        _lock(operation.payment.sale_id)
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
    from .customers import same_metadata
    request = operation.request
    if (not remote.get('id') or not customer_id or remote.get('customer') != customer_id
            or bool(remote.get('livemode')) != operation.livemode or remote.get('mode') != 'payment'
            or remote.get('currency') != 'aed' or remote.get('client_reference_id') != str(operation.payment_id)
            or remote.get('amount_total') != request['line_items'][0]['price_data']['unit_amount']
            or not same_metadata(remote.get('metadata'), request['metadata'])):
        raise ValueError('Checkout response differs from the durable request, amount or Customer.')


@transaction.atomic
def bind(operation_id, remote):
    operation = StripeCheckoutOperation.objects.select_related('payment__sale').get(pk=operation_id)
    _lock(operation.payment.sale_id)
    operation = StripeCheckoutOperation.objects.select_for_update().select_related('payment__sale').get(pk=operation_id)
    # The Session must be on one of this student's own Customers (never a sibling's).
    owned = set(StripeCustomer.objects.filter(account_id=operation.payment.sale.account_id, livemode=operation.livemode)
                .exclude(customer_id=None).values_list('customer_id', flat=True))
    customer_id = remote.get('customer') if remote.get('customer') in owned else None
    if operation.payment.stripe_customer_id and operation.payment.stripe_customer_id != customer_id:
        customer_id = None
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
    _lock(operation.payment.sale_id)
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
        from .customers import PRODUCTS, customer_for, ensure_product
        customer_id = customer_for(operation.payment.sale.account_id, gateway, operation.livemode)
        _bind_customer(operation, customer_id)
        product = operation.request['line_items'][0]['price_data'].get('product')
        if product:
            ensure_product(gateway, next(purpose for purpose, (pid, _name) in PRODUCTS.items() if pid == product))
        matches = [data(row) for row in gateway.v1.checkout.sessions.list(
            {'customer': customer_id, 'limit': 100}).auto_paging_iter()
            if data(row).get('metadata', {}).get('checkout_operation_id') == str(operation.pk)]
        if len(matches) > 1:
            raise ValueError('Multiple Sessions match this Checkout request. Manual reconciliation is required.')
        if matches:
            return bind(operation.pk, matches[0])
        with transaction.atomic():
            _lock(operation.payment.sale_id)
            operation = StripeCheckoutOperation.objects.select_for_update().select_related('payment__sale').get(pk=operation_id)
            if operation.status == 'BOUND':
                return operation
            if operation.payment.status != 'PENDING':
                raise ValueError('This payment is closed. No new Checkout may be created.')
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
