# Student timezone for session scheduling.
#
# Staff schedule using the student's local wall-clock time; the sessions API
# converts that to UTC before writing start_time / end_time. This column is the
# zone that conversion (and any student-facing display) uses. NULL means unset;
# callers fall back to Asia/Kolkata.
#
# Additive only. No existing session timestamp is read or written here -- stored
# instants are already correct and must not change. Mirrors the Hub's
# 20260810103000_student_timezone.sql, including its backfill.
import re

from django.db import migrations, models

# `country` is free text copied from the enrolment sheet, so matching is done on
# a normalised key: lower-cased, non-letters stripped, whitespace collapsed.
#
# Only countries with EXACTLY ONE zone are mapped. The US, Canada and Australia
# span several and are deliberately left NULL -- a wrong guess makes a student
# miss a lesson, whereas NULL makes the scheduling UI ask.
COUNTRY_TIMEZONES = {
    'india': 'Asia/Kolkata',
    'bharat': 'Asia/Kolkata',
    'uae': 'Asia/Dubai',
    'u a e': 'Asia/Dubai',
    'united arab emirates': 'Asia/Dubai',
    'dubai': 'Asia/Dubai',
    'abu dhabi': 'Asia/Dubai',
    'sharjah': 'Asia/Dubai',
    'qatar': 'Asia/Qatar',
    'doha': 'Asia/Qatar',
    'bahrain': 'Asia/Bahrain',
    'kuwait': 'Asia/Kuwait',
    'oman': 'Asia/Muscat',
    'muscat': 'Asia/Muscat',
    'saudi arabia': 'Asia/Riyadh',
    'saudi': 'Asia/Riyadh',
    'ksa': 'Asia/Riyadh',
    'singapore': 'Asia/Singapore',
    'sri lanka': 'Asia/Colombo',
    'srilanka': 'Asia/Colombo',
    'nepal': 'Asia/Kathmandu',
    'bangladesh': 'Asia/Dhaka',
}


def _country_key(country):
    key = re.sub(r'[^a-z ]', '', (country or '').strip().lower())
    return re.sub(r'\s+', ' ', key).strip()


def backfill_timezone_from_country(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    unset = Student.objects.filter(timezone__isnull=True).exclude(country__isnull=True).exclude(country='')
    for student in unset.iterator():
        zone = COUNTRY_TIMEZONES.get(_country_key(student.country))
        if zone:
            student.timezone = zone
            student.save(update_fields=['timezone'])


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0002_alter_student_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='timezone',
            field=models.CharField(
                blank=True,
                help_text="IANA time zone identifier (e.g. Asia/Dubai) used to schedule and display this student's sessions. Blank means unset; callers fall back to Asia/Kolkata.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_timezone_from_country, migrations.RunPython.noop),
    ]
