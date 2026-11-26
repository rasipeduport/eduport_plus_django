"""Additional hours paid through Stripe Checkout.

An administrator or the student's own mentor generates a Stripe Checkout
Session for part or all of what an allocation still owes; the parent pays on
Stripe's page. Nothing is recorded on the way back from Checkout: only Stripe's
signed webhook (stripe_gateway.process_event, routed here by this module's own
metadata key) records the payment -- once, whatever Stripe re-delivers -- and a
payment never changes the student's quota.

Each attempt (AdditionalHoursCheckout) is durable before Stripe is called: its
request is frozen and created with its own idempotency key, so a lost response
is recovered -- by retrying the same request, or by the webhook naming it --
and never duplicated. An allocation has at most one live link; while it is
live, other payments, amount changes, waiving and withdrawing are refused
(sales.additional_hours), so a paid link always fits what is owed. A payment
Stripe confirms that cannot be applied all the same -- the hours were waived or
withdrawn, or it is more than is still due -- is never recorded: its attempt is
marked for review and the administrators' Stripe review queue gets an item, so
the money is refunded or resolved by a person.

The regular tuition, Autopay, refund and Checkout flows are untouched: this
reuses their Stripe client, Customer, product and metadata helpers only.
"""
import copy
import uuid
from datetime import timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from activity.utils import log_activity

from . import additional_hours as hours
from .account_models import StudentAccount
from .allocation_models import (LIVE_CHECKOUT, STRIPE, AdditionalHoursAllocation, AdditionalHoursCheckout, AdditionalHoursPayment,
                                CheckoutStatus)
from .payment_models import StripeCustomer
from .pricing import plain

# The metadata key that routes a Checkout Session's events here (stripe_gateway.process_event).
METADATA_KEY = 'additional_hours_checkout_id'
SETTLING_EVENTS = ('checkout.session.completed', 'checkout.session.async_payment_succeeded')
CLOSING_EVENTS = {'checkout.session.expired': CheckoutStatus.EXPIRED, 'checkout.session.async_payment_failed': CheckoutStatus.FAILED}
CREATING = ('PREPARED', 'SUBMITTING', 'UNKNOWN')
# Stripe keeps an idempotency key for 24 hours; a request older than this is never re-sent.
IDEMPOTENCY_WINDOW = timedelta(hours=23)

refusal = hours.refusal


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


def live_checkout(allocation):
    """The allocation's live link, or one Stripe may still be creating, if any."""
    return allocation.checkouts.filter(status__in=LIVE_CHECKOUT).first()


def _lock(allocation_id):
    """The student's account, then the allocation: the lock order every additional-hours change takes."""
    student_id = AdditionalHoursAllocation.objects.values_list('student_id', flat=True).get(pk=allocation_id)
    StudentAccount.objects.select_for_update().filter(student_id=student_id).first()
    return AdditionalHoursAllocation.objects.select_for_update(of=('self',)).select_related('student').get(pk=allocation_id)


def _audit(action, allocation, actor, request=None, changes=None, **context):
    log_activity(action=action, entity_type='additional_hours', entity_id=allocation.pk, entity_label=allocation.reference,
                 student=allocation.student, changes=changes, context=context, request=request, actor=actor)


