"""Phase 1 initial sales. All amounts/allocations are calculated under the enquiry lock."""
import os
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from bookings.models import Lead
from . import quotes
from .models import QuoteStatus
from .payment_models import CollectionMode, Payment, PaymentMethod, PaymentStatus, Purchase, Sale, SaleKind
from .pricing import Package, plain
from .services import SalesError

MANAGE = 'accounts.manage_initial_sales'
ZERO = Decimal('0')
TOKEN_AMOUNT = Decimal('100')


def whole(value):
    return Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def refusal(code, message, status=400):
    return SalesError(code, message, status)


def accessible_lead(actor, enquiry_id, request=None, lock=False):
    if not has_app_permission(actor, MANAGE, request):
        raise refusal('FORBIDDEN', 'Initial sales access is required.', 403)
    rows = Lead.objects.all()
    if not has_app_permission(actor, 'accounts.manage_sales_quotes', request):
        rows = rows.filter(owner_bde=actor)
    lead = (rows.select_for_update() if lock else rows).filter(pk=enquiry_id).first()
    if lead is None:
        raise refusal('NOT_FOUND', 'No such enquiry.', 404)
    return lead


def current_quote(actor, lead, request=None, optional=False):
    quote = quotes.latest_quote(lead)
    if not quote or quote.status != QuoteStatus.ISSUED:
        if optional:
            return None
        raise refusal('QUOTE_REQUIRED', 'Choose a plan and issue a quote first.')
    if quote.created_by_id != actor.pk and not has_app_permission(actor, quotes.MANAGE_QUOTES, request):
        raise refusal('PLAN_OWNER_CHANGED', 'An administrator must review the previous owner’s quote.', 409)
    if quote.currency != 'AED':
        raise refusal('AED_REQUIRED', 'This workflow accepts AED quotes only.')
    return quote


def received(sale):
    paid = sale.payments.filter(Q(purpose='TOKEN') | Q(purchase__is_initial=True), status=PaymentStatus.SUCCEEDED)
    return {
        'classes': paid.filter(purpose='TUITION').aggregate(n=Sum('classes'))['n'] or ZERO,
        'amount': paid.aggregate(n=Sum('amount'))['n'] or ZERO,
        'token': paid.filter(purpose='TOKEN').aggregate(n=Sum('amount'))['n'] or ZERO,
    }


def token_state(sale, paid, today=None):
    if sale.kind != SaleKind.TOKEN:
        return None
    if sale.student_id:
        return 'ENROLLED'
    if not paid['token']:
        return 'AWAITING_PAYMENT'
    today = today or timezone.localdate()
    if sale.expected_start_date < today:
        return 'OVERDUE'
    return 'DUE' if sale.expected_start_date <= today + timedelta(days=3) else 'UPCOMING'


def has_collection_history(lead):
    """Any purchase or collection pins history, including unsuccessful attempts."""
    return (Purchase.objects.filter(sale__enquiry=lead).exists()
            or Payment.objects.filter(sale__enquiry=lead).exists())


def require_token_quote(quote):
    if quote and quote.collection_mode == 'AUTOPAY':
        raise refusal('TOKEN_AUTOPAY_NOT_ALLOWED',
            'Token Sale requires a FULL or PARTIAL quote. Issue an explicit replacement quote before continuing.', 409)


def require_compatible_quote(lead, quote, kind):
    if quote and not quote.collection_intention_confirmed and not has_collection_history(lead):
        raise refusal('COLLECTION_INTENTION_REQUIRED',
            'This historical quote has no recorded collection intention. Issue an explicit replacement quote with FULL, PARTIAL or AUTOPAY before starting or collecting the sale.', 409)
    if kind == SaleKind.TOKEN:
        require_token_quote(quote)


