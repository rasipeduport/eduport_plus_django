"""Every sale and Customer mapping belongs to a student account. Prepared, not applied."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sales', '0017_backfill_student_accounts')]
    operations = [
        migrations.AlterField('sale', 'account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sales', to='sales.studentaccount')),
        migrations.AlterField('stripecustomer', 'account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stripe_customers', to='sales.studentaccount')),
    ]
