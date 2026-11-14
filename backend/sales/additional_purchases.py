"""Additional purchases: a Mentor's further purchase for one of their enrolled students.

Each one is a NEW Sale (kind ADDITIONAL) on the student's existing StudentAccount,
with its own quote, purchase and payments; earlier sales are never changed, and
the student's one Stripe Customer is reused. The quote is priced exactly as any
quote (sales.quotes), so existing pricing rules apply unchanged. Collecting any
of the student's purchases is sales.student_finance's.

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
from .payment_models import PaymentStatus, Purchase, Sale, SaleKind
from .pricing import plain
from .student_accounts import billing_guardian, is_admin, refusal

PERMISSION = 'accounts.create_additional_purchases'


def student_and_account(actor, student_id, request=None):
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


def sale_summary(sale):
    """One sale of the student's account as the Finance tab lists it: plan, amounts, balance and how it is collected."""
    purchase = Purchase.objects.select_related('quote__revision').filter(sale=sale, is_initial=True).first()
    paid = payments.received(sale)
    agreement = AutopayAgreement.objects.filter(purchase=purchase).first() if purchase else None
    amount = purchase.amount if purchase else None
    outstanding = purchase.classes - paid['classes'] if purchase else None
    fully_paid = amount is not None and paid['amount'] >= amount
    link_pending = sale.payments.filter(status=PaymentStatus.PENDING).exists()
    if fully_paid:
        status = 'PAID'
    elif agreement is not None:
        status = 'AUTOPAY'
    elif link_pending:
        status = 'LINK_PENDING'
    else:
        status = 'PARTIALLY_PAID' if paid['amount'] > 0 else 'UNPAID'
    return {
        'id': str(sale.pk), 'kind': sale.kind, 'created_at': sale.created_at.isoformat(),
        'enrolled_at': sale.enrolled_at.isoformat() if sale.enrolled_at else None,
        'quote_id': str(purchase.quote_id) if purchase else None,
        'quote_reference': purchase.quote.reference if purchase else None,
        'syllabus': purchase.quote.revision.title if purchase else None,
        'plan_type': purchase.quote.plan_type if purchase else None,
        'class_mode': quotes._class_mode(purchase.quote) if purchase else None,
        'full_course': purchase.quote.full_course if purchase else None,
        'collection_mode': purchase.collection_mode if purchase else None,
        'classes': plain(purchase.classes) if purchase else None,
        'paid_classes': plain(paid['classes']), 'outstanding_classes': plain(outstanding) if purchase else None,
        'package_amount': plain(amount) if amount is not None else None, 'paid_amount': plain(paid['amount']),
        'outstanding_amount': plain(amount - paid['amount']) if amount is not None else None,
        'fully_paid': fully_paid, 'payment_status': status, 'link_pending': link_pending,
        'autopay_status': agreement.status if agreement else None,
        # What the Finance tab may collect: unpaid classes, no open link, and no Autopay owning the balance.
        'can_collect': bool(purchase) and outstanding > 0 and agreement is None and not link_pending,
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
    student, account = student_and_account(actor, student_id, request)
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
    _student_record, account = student_and_account(actor, student_id, request)
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
    student, account = student_and_account(actor, student_id, request)
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