@transaction.atomic
def start_sale(actor, enquiry_id, data, request=None):
    lead = accessible_lead(actor, enquiry_id, request, lock=True)
    existing = Sale.objects.filter(enquiry=lead).first()
    if existing:
        if existing.kind != data['kind']:
            raise refusal('SALE_EXISTS', 'This enquiry already has an initial sale.', 409)
        if has_collection_history(lead):
            # Idempotent reads of existing frozen sales must not reprice them.
            return existing
    if not lead.owner_bde_id:
        raise refusal('BDE_REQUIRED', 'Assign the responsible BDE before starting a sale.')
    kind = data['kind']
    quote = current_quote(actor, lead, request, optional=kind == SaleKind.TOKEN)
    require_compatible_quote(lead, quote, kind)
    if existing:
        return existing
    expected = data.get('expected_start_date')
    reference = None
    if kind == SaleKind.TOKEN:
        if expected is None or expected < timezone.localdate():
            raise refusal('START_DATE_REQUIRED', 'Choose today or a future expected class start date.')
        if quote and whole(quote.payable_amount) <= TOKEN_AMOUNT:
            raise refusal('TOKEN_EXCEEDS_PACKAGE', 'A token reservation requires a package worth more than AED 100.')
        from .enrollment import next_number
        reference = f'TOK{next_number("TOKEN"):06d}'
    sale = Sale.objects.create(
        enquiry=lead, original_bde=lead.owner_bde, created_by=actor, original_quote=quote,
        kind=kind, expected_start_date=expected if kind == SaleKind.TOKEN else None,
        reservation_reference=reference, parent_email=(lead.parent_email or '').lower().strip(),
    )
    audit('sale.create', sale, actor, request, kind=kind, quote=str(quote.pk) if quote else None)
    return sale


def _replacement_snapshot(actor, lead, expected_quote_id, collection_mode, request=None):
    if collection_mode not in ('FULL', 'PARTIAL', 'AUTOPAY'):
        raise refusal('INVALID_COLLECTION_MODE', 'Choose the replacement quote collection intention.')
    old = current_quote(actor, lead, request)
    if str(old.pk) != str(expected_quote_id):
        raise refusal('PLAN_CHANGED', 'The quote changed. Refresh the enquiry.', 409)
    if lead.plan_changes_locked_at:
        raise refusal('PLAN_LOCKED', 'Payment collection has already pinned this plan.', 409)
    from .pricing import single_payment_price
    from types import SimpleNamespace
    rates = SimpleNamespace(single_payment_percent=old.single_payment_percent,
                            single_payment_plan_types=old.pricing_version.single_payment_plan_types)
    lines = [Package(line.plan_type, line.title, line.classes, line.fee_per_class, line.total,
                     single_payment_price(line.total, rates, line.plan_type) if collection_mode == 'FULL' else None)
             for line in old.lines.order_by('position')]
    saving = sum((line.single_payment[1] for line in lines if line.single_payment), ZERO)
    snapshot = quotes.QuoteSnapshot(
        owner=actor, lead=lead, revision=old.revision, pricing=old.pricing_version,
        plan_type=old.plan_type, full_course=old.full_course, lines=lines,
        chapters=[(row.chapter, row.classes) for row in old.chapters.select_related('chapter').order_by('chapter__position')],
        classes=old.classes, total_fee=old.total_fee, single_payment_saving=saving, payable_amount=old.total_fee - saving,
        supersedes=old, class_mode=quotes._class_mode(old), collection_mode=collection_mode,
    )
    quotes.validate_sale_snapshot(lead, snapshot)
    return snapshot


def preview_collection_replacement(actor, enquiry_id, expected_quote_id, collection_mode, request=None):
    lead = accessible_lead(actor, enquiry_id, request)
    snapshot = _replacement_snapshot(actor, lead, expected_quote_id, collection_mode, request)
    return {'quote_id': str(snapshot.supersedes.pk), 'collection_mode': collection_mode,
            'collection_subtotal': plain(whole(snapshot.total_fee)),
            'collection_amount': plain(whole(snapshot.payable_amount)),
            'collection_discount': plain(whole(snapshot.total_fee) - whole(snapshot.payable_amount)),
            'pricing_version': snapshot.pricing.version, 'classes': plain(snapshot.classes)}


@transaction.atomic
def installment_replacement(actor, enquiry_id, expected_quote_id, collection_mode, request=None):
    """Explicit collection-intention replacement using the original frozen terms."""
    lead = accessible_lead(actor, enquiry_id, request, lock=True)
    snapshot = _replacement_snapshot(actor, lead, expected_quote_id, collection_mode, request)
    new = quotes.issue(snapshot)
    audit('quote.collection_replacement', Sale.objects.filter(enquiry=lead).first(), actor, request,
          enquiry=str(lead.pk), original_quote=str(snapshot.supersedes.pk), quote=str(new.pk), collection_mode=collection_mode)
    return new


