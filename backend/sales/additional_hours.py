"""Additional hours with deferred payment.

An administrator gives an enrolled student additional hours of class quota
against one of their plans (a purchase), optionally naming a chapter of it for
reference. The hours join the student's overall quota at once -- in the same
transaction as the allocation -- and can be booked for any session; the due
date is only when the agreed amount should be collected. An administrator or
the student's own mentor records the payments, in parts if need be; a payment
never changes the quota.

Additional hours are always new hours with a new charge, never classes of a
plan. So they are refused while anything about the student's plans is still
open: paid classes the existing rules never credited, unpaid plan classes, a
payment link in progress, or a quota that does not add up (eligibility). The
regular plan ledger is only read here, through its own functions
(payments.received, payments.classes_credited, student_finance.payment_type);
nothing in it is written.

Every money figure is whole AED; hours are quota hours, in half hours.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import CharField, DecimalField, F, Func, Max, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce, Upper
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from students.models import Student

from . import payments, quotes
from .account_models import StudentAccount
from .allocation_models import AdditionalHoursAllocation, AdditionalHoursPayment, VoidKind
from .autopay_models import AutopayAgreement, AutopayInstallment
from .payment_models import INITIAL_KINDS, Payment, PaymentStatus, Purchase
from .pricing import plain
from .services import SalesError

MANAGE = 'accounts.manage_additional_hours'
COLLECT = 'accounts.collect_additional_hours_payments'
ZERO = Decimal('0')
# Hours added against the same plan, chapter and count this recently ask for confirmation.
DUPLICATE_WINDOW = timedelta(days=7)
ELIGIBLE_STATUSES = ('ACTIVE', 'INACTIVE')
OPEN_STATUSES = ('PENDING', 'PARTIALLY_PAID')
STATUSES = ('PENDING', 'PARTIALLY_PAID', 'PAID', 'WAIVED', 'CANCELLED')
LIVE = Q(voided_at__isnull=True)
OPEN = Q(waived_at__isnull=True, withdrawn_at__isnull=True)


def refusal(code, message, status=409, **extra):
    return SalesError(code, message, status, **extra)


def today():
    return timezone.localdate()


def reference_key(reference):
    """A reference as compared: its letters and digits alone, upper-cased."""
    return re.sub(r'[^A-Z0-9]', '', (reference or '').upper())


def is_manager(actor, request=None):
    return has_app_permission(actor, MANAGE, request)


def _require_access(actor, request=None):
    if not (has_app_permission(actor, COLLECT, request) or is_manager(actor, request)):
        raise refusal('FORBIDDEN', 'Additional hours access is required.', 403)


def _require_manager(actor, request=None):
    if not is_manager(actor, request):
        raise refusal('FORBIDDEN', 'Only an administrator manages additional hours.', 403)


def _person(user):
    return {'id': str(user.pk), 'name': user.full_name or user.username} if user else None


def _hours(value):
    return f'{plain(value)} hrs'


def visible_student(actor, student_id, request=None):
    """The student, when ``actor`` administers additional hours or is the student's assigned mentor."""
    _require_access(actor, request)
    student = Student.objects.filter(pk=student_id).first()
    if student is None or not (is_manager(actor, request) or (student.mentor_id and student.mentor_id == actor.pk)):
        raise refusal('NOT_FOUND', 'No such student among yours.', 404)
    return student


def visible_allocation(actor, allocation_id, request=None, lock=False):
    """An allocation of a student ``actor`` may see; locked for the transaction when ``lock``."""
    _require_access(actor, request)
    rows = AdditionalHoursAllocation.objects.select_related('student')
    if lock:
        rows = rows.select_for_update(of=('self',))
    allocation = rows.filter(pk=allocation_id).first()
    if allocation is None or not (is_manager(actor, request) or (allocation.student.mentor_id
                                                                 and allocation.student.mentor_id == actor.pk)):
        raise refusal('NOT_FOUND', 'No such additional hours among your students.', 404)
    return allocation


# ------------------------------------------------------------ eligibility

def _credited(rows):
    """``rows`` (received tuition payments) split by whether the existing rules credited their classes."""
    installments = {row.payment_id: row for row in AutopayInstallment.objects.filter(payment__in=rows)}
    credited, uncredited = [], []
    for row in rows:
        (credited if payments.classes_credited(row, installments.get(row.pk)) else uncredited).append(row)
    return credited, uncredited, installments


def _received_tuition(**filters):
    return list(Payment.objects.filter(purpose='TUITION', status=PaymentStatus.SUCCEEDED, **filters)
                .select_related('sale').order_by('payment_date', 'created_at'))


