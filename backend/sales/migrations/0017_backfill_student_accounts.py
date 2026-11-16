"""Link financial records created before student accounts to backfilled accounts.

Prepared, not applied. Run `manage.py backfill_student_accounts` first: it is the
read-only report of exactly what this migration does. One account and one
guardian per enquiry with a sale or Stripe Customer; possible siblings are
reported, never linked. Stops (and changes nothing) on any ambiguous mapping.
Reversible while no account, Customer or correction was created after it.
"""
from django.db import migrations

from sales.account_backfill import apply, unapply


class Migration(migrations.Migration):
    dependencies = [('sales', '0016_student_accounts')]
    operations = [migrations.RunPython(apply, unapply)]
