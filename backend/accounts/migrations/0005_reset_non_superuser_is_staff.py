# `is_staff` now means "may use the Django admin site" and nothing else.
# Google provisioning used to set it on every non-student account; with
# password sign-in those accounts could reach /admin/ once given a password.
# Reset it to the superuser flag for every existing row. Superusers keep it.
from django.db import migrations


def reset_is_staff(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_superuser=False, is_staff=True).update(is_staff=False)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_user_username_unique'),
    ]

    operations = [
        migrations.RunPython(reset_is_staff, migrations.RunPython.noop),
    ]
