"""
    python manage.py reconcile_tutor_earnings [--dry-run]

The manual handle on the same sync Celery beat runs every 10 minutes: for an
operator who cannot wait for the next tick, and for checking what it would
add before it does (``--dry-run``, which writes nothing).
"""
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from earnings import conversions
from earnings.eligibility import activated_at
from earnings.ledger import earning_for, reconcile, unearned_classes
from earnings.models import SyncTrigger
from earnings.rates import RateBook, pricing


class Command(BaseCommand):
    help = 'Price the eligible classes with no earning yet and add them to the Tutor Earnings ledger.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would be added without writing anything.')

    def handle(self, *args, **options):
        if options['dry_run']:
            return self.dry_run()
        if not settings.TUTOR_EARNINGS_SYNC_ENABLED:
            self.stderr.write(self.style.WARNING('TUTOR_EARNINGS_SYNC_ENABLED is off: nothing was written.'))
            return
        run = reconcile(trigger=SyncTrigger.COMMAND)
        if run is None:
            self.stderr.write(self.style.WARNING('Another sync is running: nothing was written.'))
            return
        self.stdout.write(f'{run.status}: {run.earned_count} earned, {run.waiting_count} waiting for pricing, '
                          f'{run.skipped_count} not priced.')

    def dry_run(self):
        if activated_at() is None:
            self.stdout.write('Tutor Earnings is not activated: nothing counts.')
            return
        candidates = unearned_classes(timezone.now())
        if pricing() is None:
            self.stdout.write(f'Pricing has not started: {len(candidates)} eligible class(es) waiting for rates.')
            return
        book = RateBook.load()
        priced = Counter(c.class_type for c in candidates if earning_for(c, book) is not None)
        self.stdout.write(f'Would add {sum(priced.values())} earning(s): '
                          + (', '.join(f'{count} {kind}' for kind, count in sorted(priced.items())) or 'none')
                          + f'; {len(candidates) - sum(priced.values())} could not be priced.')
        # Conversions of Demos already earned; a Demo the run earns may convert in the same run too.
        found = conversions.pending(book)
        ready = sum(1 for item in found if item.state == conversions.READY)
        no_incentive = sum(1 for item in found if item.state == conversions.NO_INCENTIVE)
        self.stdout.write(f'Would add {ready} Demo conversion(s) for Demos already earned; '
                          f'{no_incentive} with no incentive (conversion rate not above the Demo).')