def require_quote_intention(quote, intention):
    if intention not in ('FULL', 'PARTIAL', 'AUTOPAY'):
        raise refusal('INVALID_COLLECTION_MODE', 'Choose a valid collection intention.')
    if quote.collection_mode != intention:
        raise refusal('COLLECTION_MODE_LOCKED', 'The issued quote fixes the collection intention. Issue an explicit replacement quote before changing it.', 409)


def purchase_terms(quote, collection_mode, *, intention=None):
    if collection_mode not in CollectionMode.values:
        raise refusal('INVALID_COLLECTION_MODE', 'Choose full or partial payment.')
    if collection_mode == CollectionMode.PARTIAL and quote.single_payment_saving > 0:
        raise refusal('REPLACEMENT_REQUIRED', 'Create a replacement quote without the single-payment discount before collecting installments.', 409)
    require_quote_intention(quote, intention or collection_mode)
    amount = quotes._collection_amount(quote)
    if amount <= 0:
        raise refusal('INVALID_PACKAGE', 'The rounded package amount must be positive.')
    return amount, quote.classes


def allocation(amount, total_classes, paid, classes, collection_mode):
    try:
        classes = Decimal(str(classes))
        valid = classes.is_finite() and classes > 0 and classes % Decimal('0.5') == 0
    except (ArithmeticError, ValueError, TypeError):
        valid = False
    if not valid or classes > total_classes - paid['classes']:
        raise refusal('INVALID_ALLOCATION', 'Choose a positive whole or half class count within the unpaid classes.')
    if collection_mode == CollectionMode.FULL and classes != total_classes - paid['classes']:
        raise refusal('FULL_PAYMENT_REQUIRED', 'Full payment must cover all unpaid classes. Use an installment quote for partial collection.', 409)
    cumulative = paid['classes'] + classes
    target = amount if cumulative == total_classes else whole(amount * cumulative / total_classes)
    due = target - paid['amount']
    if cumulative < total_classes and target >= amount:
        raise refusal('INVALID_ALLOCATION', 'This allocation rounds to the full package amount. Cover all remaining classes instead.')
    if due <= 0 or due > amount - paid['amount']:
        raise refusal('INVALID_ALLOCATION', 'The selected classes must require a positive tuition payment after token credit. Choose more classes.')
    return due, classes


def preview_collection(actor, enquiry_id, data, request=None):
    lead = accessible_lead(actor, enquiry_id, request)
    sale = Sale.objects.filter(enquiry=lead).first()
    if not sale:
        raise refusal('SALE_REQUIRED', 'Start the sale first.')
    if sale.student_id:
        raise refusal('ALREADY_ENROLLED', 'Further payment collection belongs to the enrolled-student workflow.', 403)
    purchase = Purchase.objects.filter(sale=sale, is_initial=True).first()
    quote = purchase.quote if purchase else current_quote(actor, lead, request, optional=data['purpose'] == 'TOKEN')
    if not purchase:
        require_compatible_quote(lead, quote, sale.kind)
    paid = received(sale)
    if data['purpose'] == 'TOKEN':
        if sale.kind != SaleKind.TOKEN or paid['token']:
            raise refusal('INVALID_TOKEN', 'This sale has no unpaid token reservation.')
        return {'amount': '100', 'classes': '0', 'currency': 'AED'}
    if sale.kind == SaleKind.TOKEN and not paid['token']:
        raise refusal('TOKEN_UNPAID', 'Confirm the token payment before collecting reservation tuition.')
    mode = data['collection_mode']
    if quote.created_by_id != actor.pk and not has_app_permission(actor, quotes.MANAGE_QUOTES, request):
        raise refusal('PLAN_OWNER_CHANGED', 'An administrator must review the previous owner’s quote.', 409)
    if purchase and purchase.collection_mode != mode:
        raise refusal('COLLECTION_MODE_LOCKED', 'Use the collection mode already pinned to this purchase.', 409)
    amount, classes = (purchase.amount, purchase.classes) if purchase else purchase_terms(quote, mode, intention='AUTOPAY' if data.get('_autopay_snapshot') else mode)
    due, selected = allocation(amount, classes, paid, data['classes'], mode)
    return {'amount': plain(due), 'classes': plain(selected), 'currency': 'AED', 'package_amount': plain(amount),
            'remaining_amount': plain(amount - paid['amount'] - due), 'remaining_classes': plain(classes - paid['classes'] - selected)}


