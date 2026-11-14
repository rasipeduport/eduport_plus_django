"""Student finance: every purchase on an enrolled student's account, for their mentor or an administrator.

After enrollment the student's purchases -- the initial sale and each additional
purchase -- are collected here, never from the enquiry (payments.enrolled_refusal).
Nothing here computes money of its own: amounts come from payments.allocation,
direct receipts pass payments.check_receipt and store_proof as the BDE's do, and
payments.succeed settles them. A payment collected here records money only, as
the existing class-credit rules say: enrollment credits the initial tuition, and
Autopay installments credit their own classes.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import autopay, payments, quotes
from .additional_purchases import blockers, sale_summary, student_and_account
from .autopay_models import AutopayAgreement, AutopayInstallment
from .ledger_models import Refund
from .payment_models import Payment, PaymentMethod, PaymentStatus, Purchase, Sale, SaleKind
from .pricing import plain
from .student_accounts import account_data, lock_identity, refusal

ZERO = Decimal('0')
# Refunds still open or settled; until a refund policy is approved they change neither balances nor classes.
COUNTED_REFUNDS = ['succeeded', 'pending', 'requires_action']


def enrolled_sale(actor, sale_id, request=None, lock=False):
    """A sale of one of ``actor``'s enrolled students (any student's, for an administrator)."""
    sale = Sale.objects.select_related('student', 'account', 'created_by').filter(pk=sale_id, student__isnull=False).first()
    if sale is None:
        raise refusal('NOT_FOUND', 'No such purchase.', 404)
    student_and_account(actor, sale.student_id, request)
    if lock:
        from .stripe_gateway import lock_sale
        sale = lock_sale(sale)
    return sale


def _purchase(sale):
    purchase = Purchase.objects.select_related('quote').filter(sale=sale, is_initial=True).first()
    if purchase is None:
        raise refusal('NOT_FOUND', 'This sale has no purchase to collect.', 404)
    return purchase


def _installments(rows):
    return {row.payment_id: row for row in AutopayInstallment.objects.filter(payment__in=rows)}


def not_credited(rows):
    """Received tuition the existing class-credit rules did not add to the student's quota."""
    installments = _installments(rows)
    return sum((row.classes for row in rows if row.purpose == 'TUITION' and row.status == PaymentStatus.SUCCEEDED
                and not payments.classes_credited(row, installments.get(row.pk))), ZERO)


def payment_type(payment, installment):
    if payment.purpose == 'TOKEN':
        return 'TOKEN'
    if installment is not None:
        return 'AUTOPAY_INSTALLMENT' if installment.position > 0 else 'AUTOPAY_INITIAL'
    if payment.sale.kind == SaleKind.ADDITIONAL:
        return 'ADDITIONAL'
    enrolled_at = payment.sale.enrolled_at
    return 'BALANCE' if enrolled_at and payment.created_at > enrolled_at else 'INITIAL'


def history_rows(rows):
    """Payments as the Finance tab lists them: the payment itself, which purchase it paid, and its receipt."""
    installments = _installments(rows)
    references = {purchase.sale_id: purchase.quote.reference for purchase in Purchase.objects.select_related('quote')
                  .filter(sale__in={row.sale_id for row in rows}, is_initial=True)}
    data = []
    for row in rows:
        data.append({
            **payments.payment_data(row),
            'sale_id': str(row.sale_id), 'purchase_kind': row.sale.kind,
            'purchase_reference': references.get(row.sale_id) or row.sale.reservation_reference,
            'payment_type': payment_type(row, installments.get(row.pk)),
            'created_at': row.created_at.isoformat(),
            # The student's mentor reads receipts here; the enquiry's route stays the BDE's.
            'proof_url': f'/api/sales/purchases/{row.sale_id}/payments/{row.pk}/proof/' if row.proof else None,
        })
    return data


def autopay_brief(agreement):
    """An Autopay agreement at a glance; managing it is the AutoPay tab's."""
    data = autopay.agreement_data(agreement)
    rows = data['installments']
    return {'id': data['id'], 'sale_id': str(agreement.purchase.sale_id), 'reference': agreement.purchase.quote.reference,
            'status': data['status'], 'attention_status': data['attention_status'], 'billing_timezone': data['billing_timezone'],
            'next_collection_at': data['next_collection_at'], 'package_amount': data['package_amount'],
            'remaining_amount': data['remaining_amount'], 'installments_total': len(rows),
            'installments_paid': sum(1 for row in rows if row['status'] == 'PAID'),
            'card_brand': data['card_brand'], 'card_last4': data['card_last4'], 'cancelled_at': data['cancelled_at']}