def _plan(purchase):
    """One of the student's purchases, with what eligibility reads: its classes, what is paid and what was credited."""
    from .student_finance import payment_type
    sale, quote = purchase.sale, purchase.quote
    paid = payments.received(sale)
    credited, uncredited, installments = _credited(_received_tuition(sale=sale))
    agreement = AutopayAgreement.objects.filter(purchase=purchase).first()
    return {
        'id': str(purchase.pk), 'sale_id': str(sale.pk), 'kind': sale.kind,
        'kind_label': 'Initial enrollment' if sale.kind in INITIAL_KINDS else 'Additional purchase',
        'quote_reference': quote.reference, 'syllabus': quote.revision.title, 'revision': quote.revision.number,
        'grade': quote.revision.grade, 'board': quote.revision.board, 'plan_type': quote.plan_type,
        'plan_type_label': quote.get_plan_type_display(), 'class_mode': quotes._class_mode(quote),
        'collection_mode': purchase.collection_mode, 'autopay_status': agreement.status if agreement else None,
        'purchased_at': purchase.created_at.isoformat(),
        # Plan figures stay in classes, as the quote counts them; 1 plan class = 1 hour of quota.
        'classes': plain(purchase.classes), 'paid_classes': plain(paid['classes']),
        'credited_classes': plain(sum((row.classes for row in credited), ZERO)),
        'uncredited_classes': plain(sum((row.classes for row in uncredited), ZERO)),
        'unpaid_classes': plain(purchase.classes - paid['classes']),
        'package_amount': plain(purchase.amount), 'outstanding_amount': plain(purchase.amount - paid['amount']),
        'payment_link_pending': sale.payments.filter(status=PaymentStatus.PENDING).exists(),
        # A hint for the amount only (the quote's offer fee per class); never enforced.
        'rate_per_class': plain(quote.offer_fee),
        'additional_hours': plain(purchase.additional_hours.filter(withdrawn_at__isnull=True)
                                  .aggregate(n=Sum('hours'))['n'] or ZERO),
        'chapters': [{'id': str(row.chapter_id), 'position': row.chapter.position, 'name': row.chapter.name,
                      'classes': plain(row.classes)}
                     for row in quote.chapters.select_related('chapter').order_by('chapter__position')],
        'uncredited_payments': [{
            'payment_id': str(row.pk), 'payment_date': row.payment_date.isoformat(), 'amount': plain(row.amount),
            'classes': plain(row.classes), 'payment_type': payment_type(row, installments.get(row.pk)),
            'quote_reference': quote.reference,
        } for row in uncredited],
    }


def credited_plan_classes(student):
    """The classes the existing rules credited to ``student``'s quota: enrollment's, then each Autopay installment's."""
    credited, _uncredited, _installments = _credited(_received_tuition(sale__student=student))
    return sum((row.classes for row in credited), ZERO)


def active_hours(student):
    return student.additional_hours.filter(withdrawn_at__isnull=True).aggregate(n=Sum('hours'))['n'] or ZERO


def reconciliation(student):
    """Whether ``student``'s quota is what it should be: credited plan classes plus active additional hours."""
    credited, added = credited_plan_classes(student), active_hours(student)
    expected = credited + added
    return {'quota': plain(student.total_class_quota), 'credited_plan_classes': plain(credited),
            'additional_hours': plain(added), 'expected_quota': plain(expected),
            'reconciles': student.total_class_quota == expected}


def _problem(code, message, **extra):
    return {'code': code, 'message': message, **extra}


