"""
An administrator's corrections to the earnings ledger -- never an edit or a
deletion, always a new line with who made it, when and why:

- reverse_entry: an earning or an adjustment taken back in full, in the month
  it counted in. The line it reverses stays, marked reversed; a reversed
  earning's class is never earned again automatically (earnings.ledger).
- add_adjustment: an amount added to or deducted from a tutor's earnings, in
  the month chosen, for one of their classes or none -- e.g. to pay a class
  again after its earning was reversed.
- keep_entry: an earning that needs review -- its class changed after it
  earned -- kept as earned, as it is. An adjustment alone does not settle a
  review: only keeping the earning or reversing it does.

All three are taken under the tutor's lock, so they queue with the tutor's payments.
"""
from django.db import IntegrityError, transaction

from activity.utils import log_activity

from . import summaries
from .eligibility import activated_at
from .models import EarningEntry, EarningReview, EntryKind
from .values import (
    INVALID,
    EarningsError,
    as_uuid,
    india_today,
    lock_tutor,
    month_of,
    parse_month,
    reason as clean_reason,
    rupees,
)

NOT_FOUND = 'ENTRY_NOT_FOUND'
ALREADY_REVERSED = 'ALREADY_REVERSED'
NOT_REVERSIBLE = 'NOT_REVERSIBLE'
NOT_IN_REVIEW = 'NOT_IN_REVIEW'
REVIEW_CHANGED = 'REVIEW_CHANGED'
INVALID_MONTH = 'INVALID_MONTH'
NOT_ACTIVATED = 'EARNINGS_NOT_ACTIVATED'


def _label(entry):
    details = entry.details or {}
    return details.get('student_name') or details.get('title') or entry.get_kind_display()


def reverse_entry(actor, entry_id, data, request=None):
    """Reverse the earning or adjustment ``entry_id`` for ``data['reason']``; returns the REVERSAL."""
    why = clean_reason(data.get('reason'))
    entry = EarningEntry.objects.filter(pk=entry_id).first()
    if entry is None:
        raise EarningsError(NOT_FOUND, 'No such ledger entry.', status=404)
    if entry.kind == EntryKind.REVERSAL:
        raise EarningsError(NOT_REVERSIBLE, 'A reversal cannot be reversed. Add an adjustment instead.', status=409)
    try:
        with transaction.atomic():
            lock_tutor(entry.tutor_id)
            if EarningEntry.objects.filter(reverses=entry).exists():
                raise EarningsError(ALREADY_REVERSED, 'This entry is already reversed.', status=409)
            reversal = EarningEntry.objects.create(
                kind=EntryKind.REVERSAL,
                tutor_id=entry.tutor_id,
                amount=-entry.amount,
                class_type=entry.class_type,
                source_id=entry.source_id,
                class_start=entry.class_start,
                class_end=entry.class_end,
                month=entry.month,
                details=entry.details,
                reverses=entry,
                reason=why,
                created_by=actor,
            )
    except IntegrityError:
        # Only a reversal written meanwhile is a refusal; anything else is a fault.
        if EarningEntry.objects.filter(reverses=entry).exists():
            raise EarningsError(ALREADY_REVERSED, 'This entry is already reversed.', status=409) from None
        raise
    log_activity(
        action='earnings.reverse_entry',
        entity_type='earning_entry',
        entity_id=str(entry.pk),
        entity_label=_label(entry),
        changes={'amount': {'old': str(entry.amount), 'new': str(entry.amount + reversal.amount)}},
        context={'tutor_id': str(entry.tutor_id), 'kind': entry.kind, 'reversal_id': str(reversal.pk),
                 'month': entry.month.isoformat(), 'reason': why},
        request=request,
        actor=actor,
    )
    return reversal


def add_adjustment(actor, tutor, data, request=None):
    """
    Add ``data['amount']`` (rupees: positive adds, negative deducts) to
    ``tutor``'s earnings in ``data['month']`` ('YYYY-MM', from the activation's
    month to this one), for ``data['reason']``, optionally about the class of
    one of their entries (``data['entry']``). Returns the ADJUSTMENT.
    """
    amount = rupees(data.get('amount'), 'amount', signed=True)
    why = clean_reason(data.get('reason'))
    since = activated_at()
    if since is None:
        raise EarningsError(NOT_ACTIVATED, 'Tutor Earnings is not activated.', status=409)
    month = parse_month(data.get('month') or india_today().strftime('%Y-%m'))
    if not (month_of(since) <= month <= india_today().replace(day=1)):
        raise EarningsError(INVALID_MONTH, 'Choose a month from the activation to this month.', field='month')
    about = None
    if data.get('entry'):
        key = as_uuid(data['entry'])
        about = EarningEntry.objects.filter(pk=key, tutor=tutor, class_type__isnull=False).first() if key else None
        if about is None:
            raise EarningsError(NOT_FOUND, "No such class in this tutor's ledger.", field='entry')
    with transaction.atomic():
        lock_tutor(tutor.pk)
        adjustment = EarningEntry.objects.create(
            kind=EntryKind.ADJUSTMENT,
            tutor=tutor,
            amount=amount,
            class_type=about.class_type if about else None,
            source_id=about.source_id if about else None,
            class_start=about.class_start if about else None,
            class_end=about.class_end if about else None,
            month=month,
            details=dict(about.details) if about else {},
            reason=why,
            created_by=actor,
        )
    log_activity(
        action='earnings.add_adjustment',
        entity_type='earning_entry',
        entity_id=str(adjustment.pk),
        entity_label=tutor.full_name or tutor.email,
        changes={'amount': {'old': None, 'new': str(amount)}},
        context={'tutor_id': str(tutor.pk), 'month': month.isoformat(), 'reason': why,
                 'entry_id': str(about.pk) if about else None},
        request=request,
        actor=actor,
    )
    return adjustment


def keep_entry(actor, entry_id, data, request=None):
    """
    Keep the earning ``entry_id`` as earned, for ``data['reason']``: one that
    needs review (its class changed after it earned) leaves the review list
    while its class reads as it does now. ``data['seen']`` is the change the
    administrator reviewed -- the review item's problem and current -- and
    only that change is kept: REVIEW_CHANGED when the class has changed again
    since. NOT_IN_REVIEW when it does not need review -- not an earning,
    reversed, unchanged, or kept already. Returns the EarningReview.
    """
    why = clean_reason(data.get('reason'))
    entry = EarningEntry.objects.filter(pk=entry_id).first()
    if entry is None:
        raise EarningsError(NOT_FOUND, 'No such ledger entry.', status=404)
    shown = data.get('seen')
    if not isinstance(shown, dict):
        raise EarningsError(INVALID, 'Send the change you reviewed.', field='seen')
    with transaction.atomic():
        lock_tutor(entry.tutor_id)
        item = summaries.review_item(entry)
        if item is None:
            raise EarningsError(NOT_IN_REVIEW, 'This earning does not need review.', status=409)
        if summaries.seen(item) != shown:
            raise EarningsError(REVIEW_CHANGED, 'This class changed since you opened it. Review it again.', status=409)
        review = EarningReview.objects.create(entry=entry, seen=summaries.seen(item), reason=why, created_by=actor)
    log_activity(
        action='earnings.keep_entry',
        entity_type='earning_entry',
        entity_id=str(entry.pk),
        entity_label=_label(entry),
        context={'tutor_id': str(entry.tutor_id), 'review_id': str(review.pk), 'amount': str(entry.amount),
                 'month': entry.month.isoformat(), 'problem': item['problem'], 'current': item['current'],
                 'reason': why},
        request=request,
        actor=actor,
    )
    return review
