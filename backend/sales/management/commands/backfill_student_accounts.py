"""READ-ONLY report of the student-account backfill that migration 0017 applies.

Runs inside a read-only transaction that is always rolled back, against the
schema the database is actually at (before or after migration 0016).
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader

from sales.account_backfill import plan


def masked(value):
    if not value:
        return '-'
    if '@' in value:
        name, _, domain = value.partition('@')
        return f'{name[:2]}…@{domain}'
    return f'{value[:4]}…{value[-2:]}'


class Command(BaseCommand):
    help = 'Report, without writing anything, the student accounts migration 0017 will create.'

    def handle(self, *args, **options):
        loader = MigrationLoader(connection)
        applied = set(loader.applied_migrations)
        apps = loader.project_state(nodes=sorted(applied), at_end=True).apps
        state = 'after' if ('sales', '0016_student_accounts') in applied else 'before'
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute("SELECT value FROM sales_salessequence WHERE name = 'STUDENT_ACCOUNT'")
                found = cursor.fetchone()
            rows, problems, notices = plan(apps)
            transaction.set_rollback(True)
        number = found[0] if found else 0
        self.stdout.write(f'Database is {state} migration sales.0016. Read-only dry run: nothing was written.')
        self.stdout.write(f'{len(rows)} enquiries with financial records.\n')
        for row in rows:
            if row['existing'] is not None:
                reference = row['existing'].reference + ' (exists)'
            else:
                number += 1
                reference = f'SA-{number:06d} (provisional)'
            student = row['student'].student_code if row['student'] else 'not enrolled'
            customers = ', '.join(f"{c.customer_id or 'pending'}{' live' if c.livemode else ' test'}" for c in row['customers'])
            customers = f'{customers} (kept as is, label LEGACY_PARENT, never renamed)' if customers else 'none yet'
            self.stdout.write(
                f"{reference}  {row['student_name']}  [{student}]\n"
                f"    enquiry {row['lead'].pk} · sale {'yes' if row['sale'] else 'no'} · payments {row['payments']}"
                f" (pending {row['pending_payments']}) · identity locked {'yes' if row['locked_at'] else 'no'}\n"
                f"    guardian {row['guardian']['full_name']} · email {masked(row['guardian']['email'])}"
                f" · phone {masked(row['guardian']['phone'])} · Stripe Customer {customers}")
        self.stdout.write('')
        for line in notices:
            self.stdout.write(f'NOTICE: {line}')
        for line in problems:
            self.stdout.write(self.style.ERROR(f'PROBLEM: {line}'))
        if problems:
            self.stdout.write(self.style.ERROR('Migration 0017 would stop on these problems. Nothing would change.'))
        else:
            self.stdout.write(self.style.SUCCESS('No ambiguous or duplicate mappings: migration 0017 can apply this plan.'))
