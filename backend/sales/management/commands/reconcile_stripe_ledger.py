"""Compare Stripe money movements with the Django ledger for a recent window.

An invoice Django already links to an installment must also have the same
outcome in both: paid, void or uncollectible at Stripe exactly when Django
records it so (a missed webhook leaves Django behind).

Stripe access is GET-only: the HTTP client refuses every other method, so this
command cannot create, change or cancel anything in Stripe. Without
--record-review it writes nothing to the database either.
"""
import time

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sales import review
from sales.autopay_models import AutopayAttempt, AutopayInstallment
from sales.ledger_models import Dispute, Refund, ReviewKind
from sales.payment_models import Payment, StripeCheckoutOperation


class GetOnlyClient(stripe.RequestsClient):
    def _request_internal(self, method, url, headers, post_data, is_streaming):
        if method.lower() != 'get':
            raise RuntimeError(f'Reconciliation is read-only; refused {method.upper()}.')
        return super()._request_internal(method, url, headers, post_data, is_streaming)


# A Stripe invoice outcome and the installment status that records it.
SETTLED = {'paid': 'PAID', 'void': 'VOID', 'uncollectible': 'UNCOLLECTIBLE'}


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


class Command(BaseCommand):
    help = ('Report Stripe payments, invoices, refunds and disputes that the Django ledger does not account for, '
            'or records with a different outcome.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--record-review', action='store_true', help='Queue unmatched objects for Admin review.')

    def handle(self, *args, **options):
        from sales.payments import stripe_configured
        if not stripe_configured():
            raise CommandError('Stripe is not configured for this environment.')
        gateway = stripe.StripeClient(settings.STRIPE_SECRET_KEY, http_client=GetOnlyClient(timeout=30), max_network_retries=2)
        since = {'gte': int(time.time()) - options['days'] * 86400}

        def every(resource, params):
            return [data(row) for row in resource.list({'limit': 100, 'created': since, **params}).auto_paging_iter()]

        known_sessions = (set(Payment.objects.exclude(stripe_checkout_id=None).values_list('stripe_checkout_id', flat=True))
                          | set(StripeCheckoutOperation.objects.exclude(stripe_checkout_id=None).values_list('stripe_checkout_id', flat=True))
                          | set(AutopayAttempt.objects.exclude(stripe_checkout_id=None).values_list('stripe_checkout_id', flat=True)))
        known_intents = set(Payment.objects.exclude(stripe_payment_intent=None).values_list('stripe_payment_intent', flat=True))
        linked_installments = {row.stripe_invoice_id: row for row in AutopayInstallment.objects.exclude(stripe_invoice_id=None)}
        known_refunds = set(Refund.objects.values_list('stripe_refund_id', flat=True))
        known_disputes = set(Dispute.objects.values_list('stripe_dispute_id', flat=True))

        findings = []
        for session in every(gateway.v1.checkout.sessions, {'status': 'complete'}):
            if session['id'] not in known_sessions:
                findings.append((review.checkout_kind(session), session, 'Completed Checkout not in the Django ledger.'))
        for invoice in every(gateway.v1.invoices, {}):
            installment = linked_installments.get(invoice['id'])
            if installment is None:
                if invoice.get('status') == 'paid' and invoice.get('amount_paid'):
                    findings.append((ReviewKind.UNMATCHED_INVOICE, invoice, 'Paid invoice not linked to a Django installment.'))
            elif SETTLED.get(invoice.get('status')) != (installment.status if installment.status in SETTLED.values() else None):
                findings.append((ReviewKind.INCONSISTENT, invoice, f'Stripe invoice is {invoice.get("status")}; Django records '
                                 f'installment {installment.position} as {installment.status}. Nothing was credited or changed.'))
        for intent in every(gateway.v1.payment_intents, {}):
            if intent.get('status') != 'succeeded' or intent['id'] in known_intents:
                continue
            paid_invoices = [row for row in gateway.v1.invoice_payments.list(
                {'payment': {'type': 'payment_intent', 'payment_intent': intent['id']}, 'limit': 10}).auto_paging_iter()]
            if not paid_invoices:
                findings.append((ReviewKind.UNMATCHED_PAYMENT, intent, 'Succeeded payment with no Django payment or invoice.'))
        for refund in every(gateway.v1.refunds, {}):
            if refund['id'] not in known_refunds:
                findings.append((ReviewKind.UNMATCHED_REFUND, refund, 'Refund not recorded in Django.'))
        for dispute in every(gateway.v1.disputes, {}):
            if dispute['id'] not in known_disputes:
                findings.append((ReviewKind.UNMATCHED_DISPUTE, dispute, 'Dispute not recorded in Django.'))

        missing = [payment for payment in Payment.objects.filter(method='STRIPE', status='SUCCEEDED')
                   .exclude(stripe_payment_intent=None).order_by('-verified_at')[:200]
                   if not self._exists(gateway, payment.stripe_payment_intent)]

        self.stdout.write(f"Stripe {'live' if settings.STRIPE_LIVE_MODE else 'test'} mode, last {options['days']} days.")
        for kind, obj, summary in findings:
            label = 'MISMATCH' if kind == ReviewKind.INCONSISTENT else 'UNMATCHED'
            self.stdout.write(f'{label} {kind}: {obj["id"]} · {summary}')
        for payment in missing:
            self.stdout.write(self.style.ERROR(f'MISSING AT STRIPE: Django payment {payment.pk} references {payment.stripe_payment_intent}.'))
        if options['record_review']:
            queued = sum(1 for kind, obj, summary in findings if review.record(kind, obj, None, summary, source='RECONCILIATION'))
            self.stdout.write(f'Queued {queued} new review item(s).')
        if not findings and not missing:
            self.stdout.write(self.style.SUCCESS('Stripe and the Django ledger agree for this window.'))

    def _exists(self, gateway, intent_id):
        try:
            gateway.v1.payment_intents.retrieve(intent_id)
            return True
        except stripe.InvalidRequestError as exc:
            if exc.code == 'resource_missing':
                return False
            raise