def eligibility(student):
    """Whether additional hours may be added for ``student`` now, and every reason they may not, most urgent first."""
    if student.quota_source != 'PAYMENTS':
        return {'eligible': False, 'plans': [], 'quota': None, 'problems': [_problem(
            'NOT_ELIGIBLE', 'Additional hours are only for students enrolled through Eduport Plus payments. '
                            'This student’s class quota comes from the enrolment sheet.')]}
    problems = []
    if student.status not in ELIGIBLE_STATUSES:
        problems.append(_problem('NOT_ELIGIBLE', 'Additional hours are not added for an expired student.'))
    plans = [_plan(purchase) for purchase in Purchase.objects.select_related('sale', 'quote__revision')
             .filter(student=student).order_by('created_at', 'pk')]
    if not plans:
        problems.append(_problem('NO_PLAN', 'This student has no plan to add hours against.'))
    uncredited = [row for plan in plans for row in plan['uncredited_payments']]
    if uncredited:
        classes = sum((Decimal(row['classes']) for row in uncredited), ZERO)
        problems.append(_problem(
            'PAID_CLASSES_NOT_CREDITED',
            f'{plain(classes)} paid classes ({_hours(classes)}) were never added to this student’s quota. '
            'Resolve this payment/quota mismatch before adding hours: additional hours are new hours with a new '
            'charge, never classes that were already paid for.', payments=uncredited))
    pending = [plan for plan in plans if plan['payment_link_pending']]
    if pending:
        problems.append(_problem(
            'PAYMENT_IN_PROGRESS', 'A plan payment link is still open. Let it complete, or expire it, first.',
            plans=[plan['quote_reference'] for plan in pending]))
    unpaid = [plan for plan in plans if Decimal(plan['unpaid_classes']) > 0]
    if unpaid:
        problems.append(_problem(
            'PLAN_CLASSES_UNPAID',
            'A plan still has unpaid classes. Additional hours cannot overlap a plan’s own classes, paid or unpaid: '
            'collect the plan’s balance (or let its Autopay complete) first.',
            plans=[{'quote_reference': plan['quote_reference'], 'syllabus': plan['syllabus'], 'kind': plan['kind'],
                    'unpaid_classes': plan['unpaid_classes'], 'outstanding_amount': plan['outstanding_amount'],
                    'autopay_status': plan['autopay_status'], 'collection_mode': plan['collection_mode']}
                   for plan in unpaid]))
    quota = reconciliation(student)
    if not quota['reconciles']:
        problems.append(_problem(
            'QUOTA_MISMATCH', f'The student’s quota is {_hours(student.total_class_quota)}, but their credited plan '
                              f'classes and additional hours add up to {quota["expected_quota"]} hrs. '
                              'Resolve the mismatch before adding hours.', quota=quota))
    return {'eligible': not problems, 'problems': problems, 'quota': quota, 'plans': plans}


def _refuse(found):
    first = found['problems'][0]
    raise refusal(first['code'], first['message'], 409, problems=found['problems'])


# ------------------------------------------------------------------- figures

def paid_amount(allocation):
    return allocation.payments.filter(LIVE).aggregate(n=Sum('amount'))['n'] or ZERO


def state(allocation, paid, on=None):
    """Where an allocation's payment stands; the hours count whatever it says."""
    on = on or today()
    remaining = allocation.amount - paid
    if allocation.withdrawn_at:
        status = 'CANCELLED'
    elif allocation.waived_at:
        status = 'WAIVED'
    elif remaining <= 0:
        status = 'PAID'
    else:
        status = 'PARTIALLY_PAID' if paid > 0 else 'PENDING'
    owing = status in OPEN_STATUSES
    overdue = owing and allocation.due_date < on
    return {'status': status, 'paid_amount': plain(paid), 'outstanding_amount': plain(remaining if owing else ZERO),
            'waived_amount': plain(remaining if status == 'WAIVED' else ZERO), 'overdue': overdue,
            'days_overdue': (on - allocation.due_date).days if overdue else 0}


def payment_data(payment):
    return {
        'id': str(payment.pk), 'amount': plain(payment.amount), 'currency': payment.currency,
        'method': payment.method, 'method_label': payment.get_method_display(),
        'payment_date': payment.payment_date.isoformat(), 'transaction_reference': payment.transaction_reference,
        'notes': payment.notes, 'recorded_by': _person(payment.recorded_by), 'recorded_at': payment.recorded_at.isoformat(),
        'proof_name': payment.proof_name,
        'proof_url': f'/api/sales/additional-hours/{payment.allocation_id}/payments/{payment.pk}/proof/',
        'voided': payment.voided_at is not None,
        'void': {'at': payment.voided_at.isoformat(), 'by': _person(payment.voided_by), 'kind': payment.void_kind,
                 'kind_label': payment.get_void_kind_display(), 'reason': payment.void_reason} if payment.voided_at else None,
    }


def _closing(at, by, reason):
    return {'at': at.isoformat(), 'by': _person(by), 'reason': reason} if at else None


