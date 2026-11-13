"""Additional purchases: a Mentor's further purchase for one of their enrolled students.

Each one is a NEW Sale (kind ADDITIONAL) on the student's existing StudentAccount,
with its own quote, purchase and payments; earlier sales are never changed, and
the student's one Stripe Customer is reused. The quote is priced exactly as any
quote (sales.quotes), so existing pricing rules apply unchanged.

Cases the existing business rules do not define are refused with an explicit
code until a decision is made (see docs/student-financial-identity.md):
Autopay for an additional purchase, an earlier sale with an outstanding balance,
and an earlier Autopay agreement still collecting. Payments of an additional
purchase record money only: no rule credits their classes yet.
"""
import dataclasses
import uuid

from django.db import transaction

from accounts.authz import has_app_permission
from . import payments, quotes, services
from .account_models import StudentAccount
from .models import Syllabus
from .autopay_models import AutopayAgreement
from .payment_models import Payment, PaymentMethod, PaymentStatus, Purchase, Sale, SaleKind
from .pricing import plain
from .student_accounts import account_data, billing_guardian, is_admin, lock_identity, refusal

PERMISSION = 'accounts.create_additional_purchases'


def _student(actor, student_id, request=None):
    """The student, when ``actor`` is their assigned mentor (or an administrator)."""
    from students.models import Student
    if not has_app_permission(actor, PERMISSION, request):
        raise refusal('FORBIDDEN', 'Only the student’s mentor can add a purchase.', 403)
    student = Student.objects.filter(pk=student_id).first()
    if student is None or not (student.mentor_id == actor.pk or is_admin(actor, request)):
        raise refusal('NOT_FOUND', 'No such student among yours.', 404)
    account = StudentAccount.objects.filter(student=student).first()
    if account is None:
        raise refusal('NO_STUDENT_ACCOUNT', 'This student was not enrolled through Eduport Plus payments, so they have no '
                      'student account to add a purchase to. A decision is needed for sheet-managed students.', 409)
    return student, account


def _sale(actor, sale_id, request=None, lock=False):
    """An additional purchase of one of ``actor``'s students (or any, for an administrator)."""
    sale = Sale.objects.select_related('student', 'account').filter(pk=sale_id, kind=SaleKind.ADDITIONAL).first()
    if sale is None:
        raise refusal('NOT_FOUND', 'No such purchase.', 404)
    _student(actor, sale.student_id, request)
    if lock:
        from .stripe_gateway import lock_sale
        sale = lock_sale(sale)
    return sale


def sale_summary(sale):
    purchase = Purchase.objects.select_related('quote').filter(sale=sale, is_initial=True).first()
    paid = payments.received(sale)
    agreement = AutopayAgreement.objects.filter(purchase=purchase).first() if purchase else None
    amount = purchase.amount if purchase else None
    return {
        'id': str(sale.pk), 'kind': sale.kind, 'created_at': sale.created_at.isoformat(),
        'quote_id': str(purchase.quote_id) if purchase else None,
        'quote_reference': purchase.quote.reference if purchase else None,
        'plan_type': purchase.quote.plan_type if purchase else None,
        'classes': plain(purchase.classes) if purchase else None,
        'package_amount': plain(amount) if amount is not None else None, 'paid_amount': plain(paid['amount']),
        'outstanding_amount': plain(amount - paid['amount']) if amount is not None else None,
        'fully_paid': amount is not None and paid['amount'] >= amount,
        'autopay_status': agreement.status if agreement else None,
    }


def blockers(account):
    """Earlier-sale states that no established rule covers: no new purchase until decided."""
    found = []
    for sale in account.sales.order_by('created_at'):
        summary = sale_summary(sale)
        if summary['autopay_status'] and summary['autopay_status'] not in ('COMPLETED', 'CANCELLED'):
            found.append({'code': 'EARLIER_AUTOPAY_ACTIVE', 'sale_id': summary['id'],
                          'message': 'An earlier Autopay agreement is still collecting. Whether a new purchase may start meanwhile is not decided yet.'})
        elif summary['outstanding_amount'] is not None and not summary['fully_paid']:
            found.append({'code': 'EARLIER_BALANCE_OUTSTANDING', 'sale_id': summary['id'],
                          'message': f'An earlier sale still has AED {summary["outstanding_amount"]} outstanding. Whether a new purchase may start meanwhile is not decided yet.'})
    return found


