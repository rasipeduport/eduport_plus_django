"""
Payments to tutors: an administrator records here a payment already made to a
tutor outside Eduport Plus -- by account transfer or UPI, in rupees. Nothing
here moves money.

A payment (record_payment):
- is at most what the tutor is owed: their earnings less what has been paid
  them, read under the tutor's lock, so two payments made at once can never
  pay more than that together. A part of it is fine; nothing is paid before
  pricing has started, or to a tutor owed nothing (or overpaid).
- is recorded once: the recording dialog's own ``request_id`` makes a
  repeated request answer with the payment it already recorded; the same id
  with anything else is refused.
- has a reference no other payment still counting has -- compared by its
  letters and digits alone, whatever the case, spaces or punctuation; and the
  same amount to the same tutor on the same day must be confirmed as a second
  payment.
- is never edited or deleted. A payment recorded by mistake is voided, with a
  reason (void_payment): it stays in the history, no longer counts as paid,
  and its reference is free again. Voiding is final.
"""
import re
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from activity.utils import log_activity

from .eligibility import activated_at
from .models import EarningEntry, PaymentMethod, TutorEarningsPricing, TutorPayment
from .values import (
    INDIA,
    NOTES_MAX_LENGTH,
    REFERENCE_MAX_LENGTH,
    EarningsError,
    india_today,
    lock_tutor,
    parse_date,
    reason as clean_reason,
    rupees,
    text,
)

NOT_FOUND = 'PAYMENT_NOT_FOUND'
PRICING_NOT_STARTED = 'PRICING_NOT_STARTED'
NOTHING_OUTSTANDING = 'NOTHING_OUTSTANDING'
EXCEEDS_OUTSTANDING = 'EXCEEDS_OUTSTANDING'
DUPLICATE_REFERENCE = 'DUPLICATE_REFERENCE'
POSSIBLE_DUPLICATE = 'POSSIBLE_DUPLICATE'
IDEMPOTENCY_CONFLICT = 'IDEMPOTENCY_CONFLICT'
ALREADY_VOIDED = 'ALREADY_VOIDED'
INVALID = 'INVALID_INPUT'


def reference_key(reference):
    """A reference as compared: its letters and digits alone, upper-cased."""
    return re.sub(r'[^A-Z0-9]', '', (reference or '').upper())


def earned_total(tutor_id):
    return EarningEntry.objects.filter(tutor_id=tutor_id).aggregate(total=Sum('amount'))['total'] or 0


def paid_total(tutor_id):
    return (TutorPayment.objects.filter(tutor_id=tutor_id, voided_at__isnull=True)
            .aggregate(total=Sum('amount'))['total'] or 0)


def outstanding(tutor_id):
    """What ``tutor_id`` is owed: everything earned less every payment that counts (negative: overpaid)."""
    return earned_total(tutor_id) - paid_total(tutor_id)