def allocation_data(allocation, actor=None, request=None, paid=None, last_paid_on=None, rows=None):
    """One allocation as the Hub shows it: the hours, the plan they were given against, and their payment."""
    if rows is not None:
        live = [row for row in rows if row.voided_at is None]
        paid = sum((row.amount for row in live), ZERO)
        last_paid_on = max((row.payment_date for row in live), default=None)
    elif paid is None:
        paid = paid_amount(allocation)
        last_paid_on = allocation.payments.filter(LIVE).aggregate(n=Max('payment_date'))['n']
    figures = state(allocation, paid)
    purchase, quote, chapter = allocation.purchase, allocation.purchase.quote, allocation.chapter
    manager = bool(actor) and is_manager(actor, request)
    closed = bool(allocation.waived_at or allocation.withdrawn_at)
    data = {
        'id': str(allocation.pk), 'reference': allocation.reference,
        'student': {'id': str(allocation.student_id), 'student_code': allocation.student.student_code,
                    'full_name': allocation.student.full_name},
        'plan': {'purchase_id': str(purchase.pk), 'sale_id': str(purchase.sale_id), 'kind': purchase.sale.kind,
                 'quote_reference': quote.reference, 'syllabus': quote.revision.title, 'plan_type': quote.plan_type,
                 'plan_type_label': quote.get_plan_type_display()},
        'chapter': {'id': str(chapter.pk), 'position': chapter.position, 'name': chapter.name} if chapter else None,
        'hours': plain(allocation.hours), 'hours_status': 'WITHDRAWN' if allocation.withdrawn_at else 'ACTIVE',
        'amount': plain(allocation.amount), 'currency': allocation.currency,
        'due_date': allocation.due_date.isoformat(), 'reason': allocation.reason,
        'quota_before': plain(allocation.quota_before), 'quota_after': plain(allocation.quota_before + allocation.hours),
        'created_by': _person(allocation.created_by), 'created_at': allocation.created_at.isoformat(),
        **figures,
        'last_payment_date': last_paid_on.isoformat() if last_paid_on else None,
        'waived': _closing(allocation.waived_at, allocation.waived_by, allocation.waive_reason),
        'withdrawn': _closing(allocation.withdrawn_at, allocation.withdrawn_by, allocation.withdraw_reason),
        'can_record_payment': figures['status'] in OPEN_STATUSES,
        'can_manage': manager and not closed,
        'can_void_payments': manager and not allocation.waived_at,
    }
    if rows is not None:
        data['payments'] = [payment_data(row) for row in rows]
    return data


def _allocations():
    return AdditionalHoursAllocation.objects.select_related(
        'student', 'purchase__sale', 'purchase__quote__revision', 'chapter', 'created_by', 'waived_by', 'withdrawn_by')


def _with_payments(rows):
    return rows.prefetch_related(Prefetch('payments', queryset=AdditionalHoursPayment.objects.select_related(
        'recorded_by', 'voided_by').order_by('recorded_at', 'pk')))


def detail(actor, allocation_id, request=None):
    visible_allocation(actor, allocation_id, request)
    allocation = _with_payments(_allocations()).get(pk=allocation_id)
    return allocation_data(allocation, actor, request, rows=list(allocation.payments.all()))


def summary(allocations):
    """Totals over allocations already shown (each a dict from allocation_data)."""
    def total(key, rows):
        return plain(sum((Decimal(row[key]) for row in rows), ZERO))
    active = [row for row in allocations if row['hours_status'] == 'ACTIVE']
    overdue = [row for row in allocations if row['overdue']]
    return {
        'hours_added': total('hours', active),
        # Hours the student already has whose payment is still owed.
        'payment_pending_hours': total('hours', [row for row in active if row['status'] in OPEN_STATUSES]),
        'amount': total('amount', active), 'received': total('paid_amount', allocations),
        'outstanding': total('outstanding_amount', allocations), 'waived': total('waived_amount', allocations),
        'overdue_count': len(overdue), 'overdue_amount': total('outstanding_amount', overdue),
    }


def student_overview(actor, student_id, request=None):
    """A student's additional hours, each with its payments, and their totals: kept apart from the plan figures."""
    student = visible_student(actor, student_id, request)
    allocations = list(_with_payments(_allocations()).filter(student=student).order_by('-created_at', '-pk'))
    rows = [allocation_data(allocation, actor, request, rows=list(allocation.payments.all())) for allocation in allocations]
    return {
        'student': {'id': str(student.pk), 'student_code': student.student_code, 'full_name': student.full_name,
                    'quota_source': student.quota_source},
        'summary': summary(rows), 'allocations': rows,
        'can_create': is_manager(actor, request) and student.quota_source == 'PAYMENTS',
    }


def eligibility_data(actor, student_id, request=None):
    """What the administrator's form needs: whether hours may be added now (and why not), and each plan with its chapters."""
    _require_manager(actor, request)
    student = Student.objects.filter(pk=student_id).first()
    if student is None:
        raise refusal('NOT_FOUND', 'No such student.', 404)
    found = eligibility(student)
    return {'student': {'id': str(student.pk), 'student_code': student.student_code, 'full_name': student.full_name},
            **found, 'today': today().isoformat()}