def _request(checkout_id, allocation, account, amount):
    """The Checkout request, frozen once: AED, card only, on the student's own Customer, named for these hours."""
    from .checkout import PAYMENT_METHOD_TYPES, WALLET_OPTIONS, account_metadata
    from .customers import PRODUCTS
    meta = {METADATA_KEY: str(checkout_id), 'additional_hours_id': str(allocation.pk), 'additional_hours_ref': allocation.reference}
    meta.update(account_metadata(account))
    refs = f'{account.reference} · {allocation.student.student_code}'
    description = (f'Eduport Plus additional hours — {account.student_name} ({refs}) · {plain(allocation.hours)} hrs · '
                   f'{allocation.reference}')
    message = (f'You are paying for {account.student_name} ({refs}): Eduport Plus additional hours, AED {plain(amount)} of '
               f'{allocation.reference}. Student and payment details are managed by Eduport Plus.')
    hub = settings.HUB_URL.rstrip('/')
    return copy.deepcopy({
        'mode': 'payment', 'client_reference_id': str(checkout_id),
        'allowed_payment_method_types': list(PAYMENT_METHOD_TYPES), 'wallet_options': WALLET_OPTIONS,
        'line_items': [{'price_data': {'currency': 'aed', 'unit_amount': int(amount) * 100, 'product': PRODUCTS['TUITION'][0]},
                        'quantity': 1}],
        'metadata': meta, 'payment_intent_data': {'metadata': meta, 'description': description[:1000]},
        'custom_text': {'submit': {'message': message[:1200]}},
        # The same return page as every Checkout: it never says the payment succeeded.
        'success_url': f'{hub}/payment-return?result=submitted', 'cancel_url': f'{hub}/payment-return?result=cancelled',
    })


def generate_link(actor, allocation_id, data, request=None):
    """A Stripe Checkout link for ``data['amount']`` (all that is still due when absent). Returns (checkout, created)."""
    from .customers import prepared_mapping
    from .payments import stripe_configured
    hours.visible_allocation(actor, allocation_id, request)  # Refuse before any lock; checked again below.
    with transaction.atomic():
        allocation = _lock(allocation_id)
        hours.visible_allocation(actor, allocation_id, request)  # Still theirs, under the lock.
        existing = AdditionalHoursCheckout.objects.filter(pk=data['request_id']).first()
        if existing is not None:
            if (existing.allocation_id != allocation.pk or existing.created_by_id != actor.pk
                    or (data.get('amount') is not None and existing.amount != data['amount'])):
                raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for another payment link.', 409)
            checkout, created = existing, False
        else:
            if allocation.waived_at or allocation.withdrawn_at:
                raise refusal('ALLOCATION_CLOSED', 'These hours are waived or withdrawn: they take no further payment.')
            remaining = allocation.amount - hours.paid_amount(allocation)
            if remaining <= 0:
                raise refusal('ALLOCATION_PAID', 'These hours are already paid in full.')
            amount = data.get('amount') or remaining
            if amount > remaining:
                raise refusal('EXCEEDS_OUTSTANDING', f'The link can be for at most the AED {plain(remaining)} still due.',
                              409, outstanding=plain(remaining), field='amount')
            open_link = live_checkout(allocation)
            if open_link is not None:
                raise refusal('STRIPE_LINK_OPEN', 'A Stripe payment link is already open for these hours. Share it, or expire it '
                                                  'before generating another.', 409, checkout_id=str(open_link.pk))
            if not stripe_configured():
                raise refusal('STRIPE_NOT_CONFIGURED', 'Stripe payments are not configured.', 503)
            account = StudentAccount.objects.filter(student_id=allocation.student_id).first()
            if account is None:
                raise refusal('NOT_ELIGIBLE', 'This student has no Eduport Plus payment account to bill.')
            prepared_mapping(account)  # The student's own Stripe Customer row for this mode, as every Checkout uses.
            checkout_id = data['request_id']
            checkout = AdditionalHoursCheckout.objects.create(
                id=checkout_id, allocation=allocation, amount=amount, livemode=settings.STRIPE_LIVE_MODE,
                request=_request(checkout_id, allocation, account, amount),
                idempotency_key=f'eduport-additional-hours-checkout-{checkout_id}', created_by=actor)
            _audit('additional_hours.stripe_link', allocation, actor, request, checkout=str(checkout.pk), amount=plain(amount))
            created = True
    # No provider call runs before the attempt's origin commits.
    return fulfill(checkout.pk), created


def _owned_customers(checkout):
    return set(StripeCustomer.objects.filter(account__student_id=checkout.allocation.student_id, livemode=checkout.livemode)
               .exclude(customer_id=None).values_list('customer_id', flat=True))


