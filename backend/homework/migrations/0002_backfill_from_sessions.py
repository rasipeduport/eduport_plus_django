"""
Attended sessions that already carried homework content before the homework
app existed get their lifecycle row, so the sessions table and the /homework
page show the same set from day one. assigned_by is unknown for these rows.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Session = apps.get_model('sessions_app', 'Session')
    Homework = apps.get_model('homework', 'Homework')
    sessions = (
        Session.objects.filter(status='ATTENDED')
        .exclude(homework_link__isnull=True)
        .exclude(homework_link='')
    )
    for s in sessions:
        if Homework.objects.filter(session_id=s.id).exists():
            continue
        Homework.objects.create(
            session_id=s.id,
            student_id=s.student_id,
            status='ASSIGNED',
            assigned_at=s.updated_at or s.created_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('homework', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