def quota_summary(student):
    """For the student's profile: their active additional hours, and how many of them are still to be paid for."""
    rows = list(student.additional_hours.filter(withdrawn_at__isnull=True).annotate(
        paid=Coalesce(Sum('payments__amount', filter=Q(payments__voided_at__isnull=True)), Value(ZERO),
                      output_field=DecimalField(max_digits=15, decimal_places=0)))
        .values_list('hours', 'amount', 'paid', 'waived_at'))
    if not rows:
        return None
    pending = sum((hours for hours, amount, paid, waived_at in rows if waived_at is None and paid < amount), ZERO)
    return {'active_hours': plain(sum((row[0] for row in rows), ZERO)), 'payment_pending_hours': plain(pending)}


# ------------------------------------------------------------------ changes

def _audit(action, allocation, actor, request=None, changes=None, **context):
    log_activity(action=action, entity_type='additional_hours', entity_id=allocation.pk, entity_label=allocation.reference,
                 student=allocation.student, changes=changes, context=context, request=request, actor=actor)


def _same_allocation(existing, student, actor, data):
    return (existing.student_id == student.pk and existing.created_by_id == actor.pk
            and existing.purchase_id == data['purchase'] and existing.chapter_id == data.get('chapter')
            and existing.hours == data['hours'] and existing.amount == data['amount']
            and existing.due_date == data['due_date'] and existing.reason == data['reason'])


def _lock_student(student_id):
    """The student's account, then the student: the order identity corrections take (sales.student_accounts), so
    an additional purchase or a correction made at the same moment queues behind this change, or ahead of it."""
    StudentAccount.objects.select_for_update().filter(student_id=student_id).first()
    return Student.objects.select_for_update().get(pk=student_id)


def create(actor, student_id, data, request=None):
    """Add hours to the student's quota now, owed for by ``data['due_date']``. Returns (allocation, created)."""
    _require_manager(actor, request)
    if not Student.objects.filter(pk=student_id).exists():
        raise refusal('NOT_FOUND', 'No such student.', 404)
    with transaction.atomic():
        student = _lock_student(student_id)
        existing = AdditionalHoursAllocation.objects.filter(request_id=data['request_id']).first()
        if existing is not None:
            if not _same_allocation(existing, student, actor, data):
                raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for other hours.', 409)
            return existing, False
        found = eligibility(student)
        if found['problems']:
            _refuse(found)
        purchase = Purchase.objects.select_related('quote').filter(pk=data['purchase'], student=student).first()
        if purchase is None:
            raise refusal('PLAN_NOT_STUDENTS', 'Choose one of this student’s own plans.', 409)
        chapter = None
        if data.get('chapter'):
            quoted = purchase.quote.chapters.select_related('chapter').filter(chapter_id=data['chapter']).first()
            if quoted is None:
                raise refusal('CHAPTER_NOT_IN_PLAN', 'Choose a chapter of the selected plan, or none.', 409)
            chapter = quoted.chapter
        if data['due_date'] < today():
            raise refusal('DUE_DATE_PAST', 'Choose today or a later due date.', 400)
        if not data.get('confirm_duplicate'):
            twin = (AdditionalHoursAllocation.objects.filter(
                student=student, purchase=purchase, chapter=chapter, hours=data['hours'], withdrawn_at__isnull=True,
                created_at__gte=timezone.now() - DUPLICATE_WINDOW).select_related('created_by').order_by('-created_at').first())
            if twin is not None:
                raise refusal('POSSIBLE_DUPLICATE',
                              f'{_hours(twin.hours)} were already added against this plan'
                              f'{" and chapter" if chapter else ""} on {timezone.localtime(twin.created_at):%d %b %Y} '
                              f'by {twin.created_by.full_name or twin.created_by.username} ({twin.reference}). '
                              'Confirm only if these are further hours.', 409, allocation_id=str(twin.pk),
                              reference=twin.reference)
        before = student.total_class_quota
        student.total_class_quota = before + data['hours']
        student.save(update_fields=['total_class_quota', 'updated_at'])
        from .enrollment import next_number
        allocation = AdditionalHoursAllocation.objects.create(
            reference=f'AH-{next_number("ADDITIONAL_HOURS"):06d}', request_id=data['request_id'], student=student,
            purchase=purchase, chapter=chapter, hours=data['hours'], amount=data['amount'], due_date=data['due_date'],
            reason=data['reason'], quota_before=before, created_by=actor)
        _audit('additional_hours.create', allocation, actor, request,
               changes={'total_class_quota': {'old': plain(before), 'new': plain(student.total_class_quota)}},
               hours=plain(allocation.hours), amount=plain(allocation.amount), due_date=allocation.due_date.isoformat(),
               purchase=str(purchase.pk), quote=purchase.quote.reference, chapter=str(chapter.pk) if chapter else None,
               reason=allocation.reason)
    return allocation, True


