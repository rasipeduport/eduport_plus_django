# Second half of the username introduction (see 0003): every row now has a
# username, so the column becomes NOT NULL + UNIQUE and USERNAME_FIELD can
# point at it.
import django.contrib.auth.validators
from django.db import migrations, models

USERNAME_HELP_TEXT = (
    'Sign-in name. Letters, digits and @/./+/-/_ only; stored lower-case so '
    'sign-in is case-insensitive.'
)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_username_password_lifecycle'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(
                help_text=USERNAME_HELP_TEXT,
                max_length=150,
                unique=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
            ),
        ),
    ]