def _validate(checkout, remote, owned):
    """Whether Stripe's Session is this attempt's: its Customer, amount, currency, mode and references."""
    from .customers import same_metadata
    request = checkout.request
    if (not remote.get('id') or remote.get('customer') not in owned or bool(remote.get('livemode')) != checkout.livemode
            or remote.get('mode') != 'payment' or (remote.get('currency') or '').lower() != 'aed'
            or remote.get('client_reference_id') != str(checkout.pk)
            or remote.get('amount_total') != request['line_items'][0]['price_data']['unit_amount']
            or not same_metadata(remote.get('metadata'), request['metadata'])):
        raise ValueError('The Checkout Session differs from its request, amount, currency or student Customer.')


def bind(checkout_id, remote):
    """Fix Stripe's Session to its attempt -- once -- and open the link."""
    with transaction.atomic():
        checkout = AdditionalHoursCheckout.objects.select_related('allocation').get(pk=checkout_id)
        _lock(checkout.allocation_id)
        checkout = AdditionalHoursCheckout.objects.select_for_update(of=('self',)).select_related('allocation').get(pk=checkout_id)
        _validate(checkout, remote, _owned_customers(checkout))
        if checkout.stripe_checkout_id and checkout.stripe_checkout_id != remote['id']:
            raise ValueError('Another Session is already bound to this Checkout attempt.')
        if not checkout.stripe_checkout_id:
            checkout.stripe_checkout_id = remote['id']
            checkout.checkout_url = remote.get('url') or ''
            checkout.stripe_customer_id = remote['customer']
        if checkout.status in CREATING:
            checkout.status, checkout.message = CheckoutStatus.OPEN, ''
        checkout.save(update_fields=['stripe_checkout_id', 'checkout_url', 'stripe_customer_id', 'status', 'message'])
        return checkout


def _mark(checkout_id, status, message):
    AdditionalHoursCheckout.objects.filter(pk=checkout_id, status__in=CREATING).update(status=status, message=message[:255])


def fulfill(checkout_id):
    """Create -- or find again -- the attempt's Session at Stripe, with its frozen request and key."""
    from .customers import customer_for, ensure_product
    from .stripe_gateway import client, is_definitive_rejection
    checkout = AdditionalHoursCheckout.objects.select_related('allocation').get(pk=checkout_id)
    if checkout.livemode != settings.STRIPE_LIVE_MODE:
        raise refusal('STRIPE_MODE_MISMATCH', 'This link belongs to another Stripe environment.', 409)
    if checkout.status not in CREATING:
        return checkout
    try:
        gateway = client()
        account_id = StudentAccount.objects.values_list('pk', flat=True).get(student_id=checkout.allocation.student_id)
        customer_id = customer_for(account_id, gateway, checkout.livemode)
        ensure_product(gateway, 'TUITION')
        matches = [data(row) for row in gateway.v1.checkout.sessions.list({'customer': customer_id, 'limit': 100}).auto_paging_iter()
                   if (data(row).get('metadata') or {}).get(METADATA_KEY) == str(checkout.pk)]
        if len(matches) > 1:
            raise ValueError('Several Sessions match this link. Review them in Stripe.')
        if matches:
            return bind(checkout.pk, matches[0])
        with transaction.atomic():
            allocation = _lock(checkout.allocation_id)
            checkout = AdditionalHoursCheckout.objects.select_for_update(of=('self',)).select_related('allocation').get(pk=checkout_id)
            if checkout.status not in CREATING:
                return checkout
            if (allocation.waived_at or allocation.withdrawn_at
                    or checkout.amount > allocation.amount - hours.paid_amount(allocation)):
                raise ValueError('The hours no longer owe this amount. No link was created.')
            if checkout.started_at and checkout.started_at < timezone.now() - IDEMPOTENCY_WINDOW:
                raise ValueError('This link was never confirmed by Stripe within its safe window. No new link was created.')
            checkout.started_at = checkout.started_at or timezone.now()
            checkout.status = CheckoutStatus.SUBMITTING
            checkout.save(update_fields=['started_at', 'status'])
        remote = data(gateway.v1.checkout.sessions.create({**checkout.request, 'customer': customer_id},
                                                          options={'idempotency_key': checkout.idempotency_key}))
        return bind(checkout.pk, remote)
    except ValueError as exc:
        _mark(checkout_id, CheckoutStatus.REQUIRES_REVIEW, str(exc))
        raise refusal('CHECKOUT_REVIEW_REQUIRED', str(exc), 409) from exc
    except stripe.InvalidRequestError as exc:
        if not is_definitive_rejection(exc):
            _mark(checkout_id, CheckoutStatus.UNKNOWN, 'Stripe has not confirmed this link yet. Try again to recover it.')
            raise refusal('STRIPE_UNAVAILABLE', 'Stripe has not confirmed the link yet. Try again: the same link is recovered, '
                                                'never a second one.', 503) from exc
        _mark(checkout_id, CheckoutStatus.FAILED, 'Stripe rejected this link.')
        raise refusal('STRIPE_CHECKOUT_REJECTED', 'Stripe rejected the payment link. Check the Stripe configuration.', 409) from exc
    except stripe.StripeError as exc:
        _mark(checkout_id, CheckoutStatus.UNKNOWN, 'Stripe has not confirmed this link yet. Try again to recover it.')
        raise refusal('STRIPE_UNAVAILABLE', 'Stripe has not confirmed the link yet. Try again: the same link is recovered, '
                                            'never a second one.', 503) from exc