def overview(actor, student_id, request=None, syllabus_id=None):
    student, account = _student(actor, student_id, request)
    found = blockers(account)
    data = {
        'student': {'id': str(student.pk), 'student_code': student.student_code, 'full_name': student.full_name},
        'account': {'id': str(account.pk), 'reference': account.reference},
        'sales': [sale_summary(sale) for sale in account.sales.order_by('created_at')],
        'blockers': found, 'can_add': not found,
        'catalogue': services.catalogue_rows(services.by_grade_and_title(services.catalogue())),
        'syllabus': None,
    }
    if syllabus_id:
        data['syllabus'] = services.catalogue_detail(syllabus_id)
        if data['syllabus'] is None:
            raise refusal('NOT_FOUND', 'No such syllabus on sale.', 404)
    return data


def _snapshot(actor, account, data):
    if data.get('collection_mode') == 'AUTOPAY':
        raise refusal('AUTOPAY_PENDING_DECISION', 'Autopay for an additional purchase is not decided yet. Choose complete or partial payment.', 409)
    snapshot = quotes.quote_snapshot(actor, syllabus_id=data['syllabus'], revision=data['revision'], plan_type=data['plan_type'],
                                     chapter_ids=data.get('chapter_ids') or (), class_mode=data.get('class_mode'),
                                     collection_mode=data.get('collection_mode'))
    return dataclasses.replace(snapshot, account=account)


def preview(actor, student_id, data, request=None):
    _student_record, account = _student(actor, student_id, request)
    snapshot = _snapshot(actor, account, data)
    subtotal, amount = payments.whole(snapshot.total_fee), payments.whole(snapshot.payable_amount)
    return {'plan_type': snapshot.plan_type, 'classes': plain(snapshot.classes), 'collection_mode': snapshot.collection_mode,
            'collection_subtotal': plain(subtotal), 'collection_amount': plain(amount),
            'collection_discount': plain(subtotal - amount), 'currency': snapshot.pricing.currency,
            'pricing_version': snapshot.pricing.version,
            'lines': [{'title': line.title, 'classes': plain(line.classes), 'total': plain(line.total)} for line in snapshot.lines]}


@transaction.atomic
def create(actor, student_id, data, request=None):
    """A new Sale, quote and purchase on the student's account. Earlier sales are untouched."""
    student, account = _student(actor, student_id, request)
    account = StudentAccount.objects.select_for_update().get(pk=account.pk)
    existing = Sale.objects.filter(pk=data['request_id']).first()
    if existing is not None:
        if existing.account_id != account.pk or existing.kind != SaleKind.ADDITIONAL or existing.created_by_id != actor.pk:
            raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID belongs to another purchase.', 409)
        return existing
    found = blockers(account)
    if found:
        raise refusal(found[0]['code'], found[0]['message'], 409, blockers=found)
    # As a quote is issued (quotes.create_quote): the syllabus cannot be republished meanwhile,
    # and the figures the mentor reviewed are the ones issued.
    Syllabus.objects.select_for_update().filter(pk=data['syllabus']).first()
    snapshot = _snapshot(actor, account, data)
    if data.get('pricing_version') is not None and snapshot.pricing.version != data['pricing_version']:
        raise refusal('PRICING_CHANGED', 'Pricing changed meanwhile. Review the new amount before adding the purchase.')
    if snapshot.pricing.currency != 'AED':
        raise refusal('AED_REQUIRED', 'Additional purchases are collected in AED.')
    quote = quotes.issue(snapshot)
    amount, classes = payments.purchase_terms(quote, snapshot.collection_mode)
    guardian = billing_guardian(account)
    sale = Sale.objects.create(id=data['request_id'], account=account, kind=SaleKind.ADDITIONAL, student=student,
                               created_by=actor, original_quote=quote, parent_email=guardian.email if guardian else '')
    Purchase.objects.create(id=uuid.uuid5(sale.pk, 'initial-purchase'), sale=sale, quote=quote, student=student,
                            collection_mode=snapshot.collection_mode, amount=amount, classes=classes)
    payments.audit('sale.additional_purchase', sale, actor, request, quote=str(quote.pk), account=account.reference,
                   classes=plain(classes), amount=plain(amount))
    return sale


