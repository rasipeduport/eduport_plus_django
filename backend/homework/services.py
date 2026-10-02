"""
Homework domain rules (the Supabase homework RLS + trigger, with the tutor as
grader). The assignment is the session's homework content; everything here is
about the row that follows it.
"""
import os
from django.db.models import Q
from django.utils import timezone

from activity.utils import log_activity
from exams.services import score_entry, validate_score
from sessions.models import Session, SessionStatusChoices
from .models import Homework, HomeworkStatusChoices, HomeworkFile


class HomeworkStateError(Exception):
    """A transition or edit the lifecycle refuses. The view answers 409."""


# ------------------------------------------------------------ assignment

def has_homework_content(session):
    """Whether the session carries an assignment (a URL or an uploaded file)."""
    return bool((session.homework_link or '').strip())


def sync_homework_for_session(session, actor=None, request=None, source='links'):
    """
    Keep the Homework row in step with the session: an ATTENDED session with
    homework content gets exactly one ASSIGNED row the first time that is true.
    Never deletes a row (a cleared assignment keeps its lifecycle, section 8 of
    the plan). Returns the created row or None.
    """
    if session.status != SessionStatusChoices.ATTENDED or not has_homework_content(session):
        return None
    if Homework.objects.filter(session=session).exists():
        return None
    homework = Homework.objects.create(
        session=session,
        student=session.student,
        assigned_by=actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None,
    )
    log_activity(
        action='homework.assign',
        entity_type='homework',
        entity_id=str(homework.id),
        entity_label=session.title,
        student=session.student,
        context={"session_id": str(session.id), "source": source},
        request=request,
        actor=actor,
    )
    return homework


def assert_assignment_editable(session):
    """
    The assignment may change while the homework is still ASSIGNED; once the
    student has submitted (or the tutor has scored) it is locked.
    """
    homework = Homework.objects.filter(session=session).only('status').first()
    if homework and homework.status != HomeworkStatusChoices.ASSIGNED:
        raise HomeworkStateError(
            "The homework has already been submitted; its assignment can no longer be changed."
        )


# ------------------------------------------------------------ lifecycle

def assert_homework_transition(homework, new_status):
    allowed = {
        (HomeworkStatusChoices.ASSIGNED, HomeworkStatusChoices.SUBMITTED),
        (HomeworkStatusChoices.SUBMITTED, HomeworkStatusChoices.SCORED),
    }
    if (homework.status, new_status) in allowed:
        return
    raise HomeworkStateError(
        f'Illegal homework status transition: {homework.status.lower()} -> {new_status.lower()}'
    )


def _basename(name, fallback):
    return os.path.basename(name or '')[:255] or fallback


def store_submission_files(homework, validated, user):
    rows = []
    for upload, content_type, ext in validated:
        row = HomeworkFile(
            homework=homework,
            kind=HomeworkFile.SUBMISSION,
            file_name=_basename(upload.name, f'submission{ext}'),
            content_type=content_type,
            size_bytes=upload.size,
            extension=ext,
            uploaded_by=user,
        )
        row.file.save(f'{row.id}{ext}', upload, save=False)
        row.save()
        rows.append(row)
    return rows


def submit_homework(homework, validated, student_user):
    """ASSIGNED -> SUBMITTED with the student's files. Caller holds the row lock."""
    if homework.status != HomeworkStatusChoices.ASSIGNED:
        raise HomeworkStateError('This homework has already been submitted')
    assert_homework_transition(homework, HomeworkStatusChoices.SUBMITTED)
    rows = store_submission_files(homework, validated, student_user)
    homework.status = HomeworkStatusChoices.SUBMITTED
    homework.submitted_at = timezone.now()
    homework.save(update_fields=['status', 'submitted_at', 'updated_at'])
    return rows


def score_homework(homework, score, max_score, feedback, actor):
    """SUBMITTED -> SCORED by the tutor or an admin. Caller holds the row lock."""
    if homework.status != HomeworkStatusChoices.SUBMITTED:
        raise HomeworkStateError('Only a submitted homework can be scored')
    score_val, max_val = validate_score(score, max_score)
    assert_homework_transition(homework, HomeworkStatusChoices.SCORED)
    homework.status = HomeworkStatusChoices.SCORED
    homework.score = score_val
    homework.max_score = max_val
    homework.feedback = feedback or None
    homework.scored_by = actor
    homework.scored_at = timezone.now()
    homework.save()
    return homework


# ------------------------------------------------------------ permissions

def can_grade(user, student):
    """Admins, or the student's assigned tutor. Never the mentor."""
    if user.role == 'ADMIN' or user.is_superuser:
        return True
    return user.role == 'TUTOR' and student.tutor_id == user.id


def can_view_submission(user, homework):
    """
    Submission files: admin, the tutor and the owning student always; the
    mentor only once the homework is scored (the Supabase rule).
    """
    if user.role in ('ADMIN', 'TUTOR', 'STUDENT') or user.is_superuser:
        return True
    return homework.status == HomeworkStatusChoices.SCORED


def homework_history_exists(student):
    return Homework.objects.filter(student=student).exists()


# ------------------------------------------------------------ scorecard

def collect_homework_entries(student):
    """Scored homework as scorecard entries, timestamped by scored_at (Learn getScorecard)."""
    entries = []
    rows = Homework.objects.filter(
        student=student, status=HomeworkStatusChoices.SCORED, scored_at__isnull=False
    ).only('score', 'max_score', 'scored_at')
    for row in rows:
        entry = score_entry('homework', 'Homework', row.score, row.max_score, row.scored_at)
        if entry:
            entries.append(entry)
    return entries
