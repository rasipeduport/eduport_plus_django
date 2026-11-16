# Database-backed password sign-in lockout, replacing the Redis counters of
# Phase 2. Two plain columns with defaults: existing rows start unlocked.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_reset_non_superuser_is_staff'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='failed_login_count',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Consecutive wrong passwords since the last successful sign-in.',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='locked_until',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Password sign-in is refused until this time. Clear it (and the count) to unlock.',
            ),
        ),
    ]