def finance(actor, student_id, request=None):
    """The student's purchases, balances and Autopay, all from the purchase and payment records."""
    student, account = student_and_account(actor, student_id, request)
    sales = list(account.sales.order_by('created_at'))
    rows = [sale_summary(sale) for sale in sales]
    bought = [row for row in rows if row['package_amount'] is not None]

    def total(key):
        return sum((Decimal(row[key]) for row in bought), ZERO)

    received = list(Payment.objects.filter(sale__account=account, status=PaymentStatus.SUCCEEDED).select_related('sale'))
    refunded = Refund.objects.filter(payment__sale__account=account, status__in=COUNTED_REFUNDS).aggregate(n=Sum('amount'))['n'] or ZERO
    agreements = AutopayAgreement.objects.filter(purchase__sale__account=account).select_related(
        'purchase__quote', 'created_by').order_by('created_at')
    found = blockers(account)
    return {
        'student': {'id': str(student.pk), 'student_code': student.student_code, 'full_name': student.full_name},
        'account': account_data(account, actor, request),
        'summary': {
            'purchased_classes': plain(total('classes')), 'paid_classes': plain(total('paid_classes')),
            'pending_classes': plain(total('outstanding_classes')), 'total_amount': plain(total('package_amount')),
            'paid_amount': plain(total('paid_amount')), 'pending_amount': plain(total('outstanding_amount')),
            # What may be collected now; the rest is on Autopay or awaiting an open link.
            'collectible_amount': plain(sum((Decimal(row['outstanding_amount']) for row in bought if row['can_collect']), ZERO)),
            'autopay_amount': plain(sum((Decimal(row['outstanding_amount']) for row in bought if row['autopay_status']), ZERO)),
            'class_quota': plain(student.total_class_quota), 'classes_not_credited': plain(not_credited(received)),
            'refunded_amount': plain(refunded),
        },
        'purchases': rows,
        'autopay': [autopay_brief(agreement) for agreement in agreements],
        'blockers': found, 'can_add': not found,
        'can_collect': any(row['can_collect'] for row in rows),
        'stripe_configured': payments.stripe_configured(),
    }


def payment_history(actor, student_id, request=None, sale_id=None, status=None, method=None):
    """Every payment on the student's account, newest first, optionally of one purchase, status or method."""
    _student, account = student_and_account(actor, student_id, request)
    rows = Payment.objects.filter(sale__account=account).select_related('sale', 'recorded_by').order_by('-created_at', '-pk')
    if sale_id:
        rows = rows.filter(sale_id=sale_id)
    if status:
        rows = rows.filter(status=status)
    if method:
        rows = rows.filter(method=method)
    return rows


def state(actor, sale_id, request=None):
    """One purchase of the student's: its plan, totals, payments and whether it can be collected now."""
    sale = enrolled_sale(actor, sale_id, request)
    purchase = _purchase(sale)
    paid = payments.received(sale)
    summary = sale_summary(sale)
    rows = list(sale.payments.select_related('recorded_by', 'sale').order_by('created_at', 'pk'))
    agreement = AutopayAgreement.objects.select_related('purchase__quote', 'created_by').filter(purchase=purchase).first()
    return {
        'sale': {'id': str(sale.pk), 'kind': sale.kind, 'created_at': sale.created_at.isoformat(),
                 'enrolled_at': sale.enrolled_at.isoformat() if sale.enrolled_at else None,
                 'created_by': {'id': str(sale.created_by_id), 'name': sale.created_by.full_name or sale.created_by.username}},
        'student': {'id': str(sale.student_id), 'student_code': sale.student.student_code, 'full_name': sale.student.full_name},
        'account': account_data(sale.account, actor, request),
        'quote': quotes.quote_data(purchase.quote),
        'purchase': {'id': str(purchase.pk), 'collection_mode': purchase.collection_mode},
        'totals': {'purchased_classes': plain(purchase.classes), 'paid_classes': plain(paid['classes']),
                   'unpaid_classes': plain(purchase.classes - paid['classes']), 'package_amount': plain(purchase.amount),
                   'paid_amount': plain(paid['amount']), 'outstanding_amount': plain(purchase.amount - paid['amount']),
                   'fully_paid': paid['amount'] >= purchase.amount, 'classes_not_credited': plain(not_credited(rows))},
        'payments': history_rows(rows),
        'payment_status': summary['payment_status'],
        'autopay': autopay_brief(agreement) if agreement else None,
        'can_collect': summary['can_collect'],
        'stripe_configured': payments.stripe_configured(),
    }


