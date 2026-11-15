"""
The tutor's notes no longer have a deadline (2026-11-16): once someone has
started a class, its assigned tutor's own notes complete it whenever they come
in after its scheduled end, with no approval. The 48-hour deadline, late notes
and their review go: their three checks and four columns are dropped.

Late notes still awaiting approval when this runs were the tutor's own notes on
a started class after its end, so they complete it as of the moment they came
in, before the columns go. As an approval did, a class completed so with
homework on it gets its homework row (assigned as of the completion, by no one
in particular, as homework.0002's backfill). Approved late notes already
completed their class, and rejected ones went with a recorded No-show / Not
Conducted, which stays. The dev database held none of either when this was
written. Reversing it brings the columns back, and the deadline's
checks with them: a class its tutor's notes completed more than 48 hours after
its end comes back as late notes approved as of that completion, with no
reviewer -- a completion is never undone.
"""
from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.models import F, Q


def complete_pending_late_notes(apps, schema_editor):
    Session = apps.get_model('sessions_app', 'Session')
    Homework = apps.get_model('homework', 'Homework')
    alias = schema_editor.connection.alias
    pending = (
        Session.objects.using(alias)
        .filter(late_notes_status='PENDING', late_notes_submitted_at__isnull=False, completed_at__isnull=True,
                started_at__isnull=False, tutor__isnull=False)
        .exclude(status__in=['CANCELLED', 'NOT_CONDUCTED'])
        .exclude(Q(notes_link__isnull=True) | Q(notes_link__regex=r'^\s*$'))
    )
    completed = 0
    for session in pending:
        session.status = 'ATTENDED'
        session.completed_at = session.late_notes_submitted_at
        session.completed_by_id = session.tutor_id
        session.save(update_fields=['status', 'completed_at', 'completed_by'])
        completed += 1
        if (session.homework_link or '').strip() and not Homework.objects.using(alias).filter(session_id=session.id).exists():
            Homework.objects.using(alias).create(session_id=session.id, student_id=session.student_id, status='ASSIGNED',
                                                 assigned_at=session.completed_at)
    if completed:
        # The completions' foreign-key checks are deferred; run them now, before the columns are dropped.
        schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def approve_completions_after_deadline(apps, schema_editor):
    Session = apps.get_model('sessions_app', 'Session')
    (Session.objects.using(schema_editor.connection.alias)
     .filter(completed_at__gt=F('end_time') + timedelta(days=2))
     .update(late_notes_status='APPROVED', late_notes_submitted_at=F('completed_at'),
             late_notes_reviewed_at=F('completed_at')))


class Migration(migrations.Migration):

    dependencies = [
        ('sessions_app', '0004_session_outcomes_and_late_notes'),
        ('homework', '0002_backfill_from_sessions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='session',
            name='sessions_completed_on_time_or_approved',
        ),
        migrations.RemoveConstraint(
            model_name='session',
            name='sessions_late_notes_review_consistent',
        ),
        migrations.RemoveConstraint(
            model_name='session',
            name='sessions_late_notes_after_deadline',
        ),
        migrations.RunPython(complete_pending_late_notes, approve_completions_after_deadline),
        migrations.RemoveField(
            model_name='session',
            name='late_notes_reviewed_at',
        ),
        migrations.RemoveField(
            model_name='session',
            name='late_notes_reviewed_by',
        ),
        migrations.RemoveField(
            model_name='session',
            name='late_notes_status',
        ),
        migrations.RemoveField(
            model_name='session',
            name='late_notes_submitted_at',
        ),
    ]
