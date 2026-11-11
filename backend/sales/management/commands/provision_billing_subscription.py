"""Explicit provider provisioning/reconciliation; never a payment retry command."""
from django.core.management.base import BaseCommand, CommandError

from sales import billing, payments
from sales.autopay_models import AutopayAgreement


class Command(BaseCommand):
    help = 'Provision/adopt a native Stripe Billing schedule for one verified agreement.'

    def add_arguments(self, parser):
        parser.add_argument('agreement_id')
        parser.add_argument('--migrate-legacy', action='store_true', help='Explicitly switch an eligible legacy agreement; keep all original history.')
        recovery = parser.add_mutually_exclusive_group()
        recovery.add_argument('--reconcile-only', action='store_true', help='Only adopt an existing matching Stripe schedule; never create one.')
        recovery.add_argument('--recover', action='store_true', help='Explicitly resume a corrected provisioning error after remote discovery; never bypass an ambiguous expired request or frozen terms.')

    def handle(self, *args, **options):
        agreement_id = billing.internal_id(options['agreement_id'])
        if not agreement_id:
            raise CommandError('Provide a valid agreement UUID.')
        try:
            agreement = AutopayAgreement.objects.get(pk=agreement_id)
            if options['migrate_legacy']:
                agreement = billing.migrate_legacy(agreement_id)
            if agreement.collection_engine != billing.ENGINE:
                raise CommandError('Legacy collection remains enabled. Use --migrate-legacy only after reviewing this agreement.')
            billing.provision(agreement_id, reconcile_only=options['reconcile_only'], recover=options['recover'])
            agreement.refresh_from_db()
            self.stdout.write(f'{agreement.pk}: {agreement.billing_status}; schedule={agreement.stripe_schedule_id or "none"}; {agreement.billing_message}')
            if agreement.billing_status in ('ERROR', 'REQUIRES_REVIEW', 'UNKNOWN'):
                raise CommandError('Provisioning is not verified. Review the reported state; no unsafe replacement schedule was created.')
        except (AutopayAgreement.DoesNotExist, payments.SalesError) as exc:
            raise CommandError(str(exc)) from exc
