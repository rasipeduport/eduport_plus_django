"""Stripe-owned recurring invoices. No local charge or business-retry scheduler.

Initial Checkout remains in autopay_stripe. This adapter provisions a finite
native schedule and reconciles its invoices into the existing payment ledger.
"""
import calendar
import logging
import uuid
from datetime import datetime, timedelta, timezone as utc_timezone
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from . import autopay, payments
from .autopay_models import AutopayAgreement, AutopayAttempt, AutopayInstallment
from .payment_models import Payment, StripeCustomer

ENGINE = 'STRIPE_BILLING'
logger = logging.getLogger(__name__)
INVOICE_EVENTS = {'invoice.created', 'invoice.finalized', 'invoice.updated', 'invoice.finalization_failed',
                  'invoice.payment_failed', 'invoice.payment_action_required', 'invoice.paid',
                  'invoice.voided', 'invoice.marked_uncollectible', 'invoice.payment_succeeded'}
SUBSCRIPTION_EVENTS = {'customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted',
                       'customer.subscription.paused', 'customer.subscription.resumed'}
SCHEDULE_EVENTS = {'subscription_schedule.created', 'subscription_schedule.updated', 'subscription_schedule.completed',
                   'subscription_schedule.canceled', 'subscription_schedule.released', 'subscription_schedule.aborted'}
EVENTS = INVOICE_EVENTS | SUBSCRIPTION_EVENTS | SCHEDULE_EVENTS


def data(obj):
    return obj if isinstance(obj, dict) else obj.to_dict()


def identifier(obj):
    return obj.get('id') if isinstance(obj, dict) else obj


