# Soft-deactivation lifecycle (staff exit) — mirrors the original Hub's
# profiles.deactivated_at / deactivated_by / deactivation_reason columns
# (Hub migration 20260630130000_user_exit_profiles_columns.sql).
#
# The backfill resolves the pre-existing edge case where a user was disabled by
# hand (is_active=False) before these columns existed: without it such a user
# would read as "active" in staff lists (deactivated_at IS NULL) while being
# unable to log in — an inconsistent lifecycle state. NULL deactivated_at must
# mean "fully active" from this migration onward.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def backfill_deactivated_at(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_active=False, deactivated_at__isnull=True).update(
        deactivated_at=timezone.now(),
        deactivation_reason='Backfilled: account was disabled before soft-deactivation existed',
    )


def noop(apps, schema_editor):
    # Reverse: dropping the columns discards the backfilled values anyway.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='deactivated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='deactivated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='deactivated_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='deactivation_reason',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_deactivated_at, noop),
    ]