def payment_data(payment):
    from .autopay_models import AutopayInstallment
    installment = AutopayInstallment.objects.filter(payment=payment).first()
    latest = installment.attempts.order_by('-number').first() if installment and installment.position == 0 else None
    return {
        'id': str(payment.pk), 'purpose': payment.purpose, 'method': payment.method,
        'method_label': 'Stripe · Autopay' if installment and installment.position > 0 else payment.get_method_display(), 'collection_mode': payment.collection_mode,
        'amount': plain(payment.amount), 'currency': payment.currency, 'classes': plain(payment.classes),
        'status': payment.status, 'payment_date': payment.payment_date.isoformat(),
        'transaction_reference': payment.transaction_reference, 'received_confirmed': payment.received_confirmed,
        'recorded_by': {'id': str(payment.recorded_by_id), 'name': payment.recorded_by.full_name or payment.recorded_by.username},
        'proof_name': payment.proof_name,
        'proof_url': f'/api/sales/payments/{payment.pk}/proof/' if payment.proof else None,
        'stripe_customer_id': payment.stripe_customer_id or None,
        'stripe_checkout_id': latest.stripe_checkout_id if latest else payment.stripe_checkout_id,
        'payment_url': latest.checkout_url if latest else payment.payment_url or None,
        'collection_source': 'AUTOPAY' if installment and installment.position > 0 else 'INITIAL_AUTOPAY' if installment else 'INITIAL',
        'stripe_payment_intent': payment.stripe_payment_intent,
        'stripe_invoice_id': installment.stripe_invoice_id if installment else None,
        'stripe_invoice_status': installment.stripe_invoice_status if installment else None,
        'verified_at': payment.verified_at.isoformat() if payment.verified_at else None,
    }


def sale_data(actor, enquiry_id, request=None):
    from . import autopay
    from .autopay_models import AutopayAgreement
    lead = accessible_lead(actor, enquiry_id, request)
    sale = Sale.objects.select_related('student', 'original_bde').filter(enquiry=lead).first()
    quote = quotes.latest_quote(lead)
    purchase = Purchase.objects.select_related('quote').filter(sale=sale, is_initial=True).first() if sale else None
    if purchase:
        quote = purchase.quote
    if quote and quote.currency != 'AED':
        raise refusal('AED_REQUIRED', 'This workflow accepts AED quotes only.')
    if quote and quote.created_by_id != actor.pk and not has_app_permission(actor, quotes.MANAGE_QUOTES, request):
        raise refusal('PLAN_OWNER_CHANGED', 'An administrator must review the previous owner’s quote.', 409)
    paid = received(sale) if sale else {'amount': ZERO, 'classes': ZERO, 'token': ZERO}
    amount = purchase.amount if purchase else whole(quote.payable_amount) if quote and quote.status == 'ISSUED' else None
    classes = purchase.classes if purchase else quote.classes if quote and quote.status == 'ISSUED' else ZERO
    from sessions.services import calculate_credits_used
    used = Decimal(str(calculate_credits_used(sale.student))) if sale and sale.student_id else ZERO
    can_collect = not (sale and sale.student_id)
    if can_collect and not purchase:
        try:
            require_compatible_quote(lead, quote, sale.kind if sale else SaleKind.NEW)
        except SalesError:
            can_collect = False
    return {
        'enquiry_id': str(lead.pk), 'quote': quotes.quote_data(quote) if quote else None,
        'sale': {
            'id': str(sale.pk), 'kind': sale.kind, 'reservation_reference': sale.reservation_reference,
            'expected_start_date': sale.expected_start_date.isoformat() if sale.expected_start_date else None,
            'token_status': token_state(sale, paid), 'token_paid': plain(paid['token']),
            'parent_email': sale.parent_email,
            'original_bde': {'id': str(sale.original_bde_id), 'name': sale.original_bde.full_name or sale.original_bde.username},
            'original_quote_id': str(sale.original_quote_id) if sale.original_quote_id else None,
            'student': {'id': str(sale.student_id), 'student_code': sale.student.student_code} if sale.student_id else None,
        } if sale else None,
        'purchase': {'id': str(purchase.pk), 'collection_mode': purchase.collection_mode} if purchase else None,
        'totals': {'purchased_classes': plain(classes), 'paid_classes': plain(paid['classes']),
                   'unpaid_classes': plain(classes - paid['classes']), 'used_classes': plain(used),
                   'available_quota': plain(paid['classes'] - used), 'package_amount': plain(amount),
                   'paid_amount': plain(paid['amount']), 'remaining_amount': plain(amount - paid['amount']) if amount is not None else None},
        'payments': [payment_data(payment) for payment in sale.payments.filter(Q(purpose='TOKEN') | Q(purchase__is_initial=True)).select_related('recorded_by')] if sale else [],
        'autopay': autopay.agreement_data(AutopayAgreement.objects.filter(purchase=purchase).first(),
            include_actions=has_app_permission(actor, 'accounts.view_all_students', request)) if purchase else None,
        'billing_timezone': settings.SALES_BILLING_TIMEZONE, 'autopay_configured': autopay.configured(),
        'can_collect': can_collect,
        'stripe_configured': stripe_configured(), 'parent_email': sale.parent_email if sale else lead.parent_email,
    }


