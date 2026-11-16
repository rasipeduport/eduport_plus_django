# The student's time zone (bookings.student_timezones): one new column,
# leads.student_timezone -- the IANA zone a student's booking page showed its
# slot times in, kept for showing staff the student's own time beside the
# Indian one. No existing row is written: every lead keeps an empty value,
# read as not known, and is shown in Indian time alone.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0013_lead_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='student_timezone',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
