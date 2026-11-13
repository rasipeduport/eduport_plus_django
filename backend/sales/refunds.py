"""Refund and dispute tracking from signed Stripe events.

Each event re-reads Stripe's canonical objects, so redelivered or out-of-order
events converge on the same rows. Nothing here edits a Payment, changes class
quota or alters a Sale's agreed amount: those need an approved business policy.
"""
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import review
from .ledger_models import Dispute, Refund, ReviewKind, from_minor
from .payment_models import Payment

REFUND_EVENTS = {'charge.refunded', 'refund.created', 'refund.updated', 'refund.failed'}
DISPUTE_EVENTS = {'charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed',
                  'charge.dispute.funds_withdrawn', 'charge.dispute.funds_reinstated'}


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


def identifier(value):
    return value.get('id') if isinstance(value, dict) else (value or '')


def instant(value):
    return datetime.fromtimestamp(value, dt_timezone.utc) if value else None


def find_payment(intent_id, charge_id):
    """Only Django's own provider references identify a payment."""
    match = Q(pk__in=[])
    if intent_id:
        match |= Q(stripe_payment_intent=intent_id)
    if charge_id:
        match |= Q(stripe_charge_id=charge_id)
    found = list(Payment.objects.filter(match, method='STRIPE', status='SUCCEEDED')[:2])
    return found[0] if len(found) == 1 else None


def process(event, record):
    from .stripe_gateway import client
    obj = event['data']['object']
    gateway = client()
    if event['type'] in REFUND_EVENTS:
        charge_id = obj['id'] if event['type'] == 'charge.refunded' else identifier(obj.get('charge'))
        refunds = [data(row) for row in gateway.v1.refunds.list({'charge': charge_id, 'limit': 100}).auto_paging_iter()] \
            if charge_id else [data(gateway.v1.refunds.retrieve(obj['id']))]
        matched = False
        for refund in refunds:
            matched = _refund(refund, record) or matched
        if not matched:
            review.record(ReviewKind.UNMATCHED_REFUND, obj, record, 'Refund of a payment Django did not create or cannot identify.')
        record.outcome = 'PROCESSED' if matched else 'IGNORED'
        return
    dispute = data(gateway.v1.disputes.retrieve(obj['id']))
    if _dispute(dispute):
        record.outcome = 'PROCESSED'
    else:
        review.record(ReviewKind.UNMATCHED_DISPUTE, dispute, record, 'Dispute of a payment Django did not create or cannot identify.')
        record.outcome = 'IGNORED'


@transaction.atomic
def _refund(refund, record):
    payment = find_payment(identifier(refund.get('payment_intent')), identifier(refund.get('charge')))
    if payment is None or not refund.get('amount'):
        return False
    Payment.objects.select_for_update().get(pk=payment.pk)  # Serialize with other events for this payment.
    values = {'payment': payment, 'stripe_charge_id': identifier(refund.get('charge')),
              'stripe_payment_intent_id': identifier(refund.get('payment_intent')),
              'amount': from_minor(refund['amount'], refund.get('currency')), 'currency': (refund.get('currency') or '').upper(),
              'status': refund.get('status') or '', 'reason': refund.get('reason') or '',
              'failure_reason': refund.get('failure_reason') or '', 'stripe_created_at': instant(refund.get('created'))}
    existing = Refund.objects.select_for_update().filter(stripe_refund_id=refund['id']).first()
    if existing is None:
        Refund.objects.create(stripe_refund_id=refund['id'], **values)
    else:
        if existing.payment_id != payment.pk:
            raise ValueError('A refund cannot move to another payment.')
        changed = [field for field in ('status', 'reason', 'failure_reason') if getattr(existing, field) != values[field]]
        for field in changed:
            setattr(existing, field, values[field])
        if changed:
            existing.save(update_fields=[*changed, 'updated_at'])
    return True


@transaction.atomic
def _dispute(dispute):
    payment = find_payment(identifier(dispute.get('payment_intent')), identifier(dispute.get('charge')))
    if payment is None:
        return False
    Payment.objects.select_for_update().get(pk=payment.pk)
    closed = dispute.get('status') in ('won', 'lost', 'warning_closed', 'prevented')
    values = {'status': dispute.get('status') or '', 'reason': dispute.get('reason') or '',
              'evidence_due_by': instant((dispute.get('evidence_details') or {}).get('due_by'))}
    existing = Dispute.objects.select_for_update().filter(stripe_dispute_id=dispute['id']).first()
    if existing is None:
        Dispute.objects.create(stripe_dispute_id=dispute['id'], payment=payment, stripe_charge_id=identifier(dispute.get('charge')),
                               stripe_payment_intent_id=identifier(dispute.get('payment_intent')),
                               amount=from_minor(dispute.get('amount') or 0, dispute.get('currency')),
                               currency=(dispute.get('currency') or '').upper(), stripe_created_at=instant(dispute.get('created')),
                               closed_at=timezone.now() if closed else None, **values)
        return True
    if existing.payment_id != payment.pk:
        raise ValueError('A dispute cannot move to another payment.')
    changed = [field for field, value in values.items() if getattr(existing, field) != value]
    for field in changed:
        setattr(existing, field, values[field])
    if closed and not existing.closed_at:
        existing.closed_at = timezone.now()
        changed.append('closed_at')
    if changed:
        existing.save(update_fields=[*changed, 'updated_at'])
    return True


def money(value):
    return f'{value.normalize():f}' if value is not None else None


def payment_extras(payment):
    return {
        'refunds': [{'id': row.stripe_refund_id, 'amount': money(row.amount), 'currency': row.currency, 'status': row.status,
                     'reason': row.reason, 'created_at': row.stripe_created_at.isoformat()} for row in payment.refunds.all()],
        'disputes': [{'id': row.stripe_dispute_id, 'amount': money(row.amount), 'currency': row.currency, 'status': row.status,
                      'reason': row.reason, 'evidence_due_by': row.evidence_due_by.isoformat() if row.evidence_due_by else None}
                     for row in payment.disputes.all()],
    }
