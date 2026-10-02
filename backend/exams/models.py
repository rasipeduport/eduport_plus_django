"""
Exam module, ported from the Supabase Hub/Learn apps.

Two independent kinds share the module:

* ``Exam`` -- a *chapter exam*: a live meeting between the student's mentor and
  the student (tutors are never involved) scheduled like a class, after which
  the mentor records a score X/Y, an optional recording link and optional
  question-paper files. Lifecycle SCHEDULED -> ATTENDED | CANCELLED. Exams do
  NOT consume class quota.
* ``AdditionalExam`` -- an untimed assignment: the mentor uploads a question
  paper under a title, the student uploads an answer sheet exactly once, the
  mentor scores it X/Y with optional feedback. Lifecycle ASSIGNED -> SUBMITTED
  -> SCORED.

The Postgres triggers and RLS of the original are replaced by
``exams.services`` (state machine, conflicts, scoping); the CHECK constraints
are kept as CheckConstraints so an illegal row can never be persisted.
"""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from students.models import Student


class ExamStatusChoices(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ATTENDED = 'ATTENDED', 'Attended'
    CANCELLED = 'CANCELLED', 'Cancelled'


class ExamTypeChoices(models.TextChoices):
    CHAPTER = 'CHAPTER', 'Chapter'


class AdditionalExamStatusChoices(models.TextChoices):
    ASSIGNED = 'ASSIGNED', 'Assigned'
    SUBMITTED = 'SUBMITTED', 'Submitted'
    SCORED = 'SCORED', 'Scored'


class ExamFileKind(models.TextChoices):
    QUESTION_PAPER = 'question_paper', 'Question paper'
    ANSWER_SHEET = 'answer_sheet', 'Answer sheet'


class Exam(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='exams')
    # Snapshot of students.mentor at creation (mirrors exams.mentor in the Hub);
    # only the reassignment views ever re-point it.
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mentored_exams'
    )
    type = models.CharField(max_length=20, choices=ExamTypeChoices.choices, default=ExamTypeChoices.CHAPTER)
    chapter_name = models.CharField(max_length=255)
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=ExamStatusChoices.choices,
        default=ExamStatusChoices.SCHEDULED,
        db_index=True
    )
    score = models.IntegerField(blank=True, null=True)
    max_score = models.IntegerField(blank=True, null=True)
    recording_link = models.TextField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exams'
        verbose_name = 'Exam'
        verbose_name_plural = 'Exams'
        ordering = ['-start_time']
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F('start_time')),
                name='exams_time_valid',
            ),
            # Score columns exist only once attended, and must be a sane X/Y.
            models.CheckConstraint(
                condition=(
                    Q(status='ATTENDED', score__isnull=False, max_score__isnull=False,
                      max_score__gt=0, score__gte=0, score__lte=F('max_score'))
                    | (~Q(status='ATTENDED') & Q(score__isnull=True, max_score__isnull=True))
                ),
                name='exams_score_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status'], name='exams_student_status_idx'),
            models.Index(fields=['mentor', 'status'], name='exams_mentor_status_idx'),
        ]

    def __str__(self):
        return f"{self.chapter_name} - {self.student.full_name} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"


class AdditionalExam(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='additional_exams')
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mentored_additional_exams'
    )
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=AdditionalExamStatusChoices.choices,
        default=AdditionalExamStatusChoices.ASSIGNED,
        db_index=True
    )
    submitted_at = models.DateTimeField(blank=True, null=True)
    scored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scored_additional_exams'
    )
    scored_at = models.DateTimeField(blank=True, null=True)
    score = models.IntegerField(blank=True, null=True)
    max_score = models.IntegerField(blank=True, null=True)
    feedback = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'additional_exams'
        verbose_name = 'Additional Exam'
        verbose_name_plural = 'Additional Exams'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status='SCORED', score__isnull=False, max_score__isnull=False,
                      max_score__gt=0, score__gte=0, score__lte=F('max_score'))
                    | (~Q(status='SCORED') & Q(score__isnull=True, max_score__isnull=True))
                ),
                name='additional_exams_score_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status'], name='add_exams_student_status_idx'),
            models.Index(fields=['mentor', 'status'], name='add_exams_mentor_status_idx'),
        ]

    def __str__(self):
        return f"{self.title} - {self.student.full_name}"


def exam_file_path(instance, filename):
    """Storage key: exams/<exam>/question_paper/<file id><ext>."""
    ext = instance.extension or ''
    return f"exams/{instance.exam_id}/{instance.kind}/{instance.id}{ext}"


def additional_exam_file_path(instance, filename):
    """Storage key: additional-exams/<exam>/<kind>/<file id><ext>."""
    ext = instance.extension or ''
    return f"additional-exams/{instance.additional_exam_id}/{instance.kind}/{instance.id}{ext}"


class ExamFile(models.Model):
    """A question-paper file attached to a chapter exam (several per exam)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='files')
    kind = models.CharField(max_length=20, choices=ExamFileKind.choices, default=ExamFileKind.QUESTION_PAPER)
    file = models.FileField(upload_to=exam_file_path, max_length=512)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    extension = models.CharField(max_length=16, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_exam_files',
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'exam_files'
        verbose_name = 'Exam File'
        verbose_name_plural = 'Exam Files'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.kind} for {self.exam_id}: {self.file_name}"

    def link_path(self):
        return reverse('exams:exam-file', args=[self.id])


class AdditionalExamFile(models.Model):
    """A question-paper (mentor) or answer-sheet (student) file."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    additional_exam = models.ForeignKey(AdditionalExam, on_delete=models.CASCADE, related_name='files')
    kind = models.CharField(max_length=20, choices=ExamFileKind.choices)
    file = models.FileField(upload_to=additional_exam_file_path, max_length=512)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    extension = models.CharField(max_length=16, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_additional_exam_files',
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'additional_exam_files'
        verbose_name = 'Additional Exam File'
        verbose_name_plural = 'Additional Exam Files'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=['question_paper', 'answer_sheet']),
                name='additional_exam_files_kind_valid',
            ),
        ]

    def __str__(self):
        return f"{self.kind} for {self.additional_exam_id}: {self.file_name}"

    def link_path(self):
        return reverse('additional_exams:additional-exam-file', args=[self.id])


@receiver(post_delete, sender=ExamFile)
def _delete_exam_file_bytes(sender, instance, **kwargs):
    """Dropping the row drops the bytes too, including on cascade from the exam."""
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=AdditionalExamFile)
def _delete_additional_exam_file_bytes(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