def amount(actor, sale_id, data, request=None):
    sale = enrolled_sale(actor, sale_id, request)
    purchase = _purchase(sale)
    paid = payments.received(sale)
    due, classes = payments.allocation(purchase.amount, purchase.classes, paid, data['classes'], purchase.collection_mode)
    return {'amount': plain(due), 'classes': plain(classes), 'currency': 'AED', 'package_amount': plain(purchase.amount),
            'remaining_amount': plain(purchase.amount - paid['amount'] - due),
            'remaining_classes': plain(purchase.classes - paid['classes'] - classes)}


def collect(actor, sale_id, data, request=None):
    """A one-time Stripe link, or a direct receipt with its proof, for some or all of a purchase's unpaid classes.

    The amount is always calculated here from the purchase; a receipt must state exactly that amount.
    """
    enrolled_sale(actor, sale_id, request)  # Refuse before opening the transaction; checked again under the lock.
    if data['method'] != PaymentMethod.STRIPE:
        return _record(actor, sale_id, data, request)
    # No provider call may run before its immutable local origin commits.
    with transaction.atomic(durable=True):
        payment = _record(actor, sale_id, data, request)
    from .stripe_gateway import create_checkout
    create_checkout(payment)
    payment.refresh_from_db()
    return payment


def _record(actor, sale_id, data, request=None):
    stored_proof = None
    direct = data['method'] != PaymentMethod.STRIPE
    try:
        with transaction.atomic():
            sale = enrolled_sale(actor, sale_id, request, lock=True)
            existing = Payment.objects.filter(request_id=data['request_id']).first()
            if existing is not None:
                if not payments.same_collection(existing, sale, actor, data):
                    raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for a different collection.', 409)
                return existing
            purchase = _purchase(sale)
            if AutopayAgreement.objects.filter(purchase=purchase).exists():
                raise refusal('AUTOPAY_EXISTS', 'This purchase is collected by its Autopay agreement.', 409)
            if sale.payments.filter(status=PaymentStatus.PENDING).exists():
                raise refusal('PAYMENT_PENDING', 'A payment link is still pending. Let it complete or expire it first.', 409)
            if not direct and not payments.stripe_configured():
                raise refusal('STRIPE_NOT_CONFIGURED', 'Configure matching Stripe credentials before collecting through Stripe.', 503)
            due, classes = payments.allocation(purchase.amount, purchase.classes, payments.received(sale), data['classes'],
                                               purchase.collection_mode)
            if direct:
                payments.check_receipt(data, due)
            payment = Payment(id=data['request_id'], request_id=data['request_id'], sale=sale, purchase=purchase, purpose='TUITION',
                              method=data['method'], collection_mode=purchase.collection_mode, amount=due, classes=classes,
                              recorded_by=actor, payment_date=data.get('payment_date') or timezone.localdate(),
                              received_confirmed=data.get('received_confirmed', False) if direct else False,
                              transaction_reference=data.get('transaction_reference', '') if direct else '')
            if direct:
                stored_proof = payments.store_proof(payment, data['proof'])
            payment.save(force_insert=True)
            lock_identity(sale.account)
            if direct:
                # Received money is final at once; the existing rules credit no classes for it.
                payments.succeed(payment, actor, request)
            else:
                from .checkout import prepare
                prepare(payment)
            payments.audit('payment.create', sale, actor, request, payment=str(payment.pk), amount=plain(due),
                           classes=plain(classes), method=payment.method)
            return payment
    except Exception:
        if stored_proof:
            stored_proof.storage.delete(stored_proof.name)
        raise


def expire(actor, sale_id, payment_id, request=None):
    """Expire a purchase's unpaid link: its student's mentor or an administrator."""
    from .stripe_gateway import expire_locked
    with transaction.atomic():
        sale = enrolled_sale(actor, sale_id, request, lock=True)
        payment = Payment.objects.select_for_update().select_related('sale').filter(pk=payment_id, sale=sale).first()
        if payment is None:
            raise refusal('NOT_FOUND', 'No such payment.', 404)
        return expire_locked(actor, payment, request)


def proof(actor, sale_id, payment_id, request=None):
    """A payment's receipt, for the student's mentor or an administrator."""
    sale = enrolled_sale(actor, sale_id, request)
    payment = Payment.objects.filter(pk=payment_id, sale=sale).exclude(proof='').first()
    if payment is None:
        raise refusal('NOT_FOUND', 'No such receipt.', 404)
    return payment
