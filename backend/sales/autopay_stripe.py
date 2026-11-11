"""Stripe transport and verification for the shared Autopay lifecycle."""
import uuid

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import autopay, payments
from .autopay_models import AutopayAgreement, AutopayAttempt
from .payment_models import StripeCustomer
from .pricing import plain


def as_dict(value):
    if isinstance(value, dict):
        return value
    return value.to_dict()


def checkout_options(agreement, payment, attempt_id=None):
    initial = agreement.installments.get(position=0)
    attempt_id = attempt_id or uuid.uuid5(agreement.pk, 'checkout-1')
    metadata = autopay.metadata(agreement, initial, attempt_id)
    metadata['payment_id'] = str(payment.pk)
    token = autopay.signing.dumps({'attempt': str(attempt_id)}, salt=autopay.ACTION_SALT)
    review_url = f'{settings.HUB_URL.rstrip("/")}/autopay/confirm/{token}'
    consent_message = f'{agreement.consent_text} Read the [agreed schedule]({review_url}) and [Autopay terms]({agreement.terms_url}).'
    if len(consent_message) > 1200:
        raise payments.refusal('AUTOPAY_TERMS_INVALID', 'The configured terms link exceeds Stripe’s consent-text limit. Configure a shorter approved URL.', 503)
    return {'metadata': metadata, 'payment_method_types': ['card'],
            'consent_collection': {'terms_of_service': 'required', 'payment_method_reuse_agreement': {'position': 'auto'}},
            'custom_text': {'terms_of_service_acceptance': {'message': consent_message}},
            'payment_intent_data': {'metadata': metadata, 'setup_future_usage': 'off_session'}}


@transaction.atomic
def refresh_setup(agreement_id, checkout=None):
    initial_id = AutopayAgreement.objects.get(pk=agreement_id).installments.get(position=0).pk
    agreement, initial = autopay.lock_installment(initial_id)
    if not agreement.initial_paid_at:
        return
    if agreement.collection_engine == 'STRIPE_BILLING' and (agreement.stripe_schedule_id or agreement.stripe_subscription_id):
        from .billing import refresh_current_method
        refresh_current_method(agreement)
        payments.audit('autopay.setup_verified', agreement.purchase.sale, None,
                       agreement=str(agreement.pk), setup_status=agreement.setup_status, source='CURRENT_BILLING')
        return
    from .stripe_gateway import client
    try:
        gateway = client()
        # A paid Checkout and its reuse consent are independent of successful attachment.
        if not agreement.consent_verified_at:
            first = initial.attempts.filter(stripe_payment_intent_id=initial.payment.stripe_payment_intent).first()
            session = checkout or as_dict(gateway.v1.checkout.sessions.retrieve(first.stripe_checkout_id))
            if session.get('consent', {}).get('terms_of_service') != 'accepted':
                raise ValueError('The parent’s Autopay consent has not been verified.')
            agreement.consent_verified_at = timezone.now()
        pi = as_dict(gateway.v1.payment_intents.retrieve(initial.payment.stripe_payment_intent))
        if (pi.get('status') != 'succeeded' or pi.get('customer') != agreement.stripe_customer_id
                or pi.get('currency') != 'aed' or pi.get('amount_received') != int(initial.amount) * 100
                or pi.get('setup_future_usage') != 'off_session' or bool(pi.get('livemode')) != agreement.livemode):
            raise ValueError('The paid PaymentIntent has not confirmed future off-session setup for this Customer.')
        method_id = pi.get('payment_method')
        if not isinstance(method_id, str) or not method_id.startswith('pm_'):
            raise ValueError('Stripe has not supplied a saved payment method.')
        method = as_dict(gateway.v1.payment_methods.retrieve(method_id))
        if method.get('type') != 'card':
            agreement.setup_status = 'UNSUPPORTED'
            raise ValueError('This payment method is not supported for the configured card Autopay flow.')
        if agreement.collection_engine == 'STRIPE_BILLING' and method.get('card', {}).get('country') == 'IN':
            agreement.setup_status = 'UNSUPPORTED'
            raise ValueError('India-issued cards need a Stripe Subscription mandate setup flow. The initial tuition payment is retained; automatic setup requires follow-up.')
        mapping = StripeCustomer.objects.get(enquiry_id=agreement.purchase.sale.enquiry_id)
        if (mapping.customer_id != agreement.stripe_customer_id or mapping.livemode != agreement.livemode
                or method.get('customer') != agreement.stripe_customer_id or bool(method.get('livemode')) != agreement.livemode):
            raise ValueError('The reusable method is not attached to the correct Customer and Stripe environment.')
        agreement.stripe_payment_method_id = method_id
        agreement.card_brand = method.get('card', {}).get('brand', '')
        agreement.card_last4 = method.get('card', {}).get('last4', '')
        agreement.setup_status, agreement.status, agreement.setup_message = 'READY', 'ACTIVE', ''
        agreement.ready_at = agreement.ready_at or timezone.now()
    except (stripe.StripeError, ValueError, StripeCustomer.DoesNotExist, AttributeError) as exc:
        agreement.setup_status = 'UNSUPPORTED' if agreement.setup_status == 'UNSUPPORTED' else 'INCOMPLETE'
        agreement.status = 'SETUP_INCOMPLETE'
        agreement.setup_message = str(exc)[:255] if isinstance(exc, ValueError) else 'Stripe payment-method verification is incomplete. Admin follow-up is required.'
    agreement.save(update_fields=['consent_verified_at', 'stripe_payment_method_id', 'card_brand', 'card_last4',
                                  'setup_status', 'status', 'setup_message', 'ready_at'])
    payments.audit('autopay.setup_verified', agreement.purchase.sale, None, agreement=str(agreement.pk), setup_status=agreement.setup_status)
    if agreement.collection_engine == 'STRIPE_BILLING' and agreement.setup_status == 'READY':
        from .tasks import provision_billing_subscription
        transaction.on_commit(lambda: provision_billing_subscription.delay(str(agreement.pk)), robust=True)


