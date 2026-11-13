"""Review queue for Stripe activity Django cannot attribute or validate.

Items are never credited. Resolving one either dismisses it with a reason or
links it to a student account as history; neither creates a Payment, moves
money between students or changes class quota.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from activity.utils import log_activity
from .account_models import StudentAccount
from .ledger_models import ReviewKind, StripeReviewItem, from_minor
from .student_accounts import is_admin, refusal


def _identifier(value):
    return value.get('id') if isinstance(value, dict) else (value or '')


def record(kind, obj, event=None, summary='', source='WEBHOOK'):
    """Queue one item per (kind, object). Re-delivery and re-reconciliation add nothing."""
    obj = obj or {}
    object_id = obj.get('id') or ''
    amount = obj.get('amount_total', obj.get('amount_paid', obj.get('amount')))
    currency = obj.get('currency') or ''
    if object_id and StripeReviewItem.objects.filter(kind=kind, object_id=object_id).exists():
        return None
    try:
        with transaction.atomic():
            return StripeReviewItem.objects.create(
                event=event if event is not None and not StripeReviewItem.objects.filter(event=event).exists() else None,
                source=source, kind=kind, object_type=obj.get('object') or '', object_id=object_id,
                customer_id=_identifier(obj.get('customer')), payment_link_id=_identifier(obj.get('payment_link')),
                amount=from_minor(amount, currency) if isinstance(amount, int) and currency else None,
                currency=currency.upper()[:3], livemode=bool(obj.get('livemode')), summary=summary[:255])
    except IntegrityError:
        return None  # A concurrent delivery queued it first.


def checkout_kind(obj):
    return ReviewKind.PAYMENT_LINK_PAYMENT if obj.get('payment_link') else ReviewKind.UNMATCHED_CHECKOUT


def item_data(item):
    return {'id': str(item.pk), 'kind': item.kind, 'kind_label': item.get_kind_display(), 'source': item.source,
            'object_type': item.object_type, 'object_id': item.object_id, 'customer_id': item.customer_id or None,
            'payment_link_id': item.payment_link_id or None,
            'amount': f'{item.amount.normalize():f}' if item.amount is not None else None, 'currency': item.currency or None,
            'livemode': item.livemode, 'summary': item.summary, 'status': item.status,
            'event_id': item.event_id, 'event_type': item.event.event_type if item.event_id else None,
            'account': {'id': str(item.account_id), 'reference': item.account.reference, 'student_name': item.account.student_name}
                       if item.account_id else None,
            'resolution_note': item.resolution_note,
            'resolved_by': (item.resolved_by.full_name or item.resolved_by.username) if item.resolved_by_id else None,
            'resolved_at': item.resolved_at.isoformat() if item.resolved_at else None,
            'created_at': item.created_at.isoformat()}


def items(actor, status=None, request=None):
    if not is_admin(actor, request):
        raise refusal('FORBIDDEN', 'Only an administrator can review unmatched Stripe activity.', 403)
    rows = StripeReviewItem.objects.select_related('account', 'resolved_by', 'event')
    if status:
        rows = rows.filter(status=status)
    return [item_data(item) for item in rows[:500]]


@transaction.atomic
def resolve(actor, item_id, data, request=None):
    if not is_admin(actor, request):
        raise refusal('FORBIDDEN', 'Only an administrator can review unmatched Stripe activity.', 403)
    item = StripeReviewItem.objects.select_for_update().filter(pk=item_id).first()
    if item is None:
        raise refusal('NOT_FOUND', 'No such review item.', 404)
    if item.status != 'OPEN':
        raise refusal('ALREADY_RESOLVED', 'This item was already resolved.', 409)
    note = ' '.join((data.get('note') or '').split())
    if len(note) < 5:
        raise refusal('NOTE_REQUIRED', 'Explain the resolution.')
    action = data.get('action')
    if action == 'LINK':
        account = StudentAccount.objects.filter(reference=(data.get('account_reference') or '').strip().upper()).first()
        if account is None:
            raise refusal('NOT_FOUND', 'No student account has that reference.', 404)
        item.status, item.account = 'LINKED', account
    elif action == 'DISMISS':
        item.status = 'DISMISSED'
    else:
        raise refusal('INVALID_ACTION', 'Dismiss the item or link it to a student account.')
    item.resolution_note, item.resolved_by, item.resolved_at = note, actor, timezone.now()
    item.save(update_fields=['status', 'account', 'resolution_note', 'resolved_by', 'resolved_at'])
    log_activity(action='stripe_review.resolve', entity_type='stripe_review', entity_id=item.pk, entity_label=item.kind,
                 context={'resolution': item.status, 'account': str(item.account_id) if item.account_id else None,
                          'object': item.object_id}, request=request, actor=actor)
    return item