def update(actor, allocation_id, data, request=None):
    """Change an open allocation's due date and/or amount (never below what is paid), with the reason."""
    _require_manager(actor, request)
    with transaction.atomic():
        allocation = visible_allocation(actor, allocation_id, request, lock=True)
        if allocation.waived_at or allocation.withdrawn_at:
            raise refusal('ALLOCATION_CLOSED', 'These hours are waived or withdrawn: nothing about them changes now.')
        changes = {}
        if data.get('due_date') is not None and data['due_date'] != allocation.due_date:
            if data['due_date'] < today():
                raise refusal('DUE_DATE_PAST', 'Choose today or a later due date.', 400)
            changes['due_date'] = {'old': allocation.due_date.isoformat(), 'new': data['due_date'].isoformat()}
            allocation.due_date = data['due_date']
        if data.get('amount') is not None and data['amount'] != allocation.amount:
            paid = paid_amount(allocation)
            if data['amount'] < paid:
                raise refusal('AMOUNT_BELOW_PAID', f'AED {plain(paid)} is already paid: the amount cannot be less.',
                              409, paid_amount=plain(paid))
            changes['amount'] = {'old': plain(allocation.amount), 'new': plain(data['amount'])}
            allocation.amount = data['amount']
        if not changes:
            raise refusal('NO_CHANGE', 'Change the due date or the amount.', 400)
        allocation.save(update_fields=['due_date', 'amount'])
        _audit('additional_hours.update', allocation, actor, request, changes=changes, reason=data['change_reason'])
    return allocation


def waive(actor, allocation_id, data, request=None):
    """Write off what is still unpaid. The hours stay; the allocation is closed."""
    _require_manager(actor, request)
    with transaction.atomic():
        allocation = visible_allocation(actor, allocation_id, request, lock=True)
        if allocation.waived_at or allocation.withdrawn_at:
            raise refusal('ALLOCATION_CLOSED', 'These hours are already waived or withdrawn.')
        remaining = allocation.amount - paid_amount(allocation)
        if remaining <= 0:
            raise refusal('ALLOCATION_PAID', 'These hours are paid in full: nothing is left to waive.')
        allocation.waived_at, allocation.waived_by, allocation.waive_reason = timezone.now(), actor, data['reason']
        allocation.save(update_fields=['waived_at', 'waived_by', 'waive_reason'])
        _audit('additional_hours.waive', allocation, actor, request, changes={'outstanding': {'old': plain(remaining), 'new': '0'}},
               waived_amount=plain(remaining), reason=data['reason'])
    return allocation


def withdraw(actor, allocation_id, data, request=None):
    """Take the hours back out of the quota: only while they are unused and nothing paid for them still counts."""
    _require_manager(actor, request)
    allocation = visible_allocation(actor, allocation_id, request)
    from sessions.services import calculate_credits_used
    with transaction.atomic():
        student = _lock_student(allocation.student_id)
        allocation = visible_allocation(actor, allocation_id, request, lock=True)
        if allocation.waived_at or allocation.withdrawn_at:
            raise refusal('ALLOCATION_CLOSED', 'These hours are already waived or withdrawn.')
        if allocation.payments.filter(LIVE).exists():
            raise refusal('HAS_PAYMENTS', 'Payments are recorded for these hours. Void them (as refunded) before '
                                          'withdrawing the hours.')
        used = Decimal(str(round(calculate_credits_used(student), 2)))
        unused = student.total_class_quota - used
        if unused < allocation.hours:
            raise refusal('HOURS_IN_USE', f'Only {_hours(max(unused, ZERO))} of the student’s quota are unbooked, so '
                                          f'these {_hours(allocation.hours)} cannot be withdrawn. Waive the payment instead.',
                          409, unused_hours=plain(unused), hours=plain(allocation.hours))
        before = student.total_class_quota
        student.total_class_quota = before - allocation.hours
        student.save(update_fields=['total_class_quota', 'updated_at'])
        allocation.withdrawn_at, allocation.withdrawn_by = timezone.now(), actor
        allocation.withdraw_reason, allocation.withdrawn_quota_before = data['reason'], before
        allocation.save(update_fields=['withdrawn_at', 'withdrawn_by', 'withdraw_reason', 'withdrawn_quota_before'])
        _audit('additional_hours.withdraw', allocation, actor, request,
               changes={'total_class_quota': {'old': plain(before), 'new': plain(student.total_class_quota)}},
               hours=plain(allocation.hours), reason=data['reason'])
    return allocation