def expected_object(agreement, installment, attempt, obj, checkout=False):
    meta = autopay.metadata(agreement, installment, attempt.pk)
    amount = obj.get('amount_total') if checkout else obj.get('amount')
    method = obj.get('payment_method') or (obj.get('last_payment_error') or {}).get('payment_method', {})
    if isinstance(method, dict):
        method = method.get('id')
    method_ok = checkout or method == agreement.stripe_payment_method_id or (not method and obj.get('status') in ('requires_payment_method', 'canceled'))
    return (obj.get('customer') == agreement.stripe_customer_id and obj.get('currency') == 'aed'
            and amount == int(installment.amount) * 100
            and obj.get('livemode') is agreement.livemode
            and all(obj.get('metadata', {}).get(k) == v for k, v in meta.items())
            and method_ok)


def process_event(event, record):
    """Called inside the signed provider event's transaction and idempotency lock."""
    kind = event['type']
    obj = event.get('data', {}).get('object', {})
    try:
        attempt_id = uuid.UUID(obj.get('metadata', {}).get('attempt_id', ''))
    except (ValueError, TypeError, AttributeError):
        record.outcome, record.error = 'REJECTED', 'Invalid Autopay attempt reference.'
        return
    attempt = AutopayAttempt.objects.select_related('installment').filter(pk=attempt_id).first()
    if attempt is None:
        record.outcome = 'IGNORED'
        return
    agreement, installment = autopay.lock_installment(attempt.installment_id)
    if installment.position > 0 and agreement.collection_engine == 'STRIPE_BILLING':
        record.outcome = 'IGNORED'
        return  # Billing invoice settlement is the only credit authority.
    attempt = AutopayAttempt.objects.select_for_update().get(pk=attempt.pk)
    payment = installment.payment
    checkout = kind.startswith('checkout.session.')
    if installment.position == 0 and not checkout:
        record.outcome = 'IGNORED'
        return
    if (agreement.livemode != settings.STRIPE_LIVE_MODE or not expected_object(agreement, installment, attempt, obj, checkout)
            or (checkout and (installment.position != 0 or obj.get('id') != attempt.stripe_checkout_id or obj.get('client_reference_id') != str(payment.pk)))
            or (not checkout and attempt.stripe_payment_intent_id and obj.get('id') != attempt.stripe_payment_intent_id)):
        record.outcome, record.error = 'REJECTED', 'Autopay amount, currency, method, environment or linked references do not match.'
        return
    if kind not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded', 'checkout.session.async_payment_failed',
                    'checkout.session.expired', 'payment_intent.succeeded', 'payment_intent.payment_failed',
                    'payment_intent.requires_action', 'payment_intent.processing'):
        record.outcome = 'IGNORED'
        return
    success = (checkout and kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded') and obj.get('payment_status') == 'paid') or (not checkout and kind == 'payment_intent.succeeded' and obj.get('status') == 'succeeded')
    pi_id = obj.get('payment_intent') if checkout else obj.get('id')
    if success:
        if not isinstance(pi_id, str) or not pi_id.startswith('pi_') or (not checkout and obj.get('amount_received') != int(payment.amount) * 100):
            record.outcome, record.error = 'REJECTED', 'A fully paid PaymentIntent is required.'
            return
        if payment.status == 'SUCCEEDED':
            record.outcome = 'DUPLICATE'
            return
        if installment.position > 0 and (not agreement.initial_paid_at or not agreement.purchase.sale.student_id
                or agreement.installments.filter(position__lt=installment.position).exclude(status='PAID').exists()):
            record.outcome, record.error = 'REJECTED', 'An earlier installment remains unpaid; automatic collection needs administrative review.'
            return
        from .payment_models import Payment
        if Payment.objects.filter(stripe_payment_intent=pi_id).exclude(pk=payment.pk).exists():
            record.outcome, record.error = 'REJECTED', 'This PaymentIntent has already been credited.'
            return
        attempt.stripe_payment_intent_id = pi_id
        payments.succeed(payment, provider_id=pi_id)
        installment.status, installment.paid_at = 'PAID', payment.verified_at
        installment.save(update_fields=['status', 'paid_at'])
        autopay.attempt_state(attempt, 'SUCCEEDED')
        if installment.position == 0:
            agreement.initial_paid_at = payment.verified_at
            agreement.save(update_fields=['initial_paid_at'])
            refresh_setup(agreement.pk, obj)
        elif not agreement.installments.exclude(status='PAID').exists():
            agreement.status = 'COMPLETED'
            agreement.save(update_fields=['status'])
        record.outcome = 'PROCESSED'
    elif payment.status == 'SUCCEEDED':
        record.outcome = 'DUPLICATE'
    elif checkout and kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        record.outcome = 'AWAITING_PAYMENT'
    else:
        if isinstance(pi_id, str) and pi_id.startswith('pi_'):
            attempt.stripe_payment_intent_id = pi_id
        error = obj.get('last_payment_error') or {}
        requires_action = kind == 'payment_intent.requires_action' or error.get('code') == 'authentication_required'
        status = 'REQUIRES_CUSTOMER_ACTION' if requires_action else 'PENDING' if kind == 'payment_intent.processing' else 'EXPIRED' if kind.endswith('expired') else 'FAILED'
        autopay.attempt_state(attempt, status, error.get('code', ''))
        installment.status = status
        installment.save(update_fields=['status'])
        payment.status = 'PENDING' if status in ('PENDING', 'REQUIRES_CUSTOMER_ACTION') else status
        payment.save(update_fields=['status'])
        record.outcome = 'PROCESSED'


def submit_attempt(attempt_id):
    """One idempotent provider operation. A business retry is deliberately not scheduled."""
    from .stripe_gateway import client
    attempt = AutopayAttempt.objects.select_related('installment__payment', 'installment__agreement__purchase__sale').get(pk=attempt_id)
    installment, agreement = attempt.installment, attempt.installment.agreement
    if agreement.collection_engine != 'LEGACY_PI':
        return  # Never create a recurring PaymentIntent for a Billing agreement.
    try:
        gateway = client()
        method = as_dict(gateway.v1.payment_methods.retrieve(agreement.stripe_payment_method_id))
        if method.get('customer') != agreement.stripe_customer_id or method.get('type') != 'card' or bool(method.get('livemode')) != agreement.livemode or agreement.livemode != settings.STRIPE_LIVE_MODE:
            raise ValueError('Saved method is no longer reusable for this Customer and Stripe mode.')
        remote = gateway.v1.payment_intents.create({'amount': int(installment.amount) * 100, 'currency': 'aed',
            'customer': agreement.stripe_customer_id, 'payment_method': agreement.stripe_payment_method_id,
            'payment_method_types': ['card'], 'confirm': True, 'off_session': True,
            'metadata': autopay.metadata(agreement, installment, attempt.pk)},
            options={'idempotency_key': f'eduport-autopay-attempt-{attempt.pk}'})
        result = as_dict(remote)
    except stripe.CardError as exc:
        intent = (exc.json_body or {}).get('error', {}).get('payment_intent')
        if not intent:
            _transport_result(attempt_id, 'FAILED', error_code=exc.code or 'card_error')
            return
        result = as_dict(client().v1.payment_intents.retrieve(intent if isinstance(intent, str) else intent['id']))
    except ValueError:
        _transport_result(attempt_id, 'FAILED', error_code='payment_method_unavailable', setup_incomplete=True)
        return
    except stripe.InvalidRequestError as exc:
        _transport_result(attempt_id, 'FAILED', error_code=exc.code or 'invalid_request')
        return
    except (stripe.StripeError, payments.SalesError):
        _transport_result(attempt_id, 'UNKNOWN', error_code='provider_unconfirmed')
        return
    with transaction.atomic():
        agreement, installment = autopay.lock_installment(installment.pk)
        attempt = AutopayAttempt.objects.select_for_update().get(pk=attempt_id)
        if installment.status == 'PAID':
            return
        if not expected_object(agreement, installment, attempt, result):
            _transport_result(attempt_id, 'REQUIRES_RECONCILIATION', error_code='provider_reference_mismatch')
            return
        attempt.stripe_payment_intent_id = result['id']
        error = result.get('last_payment_error') or {}
        if result.get('status') == 'requires_action' or error.get('code') == 'authentication_required':
            status = 'REQUIRES_CUSTOMER_ACTION'
        elif result.get('status') in ('requires_payment_method', 'canceled'):
            status = 'FAILED'
        else:
            # Even an API success waits for its signed webhook before quota.
            status = 'PENDING'
        autopay.attempt_state(attempt, status, error.get('code', ''))
        installment.status = status
        installment.save(update_fields=['status'])
        if status == 'FAILED':
            installment.payment.status = 'FAILED'
            installment.payment.save(update_fields=['status'])


@transaction.atomic
def _transport_result(attempt_id, status, error_code='', setup_incomplete=False):
    attempt = AutopayAttempt.objects.get(pk=attempt_id)
    agreement, installment = autopay.lock_installment(attempt.installment_id)
    attempt = AutopayAttempt.objects.select_for_update().get(pk=attempt_id)
    if installment.status == 'PAID':
        return
    autopay.attempt_state(attempt, status, error_code)
    installment.status = status
    installment.save(update_fields=['status'])
    if status == 'FAILED':
        installment.payment.status = 'FAILED'
        installment.payment.save(update_fields=['status'])
    if setup_incomplete:
        agreement.setup_status, agreement.status = 'INCOMPLETE', 'SETUP_INCOMPLETE'
        agreement.setup_message = 'The saved payment method needs Admin follow-up.'
        agreement.save(update_fields=['setup_status', 'status', 'setup_message'])


def parent_action(token):
    try:
        payload = autopay.signing.loads(token, salt=autopay.ACTION_SALT, max_age=7 * 86400)
    except autopay.signing.BadSignature as exc:
        raise payments.refusal('ACTION_LINK_INVALID', 'This private payment link is invalid or expired. Ask your adviser for a fresh link.', 404) from exc
    attempt = AutopayAttempt.objects.select_related('installment__agreement__purchase').filter(pk=payload.get('attempt')).first()
    if not attempt:
        raise payments.refusal('ACTION_LINK_INVALID', 'This payment link is unavailable.', 404)
    installment, agreement = attempt.installment, attempt.installment.agreement
    result = {'status': installment.status, 'amount': plain(installment.amount), 'currency': 'AED',
        'billing_timezone': agreement.billing_timezone, 'package_amount': plain(agreement.purchase.amount),
        'consent_text': agreement.consent_text, 'terms_url': agreement.terms_url,
        'schedule': [{'position': row.position, 'due_at': row.due_at.isoformat() if row.due_at else None,
                      'amount': plain(row.amount), 'classes': plain(row.classes)} for row in agreement.installments.all()],
        'needs_action': False}
    if (agreement.collection_engine == 'LEGACY_PI' and installment.position > 0
            and attempt.status == 'REQUIRES_CUSTOMER_ACTION' and installment.status != 'PAID'):
        if agreement.livemode != settings.STRIPE_LIVE_MODE or not autopay.configured():
            raise payments.refusal('AUTOPAY_NOT_CONFIGURED', 'This agreement’s Stripe authentication configuration needs administrative review.', 503)
        from .stripe_gateway import client
        try:
            intent = as_dict(client().v1.payment_intents.retrieve(attempt.stripe_payment_intent_id))
        except stripe.StripeError as exc:
            raise payments.refusal('STRIPE_UNAVAILABLE', 'Stripe authentication is temporarily unavailable.', 503) from exc
        if not expected_object(agreement, installment, attempt, intent):
            raise payments.refusal('ACTION_LINK_INVALID', 'This collection needs administrative review.', 409)
        result.update(needs_action=True, client_secret=intent['client_secret'], payment_method_id=agreement.stripe_payment_method_id,
                      publishable_key=settings.STRIPE_PUBLISHABLE_KEY)
    return result