def internal_id(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def month_after(instant, count):
    month = instant.year * 12 + instant.month - 1 + count
    year, month = divmod(month, 12)
    month += 1
    return instant.replace(year=year, month=month, day=min(instant.day, calendar.monthrange(year, month)[1]))


def phase_terms(rows):
    """Exactly one full-price invoice per phase, including irregular dates.

    Each price's recurring interval covers the entire phase. At the next agreed
    date Stripe resets the anchor with no proration; it cannot renew the old
    price inside that phase. The final phase lasts one interval and cancels.
    """
    if not 1 <= len(rows) <= 10:
        raise payments.refusal('STRIPE_SCHEDULE_UNSUPPORTED', 'Stripe Billing supports at most 10 future installment phases. Review the schedule before collecting the initial payment.')
    terms = []
    for index, row in enumerate(rows):
        due = row['due_at']
        due = datetime.fromisoformat(due) if isinstance(due, str) else due
        if due.tzinfo is None:
            raise payments.refusal('STRIPE_SCHEDULE_UNSUPPORTED', 'A collection instant must include the configured billing timezone.')
        due = due.astimezone(utc_timezone.utc).replace(microsecond=0)
        end = rows[index + 1]['due_at'] if index + 1 < len(rows) else month_after(due, 1)
        end = datetime.fromisoformat(end) if isinstance(end, str) else end
        end = end.astimezone(utc_timezone.utc).replace(microsecond=0)
        amount = Decimal(str(row['amount']))
        if amount < 2 or amount != amount.to_integral_value() or end <= due:
            raise payments.refusal('STRIPE_SCHEDULE_UNSUPPORTED', 'Every Stripe installment must be at least AED 2 in whole AED, with distinct increasing collection dates.')
        interval = next((n for n in range(1, 37) if month_after(due, n) >= end), None)
        if interval is None:
            raise payments.refusal('STRIPE_SCHEDULE_UNSUPPORTED', 'A Stripe phase cannot span more than 36 months. Review the agreed dates before collecting payment.')
        terms.append({'start': int(due.timestamp()), 'end': int(end.timestamp()), 'months': interval,
                      'amount': int(amount) * 100, 'id': str(row.get('id', '')), 'position': row['position']})
    return terms


def metadata(agreement):
    return {'autopay_id': str(agreement.pk), 'purchase_id': str(agreement.purchase_id),
            'quote_id': str(agreement.purchase.quote_id), 'schedule_digest': agreement.schedule_digest,
            'collection_engine': ENGINE}


def descriptive(agreement):
    """Student and account references for people reading Stripe. Never used to validate."""
    sale = agreement.purchase.sale
    account = sale.account
    meta = {'eduport_account_id': str(account.pk), 'eduport_account_ref': account.reference,
            'enquiry_id': str(sale.enquiry_id), 'sale_id': str(sale.pk)}
    if account.student_id:
        meta.update(student_id=str(account.student_id), edp_student_id=account.student.student_code)
    return meta


def schedule_request(agreement, rows):
    # metadata() is what every validator checks and stays unchanged; the student
    # references are added beside it and frozen with the request.
    common = {**metadata(agreement), **descriptive(agreement)}
    account = agreement.purchase.sale.account
    refs = account.reference + (f' · {account.student.student_code}' if account.student_id else '')
    phases = []
    terms = phase_terms(rows)
    for term in terms:
        # Create uses one top-level start_date; each following phase starts at
        # the preceding end_date. Per-phase start_date is an update-only field.
        phases.append({'end_date': term['end'],
            'billing_cycle_anchor': 'phase_start', 'proration_behavior': 'none',
            'collection_method': 'charge_automatically',
            'automatic_tax': {'enabled': False}, 'default_tax_rates': '', 'discounts': '',
            'metadata': {**common, 'installment_id': term['id'], 'installment_position': str(term['position'])},
            'description': f'{account.student_name} ({refs}) — Eduport Plus installment {term["position"]} of {len(terms)}'[:500],
            'items': [{'quantity': 1, 'price_data': {'currency': 'aed', 'product': agreement.stripe_product_id,
                'unit_amount': term['amount'], 'tax_behavior': 'inclusive',
                'recurring': {'interval': 'month', 'interval_count': term['months']}}}]})
    return {'customer': agreement.stripe_customer_id, 'start_date': terms[0]['start'],
            'end_behavior': 'cancel', 'billing_mode': {'type': 'classic'}, 'metadata': common,
            'default_settings': {'collection_method': 'charge_automatically',
                                 'default_payment_method': agreement.stripe_payment_method_id,
                                 'automatic_tax': {'enabled': False}}, 'phases': phases}


def problem(agreement_id, message, status='REQUIRES_REVIEW', scope='RECONCILIATION', generation=None, unbound=False, rejected=False):
    rows = AutopayAgreement.objects.filter(pk=agreement_id, collection_engine=ENGINE)
    if generation is not None:
        rows = rows.filter(provisioning_generation=generation, billing_issue_scope__in=['', 'PROVISIONING'])
    if unbound:
        rows = rows.filter(stripe_schedule_id__isnull=True)
    fields = {'billing_status': status, 'billing_message': message[:255], 'billing_issue_scope': scope}
    if generation is not None:
        fields['provisioning_rejection_verified'] = rejected
    rows.update(**fields)


def refresh_current_method(agreement, gateway=None, subscription=None):
    """Reconcile the CURRENT native configuration, never the original Checkout card.

    Caller holds the enquiry/agreement locks. No payment is created or confirmed.
    Only this agreement's future schedule defaults may follow its verified current
    subscription card; Customer-wide defaults and other agreements are untouched.
    """
    from .stripe_gateway import client
    try:
        gateway = gateway or client()
        mapping = StripeCustomer.objects.get(account_id=agreement.purchase.sale.account_id, customer_id=agreement.stripe_customer_id)
        if mapping.customer_id != agreement.stripe_customer_id or mapping.livemode != agreement.livemode or agreement.livemode != settings.STRIPE_LIVE_MODE:
            raise ValueError('Billing Customer and environment require review.')
        schedule = data(gateway.v1.subscription_schedules.retrieve(agreement.stripe_schedule_id)) if agreement.stripe_schedule_id else None
        if schedule and (identifier(schedule.get('customer')) != agreement.stripe_customer_id
                or bool(schedule.get('livemode')) != agreement.livemode
                or any(schedule.get('metadata', {}).get(k) != v for k, v in metadata(agreement).items())):
            raise ValueError('The current schedule does not match the agreed Customer and environment.')
        subscription_id = identifier((schedule or {}).get('subscription') or (schedule or {}).get('released_subscription')) or agreement.stripe_subscription_id
        if subscription_id:
            # Read after acquiring the agreement lock. An event's earlier
            # snapshot must not restore an older card over a newer update.
            subscription = data(gateway.v1.subscriptions.retrieve(subscription_id))
            if (subscription.get('id') != subscription_id
                    or (agreement.stripe_subscription_id and agreement.stripe_subscription_id != subscription_id)
                    or identifier(subscription.get('customer')) != agreement.stripe_customer_id
                    or bool(subscription.get('livemode')) != agreement.livemode
                    or any(subscription.get('metadata', {}).get(k) != v for k, v in metadata(agreement).items())):
                raise ValueError('The current subscription does not match this agreement.')
            method_id = identifier(subscription.get('default_payment_method'))
            if not method_id and subscription.get('default_source'):
                raise ValueError('The current subscription uses an unsupported legacy source. No old card was restored.')
        elif schedule and schedule.get('status') == 'not_started':
            phase = (schedule.get('phases') or [{}])[0]
            method_id = identifier(phase.get('default_payment_method') or schedule.get('default_settings', {}).get('default_payment_method'))
        else:
            raise ValueError('The provisioned agreement has no verifiable current subscription configuration.')
        if not method_id:
            customer = data(gateway.v1.customers.retrieve(agreement.stripe_customer_id))
            if (customer.get('deleted') or bool(customer.get('livemode')) != agreement.livemode
                    or customer.get('id') != agreement.stripe_customer_id):
                raise ValueError('The current Billing Customer is unavailable.')
            method_id = identifier((customer.get('invoice_settings') or {}).get('default_payment_method'))
        if not method_id:
            raise ValueError('Stripe has no current default payment method. The original Checkout card was not substituted.')
        method = data(gateway.v1.payment_methods.retrieve(method_id))
        if (method.get('id') != method_id or method.get('customer') != agreement.stripe_customer_id
                or bool(method.get('livemode')) != agreement.livemode):
            raise ValueError('The current default payment method is detached or belongs to another Customer or environment.')
        if method.get('type') != 'card' or method.get('card', {}).get('country') == 'IN':
            agreement.setup_status = 'UNSUPPORTED'
            raise ValueError('The current default payment method is unsupported for this Billing setup flow.')
        if schedule and schedule.get('status') in ('active', 'not_started'):
            boundary = (schedule.get('current_phase') or {}).get('start_date', 0)
            if any(phase.get('start_date', 0) >= boundary and phase.get('default_payment_method')
                   and identifier(phase['default_payment_method']) != method_id for phase in schedule.get('phases', [])):
                raise ValueError('A remaining phase explicitly uses another card. Review the native configuration; no old card or phase terms were substituted.')
        # Do not replay a card-specific idempotency key across A→B→A transitions.
        # Setting this one field is intrinsically idempotent and never collects.
        if (subscription_id and identifier(subscription.get('default_payment_method')) == method_id
                and schedule and schedule.get('status') in ('active', 'not_started')
                and identifier(schedule.get('default_settings', {}).get('default_payment_method')) != method_id):
            gateway.v1.subscription_schedules.update(schedule['id'], {'default_settings': {'default_payment_method': method_id}})
        agreement.stripe_payment_method_id = method_id
        agreement.card_brand, agreement.card_last4 = method.get('card', {}).get('brand', ''), method.get('card', {}).get('last4', '')
        agreement.setup_status, agreement.setup_message = 'READY', ''
        agreement.ready_at = agreement.ready_at or timezone.now()
        if agreement.status not in ('COMPLETED', 'CANCELLED'):
            agreement.status = 'ACTIVE'
        if subscription_id:
            agreement.stripe_subscription_id = subscription_id
        if agreement.billing_issue_scope == 'PAYMENT_METHOD':
            agreement.billing_status, agreement.billing_message, agreement.billing_issue_scope = 'PROVISIONED', '', ''
    except (stripe.StripeError, ValueError, payments.SalesError, StripeCustomer.DoesNotExist) as exc:
        agreement.setup_status = 'UNSUPPORTED' if agreement.setup_status == 'UNSUPPORTED' else 'INCOMPLETE'
        if agreement.status not in ('COMPLETED', 'CANCELLED'):
            agreement.status = 'SETUP_INCOMPLETE'
        agreement.setup_message = str(exc)[:255] if isinstance(exc, ValueError) else 'Current Billing payment-method verification is incomplete. Admin follow-up is required.'
    agreement.save(update_fields=['stripe_subscription_id', 'stripe_payment_method_id', 'card_brand', 'card_last4',
        'setup_status', 'setup_message', 'ready_at', 'status', 'billing_status', 'billing_message', 'billing_issue_scope'])
    return agreement.setup_status == 'READY'


def mark_current_method_problem(agreement):
    # Setup information has its own fields. Do not erase an unrelated or
    # historical unclassified financial review just to flag card readiness.
    if (agreement.billing_issue_scope in ('', 'PROVISIONING', 'PAYMENT_METHOD')
            and not (agreement.billing_status == 'REQUIRES_REVIEW' and not agreement.billing_issue_scope)):
        problem(agreement.pk, agreement.setup_message, scope='PAYMENT_METHOD')


SCHEDULE_DATES_DIFFER = 'Stripe schedule dates or installment references do not match the agreed schedule.'


def _running_since(request, remote):
    """Stripe's current phase, or {'start_date': when the schedule stopped}; None before it starts.

    The current phase must be one of the frozen phases: it is found by its end date, which never moves.
    """
    current = remote.get('current_phase') or {}
    if current:
        if current.get('end_date') not in [phase['end_date'] for phase in request['phases']]:
            raise ValueError(SCHEDULE_DATES_DIFFER)
        return current
    stopped = remote.get('canceled_at') or remote.get('completed_at') or remote.get('released_at')
    return {'start_date': stopped} if stopped else None


def _started_later(actual_start, start, end, running):
    """Stripe restarts a running phase when its subscription is updated, as Django does once to set
    the new subscription's card options. So a phase that had already started may start later than
    agreed, inside its own window. Its end, and every phase yet to start, stay exact."""
    return (running is not None and isinstance(actual_start, int) and start < actual_start < end
            and actual_start <= running['start_date'])


def _validate_schedule(agreement, remote):
    if (identifier(remote.get('customer')) != agreement.stripe_customer_id or bool(remote.get('livemode')) != agreement.livemode
            or any(remote.get('metadata', {}).get(k) != v for k, v in metadata(agreement).items())):
        raise ValueError('Stripe schedule does not match this agreement, Customer and environment.')
    request = agreement.billing_request
    if not request:
        raise ValueError('No frozen provisioning request exists. A remote schedule cannot be adopted by metadata alone.')
    phases = remote.get('phases', [])
    if request and (len(phases) != len(request['phases']) or remote.get('end_behavior') != 'cancel'):
        raise ValueError('Stripe schedule phases do not match the frozen provisioning request.')
    running = _running_since(request, remote)
    for index, (actual, expected) in enumerate(zip(phases, request.get('phases', []))):
        start = request['start_date'] if index == 0 else request['phases'][index - 1]['end_date']
        if ((actual.get('start_date') != start and not _started_later(actual.get('start_date'), start, expected['end_date'], running))
                or actual.get('end_date') != expected['end_date']
                or any(actual.get('metadata', {}).get(k) != v for k, v in expected['metadata'].items())):
            raise ValueError(SCHEDULE_DATES_DIFFER)
        # Stripe's current phase is this one only with this phase's own start.
        if running and running.get('end_date') == expected['end_date'] and actual.get('start_date') != running.get('start_date'):
            raise ValueError(SCHEDULE_DATES_DIFFER)
        items = actual.get('items') or []
        if len(items) != 1 or items[0].get('quantity') != 1:
            raise ValueError('Stripe schedule has an unexpected item allocation.')
        from .stripe_gateway import client
        price = items[0].get('price')
        price = price if isinstance(price, dict) else data(client().v1.prices.retrieve(price))
        frozen = expected['items'][0]['price_data']
        recurring = price.get('recurring') or {}
        if (price.get('currency') != 'aed' or price.get('unit_amount') != frozen['unit_amount']
                or identifier(price.get('product')) != frozen['product']
                or recurring.get('interval') != 'month' or recurring.get('interval_count') != frozen['recurring']['interval_count']
                or actual.get('billing_cycle_anchor') != 'phase_start'
                or actual.get('proration_behavior') != 'none' or actual.get('discounts')
                or actual.get('default_tax_rates') or (actual.get('automatic_tax') or {}).get('enabled')):
            raise ValueError('Stripe phase pricing differs from the frozen installment.')


@transaction.atomic
def _adopt_schedule(agreement_id, remote):
    initial = AutopayInstallment.objects.get(agreement_id=agreement_id, position=0)
    agreement, _ = autopay.lock_installment(initial.pk)
    _validate_schedule(agreement, remote)
    first_binding = not agreement.stripe_schedule_id
    if agreement.stripe_schedule_id and agreement.stripe_schedule_id != remote['id']:
        raise ValueError('Another Stripe schedule is already bound to this agreement.')
    subscription_id = identifier(remote.get('subscription') or remote.get('released_subscription'))
    if agreement.stripe_subscription_id and subscription_id and agreement.stripe_subscription_id != subscription_id:
        raise ValueError('Another Stripe subscription is already bound to this agreement.')
    agreement.stripe_schedule_id = remote['id']
    agreement.stripe_schedule_status = remote.get('status', '')
    if subscription_id:
        agreement.stripe_subscription_id = subscription_id
    clear_provisioning = ((agreement.billing_status not in ('REQUIRES_REVIEW', 'ERROR') and agreement.billing_issue_scope in ('', 'PROVISIONING'))
            or agreement.billing_issue_scope == 'PROVISIONING'
            or (agreement.billing_status == 'ERROR' and not agreement.billing_issue_scope))
    agreement.save(update_fields=['stripe_schedule_id', 'stripe_schedule_status', 'stripe_subscription_id'])
    if first_binding:
        payments.audit('autopay.billing_provisioned', agreement.purchase.sale, None,
                       agreement=str(agreement.pk), schedule=remote['id'], subscription=subscription_id)
    if not refresh_current_method(agreement):
        mark_current_method_problem(agreement)
        agreement.refresh_from_db()
        return agreement
    if clear_provisioning:
        agreement.billing_status, agreement.billing_message, agreement.billing_issue_scope = 'PROVISIONED', '', ''
        agreement.save(update_fields=['billing_status', 'billing_message', 'billing_issue_scope'])
    if remote.get('status') in ('canceled', 'aborted', 'released'):
        stopped_in_stripe(agreement, 'The Stripe schedule was stopped or released. Review outstanding installments; historical terms were preserved.')
    elif agreement.cancelled_at and remote.get('status') in ('not_started', 'active'):
        problem(agreement.pk, 'A Stripe schedule is running for a cancelled agreement. Cancel it in Stripe; no classes are credited for it automatically.')
    return agreement


def provision(agreement_id, reconcile_only=False, recover=False):
    """Idempotent provisioning/transport reconciliation, never a payment retry."""
    from .stripe_gateway import client
    initial = AutopayInstallment.objects.get(agreement_id=agreement_id, position=0)
    with transaction.atomic():
        agreement, _ = autopay.lock_installment(initial.pk)
        if (agreement.collection_engine != ENGINE or not agreement.initial_paid_at or agreement.setup_status != 'READY'
                or agreement.cancelled_at):
            return
        if agreement.livemode != settings.STRIPE_LIVE_MODE or not agreement.purchase.sale.student_id:
            raise payments.refusal('BILLING_NOT_READY', 'Verified enrollment and matching Stripe mode are required.', 409)
        prior_status, prior_scope = agreement.billing_status, agreement.billing_issue_scope
        if recover and reconcile_only:
            raise payments.refusal('INVALID_RECOVERY', 'Choose recovery or adoption-only reconciliation, not both.', 409)
        if agreement.stripe_schedule_id and not (recover or reconcile_only):
            return
        if recover:
            if prior_scope not in ('', 'PROVISIONING') and prior_status in ('ERROR', 'REQUIRES_REVIEW'):
                raise payments.refusal('UNRELATED_REVIEW', 'This review concerns payment/invoice reconciliation, not provisioning. Its flag cannot be cleared by reprovisioning.', 409)
            if prior_status == 'REQUIRES_REVIEW' and not prior_scope and (
                    agreement.stripe_schedule_id or agreement.installments.filter(position__gt=0).filter(
                        Q(stripe_invoice_id__isnull=False) | Q(payment__isnull=False) | Q(attempts__isnull=False)).exists()):
                raise payments.refusal('UNCLASSIFIED_REVIEW', 'Historical review has collection history. An operator must establish its cause before provisioning recovery.', 409)
        key_started = agreement.provisioning_key_started_at or agreement.provisioning_started_at
        if (agreement.billing_status == 'SUBMITTING' and key_started
                and key_started > timezone.now() - timedelta(minutes=2) and not reconcile_only):
            return
        if agreement.billing_status not in ('NOT_PROVISIONED', 'SUBMITTING', 'UNKNOWN') and not (reconcile_only or recover):
            return
        rejected_recovery = (recover and prior_status == 'ERROR' and prior_scope in ('', 'PROVISIONING')
                             and agreement.provisioning_rejection_verified)
        if rejected_recovery:
            # A cached provider rejection cannot be repaired by replaying its
            # old key. Allocate a new, durable generation only on explicit
            # recovery of a definitive rejection, never an unknown outcome.
            agreement.provisioning_generation += 1
            agreement.provisioning_key_started_at = timezone.now()
            agreement.provisioning_rejection_verified = False
        started = agreement.provisioning_key_started_at or agreement.provisioning_started_at
        if not reconcile_only:
            agreement.billing_status = 'SUBMITTING'
        if recover:
            agreement.billing_issue_scope = 'PROVISIONING'
            payments.audit('autopay.billing_recovery_requested', agreement.purchase.sale, None,
                           agreement=str(agreement.pk), previous_status=prior_status)
        if not reconcile_only:
            agreement.provisioning_started_at = agreement.provisioning_started_at or timezone.now()
            agreement.provisioning_key_started_at = agreement.provisioning_key_started_at or agreement.provisioning_started_at
        agreement.save(update_fields=['billing_status', 'provisioning_started_at', 'billing_issue_scope',
                                      'provisioning_generation', 'provisioning_key_started_at', 'provisioning_rejection_verified'])
        attempt_generation = agreement.provisioning_generation
        attempt_unbound = not agreement.stripe_schedule_id
    submitted = False
    try:
        gateway = client()
        # Reconcile remote success before attempting creation, including lost responses.
        matches = [data(row) for row in gateway.v1.subscription_schedules.list(
            {'customer': agreement.stripe_customer_id, 'limit': 100}).auto_paging_iter()
            if data(row).get('metadata', {}).get('autopay_id') == str(agreement.pk)]
        if len(matches) > 1:
            raise ValueError('Multiple remote schedules exist. Review them before any further collection.')
        if matches:
            return _adopt_schedule(agreement.pk, matches[0])
        if agreement.stripe_schedule_id:
            raise ValueError('The bound schedule was not found in the Customer’s remote history. No replacement may be created.')
        if reconcile_only or (started and started < timezone.now() - timedelta(hours=23)):
            raise ValueError('No matching schedule found. Provisioning needs review; an expired idempotency window is never retried blindly.')
        rows = list(agreement.installments.filter(position__gt=0).exclude(status='PAID').values('id', 'position', 'amount', 'due_at'))
        phase_terms(rows)
        if rows[0]['due_at'] <= timezone.now():
            raise ValueError('An agreed collection date has passed. The schedule cannot be silently backdated.')
        if agreement.installments.filter(position__gt=0).exclude(status='PAID').filter(Q(payment__isnull=False) | Q(attempts__isnull=False)).exists():
            raise ValueError('A future installment already has collection history. Reconcile it before provisioning Billing.')
        mapping = StripeCustomer.objects.get(account_id=agreement.purchase.sale.account_id, customer_id=agreement.stripe_customer_id)
        method = data(gateway.v1.payment_methods.retrieve(agreement.stripe_payment_method_id))
        if (mapping.customer_id != agreement.stripe_customer_id or mapping.livemode != agreement.livemode
                or method.get('customer') != mapping.customer_id or bool(method.get('livemode')) != agreement.livemode
                or method.get('type') != 'card' or method.get('card', {}).get('country') == 'IN'):
            raise ValueError('The saved card must be reusable for this Customer and environment; India-specific recurring mandates need a separate supported setup flow.')
        from .customers import ensure_product
        product_id = ensure_product(gateway, 'TUITION')
        with transaction.atomic():
            agreement = AutopayAgreement.objects.select_for_update().select_related('purchase__sale').get(pk=agreement.pk)
            if agreement.provisioning_generation != attempt_generation or agreement.stripe_schedule_id:
                return  # A newer recovery or verified adoption already owns this origin.
            agreement.stripe_product_id = product_id
            if not agreement.billing_request:
                agreement.billing_request = schedule_request(agreement, rows)
            agreement.save(update_fields=['stripe_product_id', 'billing_request'])
        key = f'eduport-billing-schedule-{agreement.pk}'
        if agreement.provisioning_generation:
            key += f'-recovery-{agreement.provisioning_generation}'
        submitted = True
        remote = data(gateway.v1.subscription_schedules.create(agreement.billing_request,
            options={'idempotency_key': key}))
        return _adopt_schedule(agreement.pk, remote)
    except (ValueError, payments.SalesError, StripeCustomer.DoesNotExist) as exc:
        problem(agreement.pk, str(exc), scope='PROVISIONING', generation=attempt_generation, unbound=attempt_unbound)
    except stripe.InvalidRequestError as exc:
        from .stripe_gateway import is_definitive_rejection
        definitive = is_definitive_rejection(exc)
        problem(agreement.pk, 'Stripe rejected provisioning. Correct its configuration before explicit recovery.' if definitive
                else 'Stripe provisioning is unconfirmed. No new key will be issued for an ambiguous operation.',
                'ERROR' if definitive else 'UNKNOWN', scope='PROVISIONING', generation=attempt_generation,
                unbound=attempt_unbound, rejected=submitted and definitive)
    except stripe.StripeError:
        problem(agreement.pk, 'Stripe provisioning response is unconfirmed. The same operation will be reconciled.', 'UNKNOWN', scope='PROVISIONING', generation=attempt_generation, unbound=attempt_unbound)


def provision_ready():
    ids = AutopayAgreement.objects.filter(collection_engine=ENGINE, initial_paid_at__isnull=False,
        setup_status='READY', stripe_schedule_id__isnull=True, cancelled_at__isnull=True,
        billing_status__in=['NOT_PROVISIONED', 'SUBMITTING', 'UNKNOWN']).values_list('pk', flat=True)
    for agreement_id in list(ids):
        try:
            provision(agreement_id)
        except Exception:
            logger.exception('Stripe Billing provisioning requires reconciliation for agreement %s', agreement_id)


@transaction.atomic
def migrate_legacy(agreement_id):
    initial = AutopayInstallment.objects.get(agreement_id=agreement_id, position=0)
    agreement, _ = autopay.lock_installment(initial.pk)
    if agreement.collection_engine == ENGINE:
        return agreement
    if not agreement.initial_paid_at or agreement.setup_status != 'READY' or not agreement.purchase.sale.student_id:
        raise payments.refusal('BILLING_NOT_READY', 'The original initial payment, enrollment and saved card must be verified.', 409)
    rows = agreement.installments.filter(position__gt=0).exclude(status='PAID')
    if rows.filter(Q(payment__isnull=False) | Q(attempts__isnull=False)).exists():
        raise payments.refusal('LEGACY_COLLECTION_EXISTS', 'An unpaid installment has existing provider history. It cannot be automatically migrated.', 409)
    phase_terms(list(rows.values('id', 'position', 'amount', 'due_at')))
    if rows.filter(due_at__lte=timezone.now()).exists():
        raise payments.refusal('SCHEDULE_OVERDUE', 'A collection date has passed. Review the original agreement; do not silently backdate it.', 409)
    agreement.collection_engine = ENGINE
    agreement.save(update_fields=['collection_engine'])
    payments.audit('autopay.billing_migration', agreement.purchase.sale, None, agreement=str(agreement.pk))
    return agreement


def _subscription_agreement(subscription):
    meta = subscription.get('metadata') or {}
    agreement_id = internal_id(meta.get('autopay_id'))
    agreement = AutopayAgreement.objects.select_related('purchase__sale').filter(
        pk=agreement_id, collection_engine=ENGINE).first() if agreement_id else None
    if not agreement:
        return None
    if (subscription.get('customer') != agreement.stripe_customer_id
            or bool(subscription.get('livemode')) != agreement.livemode
            or agreement.livemode != settings.STRIPE_LIVE_MODE
            or any(meta.get(k) != v for k, v in metadata(agreement).items())):
        raise ValueError('Subscription Customer, mode or agreement references do not match.')
    schedule_id = identifier(subscription.get('schedule'))
    if agreement.stripe_subscription_id and agreement.stripe_subscription_id != subscription['id']:
        raise ValueError('The agreement already belongs to another Stripe subscription.')
    if not agreement.stripe_schedule_id or (schedule_id and schedule_id != agreement.stripe_schedule_id):
        if not schedule_id or agreement.stripe_schedule_id:
            raise ValueError('The subscription does not belong to the provisioned schedule.')
        from .stripe_gateway import client
        agreement = _adopt_schedule(agreement.pk, data(client().v1.subscription_schedules.retrieve(schedule_id)))
    return agreement


def _invoice_context(invoice):
    parent = invoice.get('parent') or {}
    details = parent.get('subscription_details') or invoice.get('subscription_details') or {}
    return identifier(details.get('subscription') or invoice.get('subscription')), details.get('metadata') or {}


def _validate_invoice(agreement, installment, invoice):
    expected = int(installment.amount) * 100
    subscription_id, meta = _invoice_context(invoice)
    lines = invoice.get('lines') or {}
    rows = lines.get('data', [])
    if (subscription_id != agreement.stripe_subscription_id or invoice.get('customer') != agreement.stripe_customer_id
            or invoice.get('currency') != 'aed' or bool(invoice.get('livemode')) != agreement.livemode
            or invoice.get('total') != expected or invoice.get('subtotal') != expected
            or invoice.get('amount_due') != expected or invoice.get('starting_balance', 0) != 0
            or any(meta.get(k) != v for k, v in metadata(agreement).items())
            or str(installment.pk) != meta.get('installment_id')
            or installment.position == 0 or lines.get('has_more') or len(rows) != 1):
        raise ValueError('Invoice amount, currency, balance, subscription or installment references differ from the frozen agreement.')
    line = rows[0]
    if (line.get('amount') != expected or line.get('quantity') != 1
            or (line.get('period') or {}).get('start') != int(installment.due_at.timestamp())
            or (line.get('parent', {}).get('subscription_item_details') or {}).get('proration')):
        raise ValueError('Invoice line allocation or billing period does not match the agreed installment.')
    if installment.stripe_invoice_id and installment.stripe_invoice_id != invoice['id']:
        raise ValueError('Another invoice is already assigned to this installment. No duplicate invoice may be collected.')


def _invoice_payment(invoice, gateway):
    rows = [data(row) for row in gateway.v1.invoice_payments.list({'invoice': invoice['id'], 'status': 'paid', 'limit': 100,
        'expand': ['data.payment.payment_intent.latest_charge']}).auto_paging_iter()]
    if len(rows) != 1 or rows[0].get('amount_paid') != invoice['total']:
        raise ValueError('Invoice settlement needs reconciliation: exactly one full Stripe payment is required.')
    paid = rows[0]; reference = paid.get('payment') or {}
    if reference.get('type') != 'payment_intent':
        raise ValueError('An out-of-band or credit settlement requires manual reconciliation; no classes were credited.')
    intent = reference.get('payment_intent')
    intent = intent if isinstance(intent, dict) else data(gateway.v1.payment_intents.retrieve(intent))
    if (intent.get('status') != 'succeeded' or intent.get('amount_received') != invoice['total']
            or intent.get('customer') != invoice['customer'] or intent.get('currency') != 'aed'
            or bool(intent.get('livemode')) != bool(invoice.get('livemode'))):
        raise ValueError('Stripe has not verified the full invoice payment for this Customer and environment.')
    return paid, intent


def _attempt(installment, event, intent=None, invoice_payment=None, occurred_at=None):
    obj = event['data']['object']; error = (intent or {}).get('last_payment_error') or {}
    charge = identifier((intent or {}).get('latest_charge')) or identifier(error.get('charge'))
    key = charge or f'{installment.stripe_invoice_id}:{event["type"]}:{obj.get("attempt_count", 0)}:{error.get("code", "")}'
    existing = AutopayAttempt.objects.filter(provider_attempt_key=key).first()
    if existing:
        if existing.installment_id != installment.pk:
            raise ValueError('Provider attempt belongs to a different installment.')
        return existing
    return AutopayAttempt.objects.create(installment=installment,
        number=(installment.attempts.aggregate(n=Max('number'))['n'] or 0) + 1,
        provider_attempt_key=key, stripe_payment_intent_id=(intent or {}).get('id', ''),
        stripe_charge_id=charge or '', stripe_invoice_payment_id=(invoice_payment or {}).get('id', ''),
        created_at=datetime.fromtimestamp(occurred_at or event.get('created') or timezone.now().timestamp(), utc_timezone.utc))


def _failed_charge_history(installment, event, intent, gateway):
    """Recover failed attempts even when invoice webhooks arrive out of order.

    Stripe may reuse an invoice's PaymentIntent across retries. Charge IDs,
    rather than that PaymentIntent ID, identify the separate executed attempts.
    """
    if not intent.get('id'):
        return
    charges = [data(row) for row in gateway.v1.charges.list(
        {'payment_intent': intent['id'], 'limit': 100}).auto_paging_iter()]
    for charge in sorted(charges, key=lambda row: row.get('created', 0)):
        if charge.get('status') != 'failed':
            continue
        if (charge.get('customer') != installment.agreement.stripe_customer_id
                or charge.get('currency') != 'aed' or charge.get('amount') != int(installment.amount) * 100
                or bool(charge.get('livemode')) != installment.agreement.livemode):
            raise ValueError('Invoice attempt Customer, currency or amount does not match.')
        attempt = _attempt(installment, event, {**intent, 'latest_charge': charge['id']}, occurred_at=charge.get('created'))
        if attempt.status != 'FAILED':
            autopay.attempt_state(attempt, 'FAILED', charge.get('failure_code') or '')


def _reconcile_invoice(event, record):
    from .stripe_gateway import client
    gateway = client()
    invoice = data(gateway.v1.invoices.retrieve(event['data']['object']['id']))
    subscription_id, meta = _invoice_context(invoice)
    agreement = None
    if subscription_id:
        subscription = data(gateway.v1.subscriptions.retrieve(subscription_id))
        agreement = _subscription_agreement(subscription)
    if agreement is None:
        if invoice.get('status') == 'paid' and invoice.get('amount_paid'):
            from . import review
            from .ledger_models import ReviewKind
            review.record(ReviewKind.UNMATCHED_INVOICE, invoice, record, 'A paid invoice outside any Django agreement was not credited.')
        record.outcome = 'IGNORED'; return
    installment = agreement.installments.filter(pk=internal_id(meta.get('installment_id')), position__gt=0).first()
    if not installment:
        if invoice.get('status') in ('draft', 'open'):
            gateway.v1.invoices.update(invoice['id'], {'auto_advance': False})
        problem(agreement.pk, 'An invoice on this subscription has no matching frozen installment. Collection requires review.')
        raise ValueError('Invoice has no matching frozen installment.')
    agreement, installment = autopay.lock_installment(installment.pk)
    if not agreement.initial_paid_at or not agreement.purchase.sale.student_id:
        raise ValueError('A recurring invoice cannot replace verified initial tuition payment and enrollment.')
    if not agreement.stripe_subscription_id:
        agreement.stripe_subscription_id = subscription_id
        agreement.save(update_fields=['stripe_subscription_id'])
    try:
        _validate_invoice(agreement, installment, invoice)
    except ValueError:
        # Stop collection of an unexpected invoice; never alter its amount or the quote.
        if invoice.get('status') in ('draft', 'open'):
            gateway.v1.invoices.update(invoice['id'], {'auto_advance': False})
        problem(agreement.pk, 'Stripe invoice terms differ from the frozen installment. Collection requires review.')
        raise
    agreement.stripe_subscription_status = subscription.get('status', '')
    agreement.save(update_fields=['stripe_subscription_status'])
    if installment.status == 'PAID':
        if invoice.get('status') != 'paid':
            problem(agreement.pk, 'A previously settled invoice changed at Stripe. Review its history; no automatic quota reversal was made.')
        record.outcome = 'DUPLICATE'; return
    installment.stripe_invoice_id = invoice['id']
    installment.stripe_invoice_status = invoice.get('status', '')
    installment.stripe_invoice_number = invoice.get('number') or ''
    installment.stripe_invoice_url = invoice.get('hosted_invoice_url') or ''
    next_attempt = invoice.get('next_payment_attempt')
    installment.stripe_next_payment_attempt = datetime.fromtimestamp(next_attempt, utc_timezone.utc) if next_attempt else None
    installment.save(update_fields=['stripe_invoice_id', 'stripe_invoice_status', 'stripe_invoice_number', 'stripe_invoice_url', 'stripe_next_payment_attempt'])
    if invoice.get('status') == 'draft':
        installment.status = 'INVOICE_DRAFT'; installment.save(update_fields=['status'])
        if event['type'] == 'invoice.finalization_failed' or invoice.get('last_finalization_error'):
            problem(agreement.pk, 'Stripe could not finalize an installment invoice. Review the invoice in Stripe; no classes were credited.')
        record.outcome = 'PROCESSED'; return
    if not installment.payment_id:
        payment_id = uuid.uuid5(installment.pk, 'payment')
        payment = Payment.objects.create(id=payment_id, request_id=payment_id, sale=agreement.purchase.sale,
            purchase=agreement.purchase, purpose='TUITION', method='STRIPE', collection_mode='PARTIAL',
            collection_scope='BILLING_INSTALLMENT', amount=installment.amount, classes=installment.classes,
            recorded_by=agreement.created_by, stripe_customer_id=agreement.stripe_customer_id)
        installment.payment = payment
        installment.save(update_fields=['payment'])
    payment = Payment.objects.select_for_update().get(pk=installment.payment_id)
    status = invoice.get('status')
    if status == 'paid':
        paid, intent = _invoice_payment(invoice, gateway)
        if Payment.objects.filter(stripe_payment_intent=intent['id']).exclude(pk=payment.pk).exists():
            raise ValueError('This Stripe payment has already credited another allocation.')
        _failed_charge_history(installment, event, intent, gateway)
        attempt = _attempt(installment, event, intent, paid)
        from .stripe_gateway import card_evidence
        charge_id, card = card_evidence(intent.get('latest_charge'))
        payments.succeed(payment, provider_id=intent['id'], charge_id=charge_id if charge_id.startswith('ch_') else '', payer=card)
        installment.status, installment.paid_at = 'PAID', payment.verified_at
        installment.save(update_fields=['status', 'paid_at'])
        autopay.attempt_state(attempt, 'SUCCEEDED')
        if not agreement.installments.exclude(status='PAID').exists():
            agreement.status = 'COMPLETED'; agreement.save(update_fields=['status'])
    elif status in ('void', 'uncollectible'):
        installment.status = 'VOID' if status == 'void' else 'UNCOLLECTIBLE'
        payment.status = 'FAILED'; payment.save(update_fields=['status'])
        installment.save(update_fields=['status'])
        problem(agreement.pk, 'An installment invoice is void or uncollectible. Its unpaid allocation remains visible for Admin review.')
    elif event['type'] in ('invoice.payment_failed', 'invoice.payment_action_required'):
        # Retrieve current intent for accurate failure/SCA details; do not create or confirm one.
        candidates = [data(row) for row in gateway.v1.invoice_payments.list(
            {'invoice': invoice['id'], 'status': 'open', 'limit': 100}).auto_paging_iter()]
        candidates.sort(key=lambda row: (bool(row.get('is_default')), row.get('created', 0)), reverse=True)
        intent_id = next((identifier(row.get('payment', {}).get('payment_intent')) for row in candidates
                          if row.get('payment', {}).get('type') == 'payment_intent'), None)
        intent = data(gateway.v1.payment_intents.retrieve(intent_id)) if intent_id else {}
        _failed_charge_history(installment, event, intent, gateway)
        error = intent.get('last_payment_error') or {}
        state = 'REQUIRES_CUSTOMER_ACTION' if (intent.get('status') == 'requires_action' or error.get('code') == 'authentication_required'
            or (not intent and event['type'] == 'invoice.payment_action_required')) else 'PENDING' if intent.get('status') in ('processing', 'succeeded') else 'FAILED'
        attempt = _attempt(installment, event, intent)
        autopay.attempt_state(attempt, state, error.get('decline_code') or error.get('code', ''))
        installment.status = state; installment.save(update_fields=['status'])
        payment.status = 'PENDING' if state in ('PENDING', 'REQUIRES_CUSTOMER_ACTION') else 'FAILED'
        payment.save(update_fields=['status'])
    elif installment.status not in ('FAILED', 'REQUIRES_CUSTOMER_ACTION'):
        installment.status = 'PENDING'; installment.save(update_fields=['status'])
    record.outcome = 'PROCESSED'


def process_event(event, record):
    """Called only from the signature-verified, transaction-safe event router."""
    from .stripe_gateway import client
    obj = event['data']['object']
    try:
        if event['type'] in INVOICE_EVENTS:
            _reconcile_invoice(event, record)
        elif event['type'] in SUBSCRIPTION_EVENTS:
            subscription = data(client().v1.subscriptions.retrieve(obj['id']))
            agreement = _subscription_agreement(subscription)
            if not agreement:
                if event['type'] == 'customer.subscription.created':
                    from . import review
                    from .ledger_models import ReviewKind
                    review.record(ReviewKind.UNMATCHED_SUBSCRIPTION, subscription, record, 'A subscription Django did not create.')
                record.outcome = 'IGNORED'; return
            agreement, _ = autopay.lock_installment(agreement.installments.get(position=0).pk)
            agreement.stripe_subscription_id = subscription['id']
            agreement.stripe_subscription_status = subscription.get('status', '')
            agreement.save(update_fields=['stripe_subscription_id', 'stripe_subscription_status'])
            gateway = client()
            if subscription.get('status') not in ('canceled', 'incomplete_expired') and (
                    subscription.get('payment_settings') or {}).get('save_default_payment_method') != 'on_subscription':
                gateway.v1.subscriptions.update(subscription['id'], {'payment_settings': {
                    'save_default_payment_method': 'on_subscription', 'payment_method_types': ['card']},
                    'proration_behavior': 'none'}, options={'idempotency_key': f'eduport-billing-card-settings-{subscription["id"]}'})
            if not refresh_current_method(agreement, gateway, subscription):
                mark_current_method_problem(agreement)
            if subscription.get('status') in ('canceled', 'incomplete_expired'):
                agreement.refresh_from_db()
                stopped_in_stripe(agreement, 'Stripe subscription collection is stopped. Review its status and recovery settings; outstanding installments were preserved.')
            elif subscription.get('status') in ('unpaid', 'paused') and agreement.installments.exclude(status='PAID').exists():
                problem(agreement.pk, 'Stripe subscription collection is stopped. Review its status and recovery settings; outstanding installments were preserved.')
            elif subscription.get('pause_collection'):
                problem(agreement.pk, 'Stripe invoice collection is paused. Review the native subscription settings; no unpaid classes were credited.')
            record.outcome = 'PROCESSED'
        else:
            remote = data(client().v1.subscription_schedules.retrieve(obj['id']))
            agreement_id = internal_id(remote.get('metadata', {}).get('autopay_id'))
            if not AutopayAgreement.objects.filter(pk=agreement_id, collection_engine=ENGINE).exists():
                record.outcome = 'IGNORED'; return
            _adopt_schedule(agreement_id, remote)
            record.outcome = 'PROCESSED'
    except (ValueError, AutopayInstallment.DoesNotExist) as exc:
        agreement_id = internal_id(obj.get('metadata', {}).get('autopay_id') or _invoice_context(obj)[1].get('autopay_id'))
        if agreement_id and AutopayAgreement.objects.filter(pk=agreement_id, collection_engine=ENGINE).exists():
            problem(agreement_id, str(exc))
        record.outcome, record.error = 'REJECTED', str(exc)[:255]



def stopped_in_stripe(agreement, message):
    """Keep Django in step when collection stops at Stripe. Admin cancellations are expected."""
    if agreement.cancelled_at:
        return
    if agreement.installments.exclude(status='PAID').exists():
        AutopayAgreement.objects.filter(pk=agreement.pk, cancelled_at__isnull=True).update(
            status='CANCELLED', cancelled_at=timezone.now(), cancellation_source='STRIPE',
            cancellation_reason='Collection was stopped in Stripe, not through Eduport Plus.')
        problem(agreement.pk, message)


def cancel_agreement(actor, agreement_id, values, request=None):
    """Administrator cancellation (own decision or the parent's request).

    Future collection stops; paid installments, payments, classes and the agreed
    schedule stay as history. Stripe is told first: if it cannot confirm, nothing
    changes in Django. Open invoices are not voided automatically.
    """
    from .stripe_gateway import client
    from .student_accounts import is_admin
    if not is_admin(actor, request):
        raise payments.refusal('FORBIDDEN', 'Only an administrator can cancel Autopay.', 403)
    agreement = AutopayAgreement.objects.select_related('purchase__sale').filter(pk=agreement_id).first()
    if agreement is None:
        raise payments.refusal('NOT_FOUND', 'No such Autopay agreement.', 404)
    reason = ' '.join((values.get('reason') or '').split())
    source = values.get('source') or 'ADMIN'
    if len(reason) < 10:
        raise payments.refusal('REASON_REQUIRED', 'Explain the cancellation (at least 10 characters).')
    if source not in ('ADMIN', 'PARENT_REQUEST'):
        raise payments.refusal('INVALID_SOURCE', 'Choose who asked for the cancellation.')
    initial = agreement.installments.get(position=0)
    with transaction.atomic():
        agreement, _ = autopay.lock_installment(initial.pk)
        if agreement.cancelled_at:
            return agreement
        if agreement.status == 'COMPLETED' or not agreement.installments.filter(position__gt=0).exclude(status='PAID').exists():
            raise payments.refusal('NOTHING_TO_CANCEL', 'Every installment is already paid.', 409)
        schedule_id = agreement.stripe_schedule_id if agreement.collection_engine == ENGINE else None
    schedule_status = ''
    if schedule_id:
        gateway = client()
        try:
            remote = data(gateway.v1.subscription_schedules.cancel(schedule_id, {'invoice_now': False, 'prorate': False}))
        except stripe.InvalidRequestError:
            # Already stopped (for example by a concurrent cancellation): confirm, never assume.
            try:
                remote = data(gateway.v1.subscription_schedules.retrieve(schedule_id))
            except stripe.StripeError as exc:
                raise payments.refusal('STRIPE_UNAVAILABLE', 'Stripe could not confirm the cancellation. Nothing changed in Eduport Plus.', 503) from exc
        except stripe.StripeError as exc:
            raise payments.refusal('STRIPE_UNAVAILABLE', 'Stripe could not confirm the cancellation. Nothing changed in Eduport Plus.', 503) from exc
        schedule_status = remote.get('status') or ''
        if schedule_status not in ('canceled', 'completed', 'released'):
            raise payments.refusal('STRIPE_UNAVAILABLE', 'Stripe did not confirm the cancellation. Nothing changed in Eduport Plus.', 503)
    with transaction.atomic():
        agreement, _ = autopay.lock_installment(initial.pk)
        if agreement.cancelled_at:
            return agreement
        agreement.status, agreement.cancelled_at, agreement.cancelled_by = 'CANCELLED', timezone.now(), actor
        agreement.cancellation_reason, agreement.cancellation_source = reason, source
        fields = ['status', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'cancellation_source']
        if schedule_status:
            agreement.stripe_schedule_status = schedule_status
            fields.append('stripe_schedule_status')
        agreement.save(update_fields=fields)
        # Installments that never started collecting are cancelled; ones with an
        # invoice or payment attempt stay visible for follow-up.
        agreement.installments.filter(position__gt=0, payment__isnull=True, stripe_invoice_id__isnull=True).exclude(
            status='PAID').update(status='CANCELLED')
        payments.audit('autopay.cancelled', agreement.purchase.sale, actor, request, agreement=str(agreement.pk),
                       source=source, schedule=schedule_id)
    return agreement