# ----------------------------------------------------------------- payments

def _tuition_with_reference(key):
    """A regular tuition payment carrying the same reference (compared as reference_key compares)."""
    normalized = Upper(Func(F('transaction_reference'), Value('[^A-Za-z0-9]'), Value(''), Value('g'),
                            function='REGEXP_REPLACE', output_field=CharField()))
    return (Payment.objects.exclude(transaction_reference='').annotate(reference_key=normalized)
            .filter(reference_key=key).select_related('sale__student').first())


def _check_duplicates(allocation, key, data, confirmed):
    live = AdditionalHoursPayment.objects.filter(LIVE).select_related('allocation', 'recorded_by')
    if key:
        same = live.filter(allocation=allocation, reference_key=key).first()
        if same is not None:
            raise refusal('DUPLICATE_REFERENCE', f'This reference is already recorded on these hours '
                                                 f'(AED {plain(same.amount)}, {same.payment_date:%d %b %Y}).',
                          409, field='transaction_reference', payment_id=str(same.pk))
        foreign = live.filter(reference_key=key).exclude(allocation__student_id=allocation.student_id).first()
        if foreign is not None:
            raise refusal('DUPLICATE_REFERENCE', 'This reference is already recorded for another student’s additional hours.',
                          409, field='transaction_reference')
    if confirmed:
        return
    if key:
        sibling = live.filter(reference_key=key, allocation__student_id=allocation.student_id).exclude(allocation=allocation).first()
        if sibling is not None:
            raise refusal('POSSIBLE_DUPLICATE', f'This reference is also recorded on {sibling.allocation.reference}. '
                                                'Confirm only if one payment covered both.', 409, payment_id=str(sibling.pk))
        tuition = _tuition_with_reference(key)
        if tuition is not None:
            raise refusal('POSSIBLE_DUPLICATE', f'This reference is already recorded on a tuition payment '
                                                f'({tuition.payment_date:%d %b %Y}). Confirm only if one transfer paid both.', 409)
    twin = live.filter(allocation=allocation, amount=data['amount'], payment_date=data['payment_date']).first()
    if twin is not None:
        raise refusal('POSSIBLE_DUPLICATE', f'A payment of AED {plain(twin.amount)} dated {twin.payment_date:%d %b %Y} was '
                                            f'already recorded by {twin.recorded_by.full_name or twin.recorded_by.username}. '
                                            'Confirm only if this is a second payment.', 409, payment_id=str(twin.pk))


def _same_payment(existing, allocation, actor, data, reference):
    return (existing.allocation_id == allocation.pk and existing.recorded_by_id == actor.pk
            and existing.amount == data['amount'] and existing.method == data['method']
            and existing.payment_date == data['payment_date'] and existing.transaction_reference == reference
            and existing.notes == (data.get('notes') or '').strip())


def record_payment(actor, allocation_id, data, request=None):
    """Money received for an allocation, with its receipt: at most what is still due. Never changes the quota.

    Returns (payment, created) -- created false when the same request was recorded before.
    """
    visible_allocation(actor, allocation_id, request)  # Refuse before the transaction; checked again under the lock.
    stored = None
    reference = (data.get('transaction_reference') or '').strip()
    try:
        with transaction.atomic():
            allocation = visible_allocation(actor, allocation_id, request, lock=True)
            existing = AdditionalHoursPayment.objects.filter(request_id=data['request_id']).first()
            if existing is not None:
                if not _same_payment(existing, allocation, actor, data, reference):
                    raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for another payment.', 409)
                return existing, False
            if allocation.waived_at or allocation.withdrawn_at:
                raise refusal('ALLOCATION_CLOSED', 'These hours are waived or withdrawn: they take no further payment.')
            remaining = allocation.amount - paid_amount(allocation)
            if remaining <= 0:
                raise refusal('ALLOCATION_PAID', 'These hours are already paid in full.')
            if data['amount'] > remaining:
                raise refusal('EXCEEDS_OUTSTANDING', f'The payment is more than the AED {plain(remaining)} still due.',
                              409, outstanding=plain(remaining), field='amount')
            if not data.get('received_confirmed'):
                raise refusal('RECEIPT_NOT_CONFIRMED', 'Confirm that the money has actually been received.', 400)
            if not data.get('proof'):
                raise refusal('PROOF_REQUIRED', 'Attach the payment receipt or screenshot.', 400)
            key = reference_key(reference)
            _check_duplicates(allocation, key, data, data.get('confirm_duplicate') is True)
            payment = AdditionalHoursPayment(
                request_id=data['request_id'], allocation=allocation, amount=data['amount'], method=data['method'],
                payment_date=data['payment_date'], transaction_reference=reference, reference_key=key,
                received_confirmed=True, notes=(data.get('notes') or '').strip(), recorded_by=actor)
            stored = payments.store_proof(payment, data['proof'])
            payment.save(force_insert=True)
            _audit('additional_hours.payment_record', allocation, actor, request,
                   changes={'outstanding': {'old': plain(remaining), 'new': plain(remaining - payment.amount)}},
                   payment=str(payment.pk), amount=plain(payment.amount), method=payment.method,
                   payment_date=payment.payment_date.isoformat(), reference=reference)
            return payment, True
    except Exception:
        if stored:
            stored.storage.delete(stored.name)
        raise