def stripe_configured():
    from django.conf import settings
    prefix = 'sk_live_' if settings.STRIPE_LIVE_MODE else 'sk_test_'
    return settings.STRIPE_SECRET_KEY.startswith(prefix) and bool(settings.STRIPE_WEBHOOK_SECRET)


def audit(action, sale, actor, request=None, **context):
    log_activity(action=action, entity_type='sale', entity_id=sale.pk if sale else context.get('enquiry'),
                 entity_label=sale.reservation_reference or str(sale.pk) if sale else 'Quote replacement',
                 student=sale.student if sale and sale.student_id else None, context=context, actor=actor, request=request)


def collect(actor, enquiry_id, data, request=None):
    if data['method'] != PaymentMethod.STRIPE:
        return _prepare_collection(actor, enquiry_id, data, request)
    # No provider call may run before its immutable local origin commits.
    with transaction.atomic(durable=True):
        payment = _prepare_collection(actor, enquiry_id, data, request)
    if payment.method == PaymentMethod.STRIPE:
        from .stripe_gateway import create_checkout
        create_checkout(payment)
        payment.refresh_from_db()
    return payment


def _prepare_collection(actor, enquiry_id, data, request=None):
    stored_proof = None
    try:
        with transaction.atomic():
            lead = accessible_lead(actor, enquiry_id, request, lock=True)
            sale = Sale.objects.select_for_update().filter(enquiry=lead).first()
            if not sale:
                raise refusal('SALE_REQUIRED', 'Start the sale first.')
            existing = Payment.objects.filter(request_id=data['request_id']).first()
            if existing:
                if (existing.sale_id != sale.pk or existing.recorded_by_id != actor.pk
                        or existing.purpose != data['purpose'] or existing.method != data['method']
                        or existing.classes != data['classes'] or existing.collection_mode != data['collection_mode']
                        or (data['method'] != 'STRIPE' and (existing.amount != data.get('amount')
                            or existing.payment_date != data.get('payment_date', existing.payment_date)
                            or existing.transaction_reference != data.get('transaction_reference', '')
                            or existing.received_confirmed != data.get('received_confirmed', False)))):
                    raise refusal('IDEMPOTENCY_CONFLICT', 'That request ID was already used for a different collection.', 409)
                return existing
            if sale.student_id:
                raise refusal('ALREADY_ENROLLED', 'BDE collection ends at enrollment. This phase does not collect further student payments.', 403)
            from .autopay_models import AutopayAgreement
            if AutopayAgreement.objects.filter(purchase__sale=sale).exists():
                raise refusal('AUTOPAY_EXISTS', 'Continue the existing initial Autopay agreement instead of collecting another payment.', 409)
            if sale.payments.filter(status='PENDING').exists():
                raise refusal('PAYMENT_PENDING', 'An existing payment link is still pending. Resolve or expire it before another collection.', 409)
            if data['method'] == PaymentMethod.STRIPE and not stripe_configured():
                raise refusal('STRIPE_NOT_CONFIGURED', 'Configure matching Stripe credentials before collecting through Stripe.', 503)
            preview = preview_collection(actor, enquiry_id, data, request)
            amount = Decimal(preview['amount'])
            purchase = None
            if data['purpose'] == 'TUITION':
                from invitations.credentials import credential_cipher
                credential_cipher()  # Verify delivery configuration before collecting money.
                purchase = Purchase.objects.filter(sale=sale, is_initial=True).first()
                if purchase is None:
                    quote = current_quote(actor, lead, request)
                    package, classes = purchase_terms(quote, data['collection_mode'], intention='AUTOPAY' if data.get('_autopay_snapshot') else data['collection_mode'])
                    purchase = Purchase.objects.create(id=uuid.uuid5(sale.pk, 'initial-purchase'), sale=sale, quote=quote,
                                                       collection_mode=data['collection_mode'], amount=package, classes=classes)
                    lead.plan_changes_locked_at = timezone.now()
                    lead.save(update_fields=['plan_changes_locked_at'])
            if data['method'] != PaymentMethod.STRIPE:
                if not data.get('received_confirmed'):
                    raise refusal('RECEIPT_NOT_CONFIRMED', 'Confirm that the money has actually been received.')
                if data.get('amount') != amount:
                    raise refusal('AMOUNT_MISMATCH', f'This class allocation requires exactly AED {plain(amount)}.')
                if not data.get('proof'):
                    raise refusal('PROOF_REQUIRED', 'Attach the payment receipt or screenshot.')
            payment = Payment(id=data['request_id'], request_id=data['request_id'], sale=sale, purchase=purchase,
                              purpose=data['purpose'], method=data['method'], collection_mode=data['collection_mode'],
                              amount=amount, classes=data['classes'], recorded_by=actor,
                              payment_date=data.get('payment_date') or timezone.localdate(),
                              received_confirmed=data.get('received_confirmed', False),
                              transaction_reference=data.get('transaction_reference', ''))
            if data['method'] != PaymentMethod.STRIPE:
                from .payment_uploads import validate_proof
                content_type, extension = validate_proof(data['proof'])
                payment.proof_extension = extension
                payment.proof_content_type = content_type
                payment.proof_name = os.path.basename(data['proof'].name)[:255]
                payment.proof.save(f'receipt{extension}', data['proof'], save=False)
                stored_proof = payment.proof
            payment.save(force_insert=True)
            agreement = None
            if data.get('_autopay_snapshot'):
                from .autopay import persist_schedule, link_initial
                agreement = persist_schedule(payment, data['_autopay_snapshot'])
                link_initial(agreement, payment)
            if payment.method == PaymentMethod.STRIPE:
                from .checkout import prepare
                prepare(payment, agreement=agreement)
            if payment.method != PaymentMethod.STRIPE:
                succeed(payment, actor, request)
            audit('payment.create', sale, actor, request, payment=str(payment.pk), amount=plain(amount), classes=plain(payment.classes), method=payment.method)
            return payment
    except Exception:
        if stored_proof:
            stored_proof.storage.delete(stored_proof.name)
        raise