def state(actor, sale_id, request=None):
    sale = _sale(actor, sale_id, request)
    purchase = Purchase.objects.select_related('quote').get(sale=sale, is_initial=True)
    paid = payments.received(sale)
    rows = list(sale.payments.select_related('recorded_by', 'sale'))
    pending = any(row.status == PaymentStatus.PENDING for row in rows)
    return {
        'sale': {'id': str(sale.pk), 'kind': sale.kind, 'created_at': sale.created_at.isoformat(),
                 'created_by': {'id': str(sale.created_by_id), 'name': sale.created_by.full_name or sale.created_by.username}},
        'student': {'id': str(sale.student_id), 'student_code': sale.student.student_code, 'full_name': sale.student.full_name},
        'account': account_data(sale.account, actor, request),
        'quote': quotes.quote_data(purchase.quote),
        'purchase': {'id': str(purchase.pk), 'collection_mode': purchase.collection_mode},
        'totals': {'purchased_classes': plain(purchase.classes), 'paid_classes': plain(paid['classes']),
                   'unpaid_classes': plain(purchase.classes - paid['classes']), 'package_amount': plain(purchase.amount),
                   'paid_amount': plain(paid['amount']), 'outstanding_amount': plain(purchase.amount - paid['amount']),
                   'fully_paid': paid['amount'] >= purchase.amount,
                   # No rule credits an additional purchase's classes yet (a decision is pending).
                   'classes_not_credited': plain(paid['classes'])},
        'payments': [payments.payment_data(row) for row in rows],
        'can_collect': purchase.classes - paid['classes'] > 0 and not pending,
        'stripe_configured': payments.stripe_configured(),
    }


def amount(actor, sale_id, data, request=None):
    sale = _sale(actor, sale_id, request)
    purchase = Purchase.objects.get(sale=sale, is_initial=True)
    paid = payments.received(sale)
    due, classes = payments.allocation(purchase.amount, purchase.classes, paid, data['classes'], purchase.collection_mode)
    return {'amount': plain(due), 'classes': plain(classes), 'currency': 'AED', 'package_amount': plain(purchase.amount),
            'remaining_amount': plain(purchase.amount - paid['amount'] - due),
            'remaining_classes': plain(purchase.classes - paid['classes'] - classes)}


def collect(actor, sale_id, data, request=None):
    """A one-time Stripe Checkout link for this purchase; the amount is calculated here, never sent."""
    _sale(actor, sale_id, request)  # Refuse before opening the transaction; checked again under the lock.
    with transaction.atomic(durable=True):
        sale = _sale(actor, sale_id, request, lock=True)
        existing = Payment.objects.filter(request_id=data['request_id']).first()
        if existing is not None:
            if existing.sale_id != sale.pk or existing.recorded_by_id != actor.pk or existing.classes != data['classes']:
                raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for a different collection.', 409)
            return existing
        if AutopayAgreement.objects.filter(purchase__sale=sale).exists():
            raise refusal('AUTOPAY_EXISTS', 'This purchase is collected by its Autopay agreement.', 409)
        if sale.payments.filter(status=PaymentStatus.PENDING).exists():
            raise refusal('PAYMENT_PENDING', 'A payment link is still pending. Let it complete or expire it first.', 409)
        if not payments.stripe_configured():
            raise refusal('STRIPE_NOT_CONFIGURED', 'Configure matching Stripe credentials before collecting through Stripe.', 503)
        purchase = Purchase.objects.get(sale=sale, is_initial=True)
        due, classes = payments.allocation(purchase.amount, purchase.classes, payments.received(sale), data['classes'],
                                           purchase.collection_mode)
        payment = Payment(id=data['request_id'], request_id=data['request_id'], sale=sale, purchase=purchase, purpose='TUITION',
                          method=PaymentMethod.STRIPE, collection_mode=purchase.collection_mode, amount=due, classes=classes,
                          recorded_by=actor)
        payment.save(force_insert=True)
        lock_identity(sale.account)
        from .checkout import prepare
        prepare(payment)
        payments.audit('payment.create', sale, actor, request, payment=str(payment.pk), amount=plain(due),
                       classes=plain(classes), method=payment.method)
    from .stripe_gateway import create_checkout
    create_checkout(payment)
    payment.refresh_from_db()
    return payment


def expire(actor, sale_id, payment_id, request=None):
    """Expire this purchase's unpaid link: its student's mentor or an administrator."""
    from .stripe_gateway import expire_locked
    with transaction.atomic():
        sale = _sale(actor, sale_id, request, lock=True)
        payment = Payment.objects.select_for_update().select_related('sale').filter(pk=payment_id, sale=sale).first()
        if payment is None:
            raise refusal('NOT_FOUND', 'No such payment.', 404)
        return expire_locked(actor, payment, request)