def _request_id(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise EarningsError(INVALID, 'The request is missing its key. Reload and try again.', field='request_id') from None


def _same(payment, tutor, amount, paid_on, method, reference, notes):
    return (payment.tutor_id == tutor.pk and payment.amount == amount and payment.paid_on == paid_on
            and payment.method == method and payment.reference == reference and payment.notes == notes)


def _clean(data):
    amount = rupees(data.get('amount'), 'amount')
    paid_on = parse_date(data.get('paid_on'), 'paid_on')
    if paid_on > india_today():
        raise EarningsError(INVALID, 'The payment date cannot be in the future.', field='paid_on')
    since = activated_at()
    if since is not None and paid_on < timezone.localtime(since, INDIA).date():
        raise EarningsError(INVALID, 'The payment date cannot be before Tutor Earnings started.', field='paid_on')
    method = data.get('method')
    if method not in PaymentMethod.values:
        raise EarningsError(INVALID, 'Choose Account Transfer or UPI.', field='method')
    reference = text(data.get('reference'), 'reference', max_length=REFERENCE_MAX_LENGTH, required=True,
                     message='Enter the transaction reference: the bank UTR or the UPI transaction ID.')
    key = reference_key(reference)
    if not key:
        raise EarningsError(INVALID, 'The reference needs letters or digits.', field='reference')
    notes = text(data.get('notes'), 'notes', max_length=NOTES_MAX_LENGTH, required=False, message='')
    return amount, paid_on, method, reference, key, notes


def record_payment(actor, tutor, data, request=None):
    """
    Record a payment to ``tutor`` from ``data``: request_id, amount, paid_on
    (YYYY-MM-DD), method, reference, notes, and confirm_duplicate. Returns
    (payment, created) -- created false when the same request was recorded before.
    """
    request_id = _request_id(data.get('request_id'))
    amount, paid_on, method, reference, key, notes = _clean(data)
    confirmed = data.get('confirm_duplicate') is True
    with transaction.atomic():
        lock_tutor(tutor.pk)
        earlier = TutorPayment.objects.filter(request_id=request_id).first()
        if earlier is not None:
            if _same(earlier, tutor, amount, paid_on, method, reference, notes):
                return earlier, False
            raise EarningsError(IDEMPOTENCY_CONFLICT, 'This request was already used for another payment. Reload and try again.',
                                status=409)
        if not TutorEarningsPricing.objects.exists():
            raise EarningsError(PRICING_NOT_STARTED, 'Pricing has not started yet, so nothing is owed.', status=409)
        balance = outstanding(tutor.pk)
        if balance <= 0:
            message = (f'{tutor.full_name or "This tutor"} is overpaid by ₹{-balance:,.2f}.' if balance < 0
                       else f'{tutor.full_name or "This tutor"} is owed nothing.')
            raise EarningsError(NOTHING_OUTSTANDING, message, status=409, outstanding=str(balance))
        if amount > balance:
            raise EarningsError(EXCEEDS_OUTSTANDING, f'The payment is more than the ₹{balance:,.2f} outstanding.',
                                status=409, outstanding=str(balance), field='amount')
        clash = TutorPayment.objects.filter(reference_key=key, voided_at__isnull=True).select_related('tutor').first()
        if clash is not None:
            raise EarningsError(
                DUPLICATE_REFERENCE,
                f'This reference is already recorded for a payment to {clash.tutor.full_name or clash.tutor.email} '
                f'on {clash.paid_on:%d %b %Y}.',
                status=409, field='reference', payment_id=str(clash.pk),
            )
        if not confirmed:
            twin = (TutorPayment.objects.filter(tutor=tutor, amount=amount, paid_on=paid_on, voided_at__isnull=True)
                    .select_related('recorded_by').first())
            if twin is not None:
                raise EarningsError(
                    POSSIBLE_DUPLICATE,
                    f'A payment of ₹{amount:,.2f} to {tutor.full_name or tutor.email} dated {paid_on:%d %b %Y} '
                    f'was already recorded by {twin.recorded_by.full_name or twin.recorded_by.email}.',
                    status=409, payment_id=str(twin.pk), recorded_at=twin.recorded_at.isoformat(),
                )
        try:
            with transaction.atomic():
                payment = TutorPayment.objects.create(
                    request_id=request_id, tutor=tutor, amount=amount, paid_on=paid_on, method=method,
                    reference=reference, reference_key=key, notes=notes, recorded_by=actor,
                )
        except IntegrityError:
            # A payment with this reference -- to another tutor -- was recorded at the same moment.
            raise EarningsError(DUPLICATE_REFERENCE, 'This reference was just recorded for another payment.',
                                status=409, field='reference') from None
    log_activity(
        action='earnings.record_payment',
        entity_type='tutor_payment',
        entity_id=str(payment.pk),
        entity_label=tutor.full_name or tutor.email,
        changes={'paid': {'old': None, 'new': str(amount)}},
        context={'tutor_id': str(tutor.pk), 'paid_on': paid_on.isoformat(), 'method': method,
                 'reference': reference, 'outstanding_before': str(balance)},
        request=request,
        actor=actor,
    )
    return payment, True


def void_payment(actor, payment_id, data, request=None):
    """Void the payment ``payment_id`` for ``data['reason']``; returns it."""
    why = clean_reason(data.get('reason'))
    payment = TutorPayment.objects.filter(pk=payment_id).first()
    if payment is None:
        raise EarningsError(NOT_FOUND, 'No such payment.', status=404)
    with transaction.atomic():
        lock_tutor(payment.tutor_id)
        payment = TutorPayment.objects.select_for_update().select_related('tutor').get(pk=payment.pk)
        if payment.voided_at is not None:
            raise EarningsError(ALREADY_VOIDED, 'This payment is already voided.', status=409)
        payment.voided_at = timezone.now()
        payment.voided_by = actor
        payment.void_reason = why
        payment.save(update_fields=['voided_at', 'voided_by', 'void_reason'])
    log_activity(
        action='earnings.void_payment',
        entity_type='tutor_payment',
        entity_id=str(payment.pk),
        entity_label=payment.tutor.full_name or payment.tutor.email,
        changes={'paid': {'old': str(payment.amount), 'new': '0'}},
        context={'tutor_id': str(payment.tutor_id), 'paid_on': payment.paid_on.isoformat(),
                 'reference': payment.reference, 'reason': why},
        request=request,
        actor=actor,
    )
    return payment