def expire_link(actor, allocation_id, checkout_id, request=None):
    """Close an unpaid link at Stripe first; only Stripe's confirmation closes it here."""
    from .stripe_gateway import client
    hours.visible_allocation(actor, allocation_id, request)
    with transaction.atomic():
        allocation = _lock(allocation_id)
        checkout = allocation.checkouts.select_for_update().filter(pk=checkout_id).first()
        if checkout is None:
            raise refusal('NOT_FOUND', 'No such payment link.', 404)
        if checkout.status != CheckoutStatus.OPEN:
            raise refusal('CHECKOUT_NOT_OPEN', 'Only an open, unpaid link can be expired.', 409)
        try:
            client().v1.checkout.sessions.expire(checkout.stripe_checkout_id)
        except stripe.StripeError as exc:
            raise refusal('STRIPE_UNAVAILABLE', 'Stripe could not confirm the expiry, so the link stays open. If the parent has '
                                                'paid already, the payment is recorded when Stripe confirms it.', 503) from exc
        checkout.status, checkout.closed_at = CheckoutStatus.EXPIRED, timezone.now()
        checkout.message = f'Expired by {actor.full_name or actor.username}.'[:255]
        checkout.save(update_fields=['status', 'closed_at', 'message'])
        _audit('additional_hours.stripe_link_expire', allocation, actor, request, checkout=str(checkout.pk),
               amount=plain(checkout.amount))
    return checkout


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def process_event(event, record):
    """A signed Stripe event about one of these links (stripe_gateway.process_event routes it; it holds the event's lock)."""
    from . import review
    from .ledger_models import ReviewKind
    from .stripe_gateway import checkout_evidence
    event_type, obj = event['type'], event.get('data', {}).get('object', {})
    checkout_id = _uuid((obj.get('metadata') or {}).get(METADATA_KEY))
    checkout = AdditionalHoursCheckout.objects.filter(pk=checkout_id).first() if checkout_id else None
    if checkout is None or checkout.livemode != settings.STRIPE_LIVE_MODE:
        record.outcome, record.error = 'REJECTED', 'The Checkout Session names additional hours Django has no link for.'
        return
    if checkout.status in CREATING:
        try:
            bind(checkout.pk, obj)  # A lost creation response, recovered from the signed event.
        except ValueError as exc:
            record.outcome, record.error = 'REJECTED', str(exc)[:255]
            return
    allocation = _lock(checkout.allocation_id)
    checkout = AdditionalHoursCheckout.objects.select_for_update(of=('self',)).select_related('allocation').get(pk=checkout.pk)
    try:
        _validate(checkout, obj, _owned_customers(checkout))
        if obj['id'] != checkout.stripe_checkout_id:
            raise ValueError('The Session is not the one bound to this link.')
    except ValueError as exc:
        record.outcome, record.error = 'REJECTED', str(exc)[:255]
        return
    if event_type in CLOSING_EVENTS:
        if checkout.status in LIVE_CHECKOUT:
            checkout.status, checkout.closed_at = CLOSING_EVENTS[event_type], timezone.now()
            checkout.save(update_fields=['status', 'closed_at'])
            record.outcome = 'PROCESSED'
        else:
            record.outcome = 'DUPLICATE'
        return
    if event_type not in SETTLING_EVENTS:
        record.outcome = 'IGNORED'
        return
    if obj.get('payment_status') != 'paid':
        record.outcome = 'AWAITING_PAYMENT'
        return
    intent = obj.get('payment_intent')
    if not isinstance(intent, str) or not intent.startswith('pi_'):
        record.outcome, record.error = 'REJECTED', 'A successful PaymentIntent reference is required.'
        return
    if checkout.status in (CheckoutStatus.PAID, CheckoutStatus.REQUIRES_REVIEW) and checkout.stripe_payment_intent_id == intent:
        record.outcome = 'DUPLICATE'
        return
    if AdditionalHoursPayment.objects.filter(stripe_payment_intent_id=intent).exists():
        record.outcome = 'DUPLICATE'
        return
    remaining = allocation.amount - hours.paid_amount(allocation)
    problem = ('the hours were withdrawn' if allocation.withdrawn_at else 'what was still due was waived' if allocation.waived_at
               else f'only AED {plain(max(remaining, 0))} was still due' if checkout.amount > remaining
               else 'the link was no longer open' if checkout.status != CheckoutStatus.OPEN else None)
    if problem:
        # Never applied, never dropped: an administrator refunds or resolves it.
        message = f'Paid at Stripe ({intent}) after {problem}: not recorded. Refund or resolve it in Stripe.'
        checkout.status, checkout.message, checkout.closed_at = CheckoutStatus.REQUIRES_REVIEW, message[:255], timezone.now()
        checkout.stripe_payment_intent_id = checkout.stripe_payment_intent_id or intent
        checkout.save(update_fields=['status', 'message', 'closed_at', 'stripe_payment_intent_id'])
        review.record(ReviewKind.INCONSISTENT, obj, record, f'Additional hours {allocation.reference}: {message}')
        _audit('additional_hours.stripe_review', allocation, None, checkout=str(checkout.pk), amount=plain(checkout.amount),
               payment_intent=intent, reason=problem)
        record.outcome, record.error = 'REVIEW', message[:255]
        return
    charge_id, payer = checkout_evidence(obj)
    checkout.status, checkout.stripe_payment_intent_id, checkout.closed_at = CheckoutStatus.PAID, intent, timezone.now()
    checkout.save(update_fields=['status', 'stripe_payment_intent_id', 'closed_at'])
    payment = AdditionalHoursPayment.objects.create(
        request_id=uuid.uuid5(checkout.pk, 'payment'), allocation=allocation, amount=checkout.amount, method=STRIPE,
        payment_date=timezone.localdate(), transaction_reference=intent, reference_key=hours.reference_key(intent),
        recorded_by=checkout.created_by, checkout=checkout, stripe_checkout_id=checkout.stripe_checkout_id,
        stripe_payment_intent_id=intent, stripe_charge_id=charge_id, payer_details=payer)
    # The quota is never touched: the hours were added when the allocation was.
    _audit('additional_hours.payment_record', allocation, None,
           changes={'outstanding': {'old': plain(remaining), 'new': plain(remaining - payment.amount)}},
           payment=str(payment.pk), amount=plain(payment.amount), method=STRIPE, payment_date=payment.payment_date.isoformat(),
           reference=intent, checkout=str(checkout.pk))
    record.outcome = 'PROCESSED'
