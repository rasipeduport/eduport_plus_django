"""
Tutor IDs (accounts.tutor_codes), schema only: the column each tutor's
permanent EPT0001-style ID lives in, and the counter of the last one issued.
Both start empty; 0034 issues the IDs of the tutors already here and adds the
checks and triggers.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0032_additional_hours_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='TutorCodeCounter',
            fields=[
                ('name', models.CharField(max_length=10, primary_key=True, serialize=False)),
                ('value', models.PositiveBigIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Tutor ID counter',
                'verbose_name_plural': 'Tutor ID counter',
                'db_table': 'tutor_code_counter',
            },
        ),
        migrations.AddField(
            model_name='user',
            name='tutor_code',
            field=models.CharField(
                blank=True, editable=False, max_length=16, null=True, unique=True, verbose_name='Tutor ID',
            ),
        ),
    ]