def succeed(payment, actor=None, request=None, provider_id=None):
    """Called only under the enquiry lock after direct receipt or signed provider verification."""
    if payment.status == PaymentStatus.SUCCEEDED:
        return
    if payment.status not in (PaymentStatus.PENDING, PaymentStatus.FAILED):
        raise refusal('PAYMENT_CLOSED', 'This payment is no longer collectible.', 409)
    payment.status = PaymentStatus.SUCCEEDED
    payment.verified_at = timezone.now()
    if provider_id:
        payment.stripe_payment_intent = provider_id
        payment.payment_date = timezone.localdate()
    payment.save(update_fields=['status', 'verified_at', 'stripe_payment_intent', 'payment_date'])
    if payment.purpose == 'TUITION':
        from .autopay_models import AutopayInstallment
        if payment.sale.student_id and AutopayInstallment.objects.filter(payment=payment, position__gt=0).exists():
            from students.models import Student
            student = Student.objects.select_for_update().get(pk=payment.sale.student_id)
            if student.quota_source != 'PAYMENTS':
                raise refusal('QUOTA_SOURCE_CONFLICT', 'This payment-managed student’s quota needs administrative review.', 409)
            student.total_class_quota += payment.classes
            student.save(update_fields=['total_class_quota'])
        else:
            from .enrollment import enroll
            enroll(payment.sale, payment.purchase, actor or payment.recorded_by, request)
    from .autopay_models import AutopayInstallment
    automatic = AutopayInstallment.objects.filter(payment=payment, position__gt=0).exists()
    audit('payment.received', payment.sale, None if automatic else actor or payment.recorded_by, request,
          payment=str(payment.pk), amount=plain(payment.amount), classes=plain(payment.classes),
          collection_source='AUTOPAY' if automatic else 'INITIAL')