def void_payment(actor, allocation_id, payment_id, data, request=None):
    """Void a payment, with its kind and reason: it stays in the history and no longer counts, so the balance reopens."""
    _require_manager(actor, request)
    with transaction.atomic():
        allocation = visible_allocation(actor, allocation_id, request, lock=True)
        payment = allocation.payments.select_for_update().filter(pk=payment_id).first()
        if payment is None:
            raise refusal('NOT_FOUND', 'No such payment.', 404)
        if payment.voided_at is not None:
            raise refusal('ALREADY_VOIDED', 'This payment is already voided.')
        if allocation.waived_at:
            raise refusal('ALLOCATION_CLOSED', 'These hours are waived: their payments can no longer be voided.')
        remaining = allocation.amount - paid_amount(allocation)
        payment.voided_at, payment.voided_by = timezone.now(), actor
        payment.void_kind, payment.void_reason = data['kind'], data['reason']
        payment.save(update_fields=['voided_at', 'voided_by', 'void_kind', 'void_reason'])
        _audit('additional_hours.payment_void', allocation, actor, request,
               changes={'outstanding': {'old': plain(remaining), 'new': plain(remaining + payment.amount)}},
               payment=str(payment.pk), amount=plain(payment.amount), kind=payment.void_kind,
               reason=payment.void_reason, reference=payment.transaction_reference)
    return payment


def proof(actor, allocation_id, payment_id, request=None):
    allocation = visible_allocation(actor, allocation_id, request)
    payment = allocation.payments.filter(pk=payment_id).exclude(proof='').first()
    if payment is None:
        raise refusal('NOT_FOUND', 'No such receipt.', 404)
    return payment


# ----------------------------------------------------------------- register

def register(actor, filters, request=None):
    """Allocations across students -- every student's for an administrator, a mentor's own students' otherwise --
    with what is paid; filtered by status, overdue, mentor, student and due dates. Returns (rows, totals)."""
    _require_access(actor, request)
    rows = _allocations()
    if not is_manager(actor, request):
        rows = rows.filter(student__mentor_id=actor.pk)
    elif filters.get('mentor'):
        rows = rows.filter(student__mentor_id=filters['mentor'])
    if filters.get('student'):
        rows = rows.filter(student_id=filters['student'])
    if filters.get('due_from'):
        rows = rows.filter(due_date__gte=filters['due_from'])
    if filters.get('due_to'):
        rows = rows.filter(due_date__lte=filters['due_to'])
    status = filters.get('status')
    if status in ('PENDING', 'PARTIALLY_PAID', 'PAID', 'OPEN') or filters.get('overdue'):
        rows = rows.filter(OPEN)
    elif status == 'WAIVED':
        rows = rows.filter(waived_at__isnull=False)
    elif status == 'CANCELLED':
        rows = rows.filter(withdrawn_at__isnull=False)
    rows = rows.annotate(
        paid=Coalesce(Sum('payments__amount', filter=Q(payments__voided_at__isnull=True)), Value(ZERO),
                      output_field=DecimalField(max_digits=15, decimal_places=0)),
        last_paid_on=Max('payments__payment_date', filter=Q(payments__voided_at__isnull=True)))
    if status == 'PENDING':
        rows = rows.filter(paid=0)
    elif status == 'PARTIALLY_PAID':
        rows = rows.filter(paid__gt=0, paid__lt=F('amount'))
    elif status == 'PAID':
        rows = rows.filter(paid__gte=F('amount'))
    elif status == 'OPEN':
        rows = rows.filter(paid__lt=F('amount'))
    if filters.get('overdue'):
        rows = rows.filter(paid__lt=F('amount'), due_date__lt=today())
    rows = rows.order_by('due_date', 'created_at', 'pk')
    shown = [allocation_data(row, actor, request, paid=row.paid, last_paid_on=row.last_paid_on) for row in rows]
    return rows, summary(shown)
