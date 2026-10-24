# Phase 2 of the authentication redesign: a username to sign in with, plus the
# password-lifecycle columns behind the forced first-login change.
#
# `username` is added NULLABLE here and backfilled from each existing row's
# email local part; 0004 then makes it NOT NULL + UNIQUE. The schema change and
# the data change are kept in separate migrations on purpose: altering a table
# in the same transaction that just updated its rows is what makes PostgreSQL
# raise "cannot ALTER TABLE because it has pending trigger events".
#
# The backfill mirrors accounts.models.derive_username_base (copied here, not
# imported: migrations must not depend on live model code).
import re

import django.contrib.auth.validators
from django.db import migrations, models

USERNAME_MAX_LENGTH = 150
USERNAME_HELP_TEXT = (
    'Sign-in name. Letters, digits and @/./+/-/_ only; stored lower-case so '
    'sign-in is case-insensitive.'
)
_USERNAME_CLEAN_RE = re.compile(r'[^a-z0-9._+-]')


def _username_base(email):
    local_part = (email or '').split('@', 1)[0].strip().lower()
    base = _USERNAME_CLEAN_RE.sub('_', local_part).strip('._+-')
    return (base or 'user')[:USERNAME_MAX_LENGTH]


def backfill_usernames(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    taken = set(
        User.objects.exclude(username__isnull=True)
        .exclude(username='')
        .values_list('username', flat=True)
    )
    for user in User.objects.filter(username__isnull=True).order_by('created_at', 'id'):
        base = _username_base(user.email)
        candidate, suffix = base, 2
        while candidate in taken:
            tail = str(suffix)
            candidate = f"{base[:USERNAME_MAX_LENGTH - len(tail)]}{tail}"
            suffix += 1
        taken.add(candidate)
        user.username = candidate
        user.save(update_fields=['username'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_soft_deactivation'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='username',
            field=models.CharField(
                help_text=USERNAME_HELP_TEXT,
                max_length=USERNAME_MAX_LENGTH,
                null=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='must_change_password',
            field=models.BooleanField(
                default=False,
                help_text='The user signed in with a temporary password and must set their own before using the app.',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='password_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_usernames, migrations.RunPython.noop),
    ]
