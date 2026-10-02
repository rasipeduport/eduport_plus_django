"""
Homework module, ported from the Supabase Hub/Learn apps with one role change:
the TUTOR grades (the Hub had the tutor grade as well; the mentor never does).

The assignment itself stays where it already lives in this repo: the session's
``homework_link`` (a URL or the single uploaded file behind it), set by the
mentor from the Session flow. A ``Homework`` row is the lifecycle hung off that
assignment -- created automatically once an ATTENDED session has homework
content, carrying the student's one-shot submission files and the tutor's
score. Both the sessions table and the /homework page read this one row.
"""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from sessions.models import Session
from students.models import Student


class HomeworkStatusChoices(models.TextChoices):
    ASSIGNED = 'ASSIGNED', 'Assigned'
    SUBMITTED = 'SUBMITTED', 'Submitted'
    SCORED = 'SCORED', 'Scored'


class Homework(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # One homework per session (the Hub's UNIQUE session_id).
    session = models.OneToOneField(Session, on_delete=models.CASCADE, related_name='homework')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='homework')
    status = models.CharField(
        max_length=20,
        choices=HomeworkStatusChoices.choices,
        default=HomeworkStatusChoices.ASSIGNED,
        db_index=True
    )
    # The staff member whose request first put homework content on the attended
    # session. Null for rows backfilled from pre-existing sessions.
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_homework',
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(blank=True, null=True)
    scored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scored_homework',
    )
    scored_at = models.DateTimeField(blank=True, null=True)
    score = models.IntegerField(blank=True, null=True)
    max_score = models.IntegerField(blank=True, null=True)
    feedback = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'homework'
        verbose_name = 'Homework'
        verbose_name_plural = 'Homework'
        ordering = ['-assigned_at']
        constraints = [
            # Score columns are set together only when scored, and must be a sane X/Y.
            models.CheckConstraint(
                condition=(
                    Q(status='SCORED', score__isnull=False, max_score__isnull=False,
                      max_score__gt=0, score__gte=0, score__lte=F('max_score'))
                    | (~Q(status='SCORED') & Q(score__isnull=True, max_score__isnull=True))
                ),
                name='homework_score_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status'], name='homework_student_status_idx'),
        ]

    def __str__(self):
        return f"Homework for {self.session_id} ({self.status})"


def homework_file_path(instance, filename):
    """Storage key: homework/<homework>/submission/<file id><ext>."""
    ext = instance.extension or ''
    return f"homework/{instance.homework_id}/{instance.kind}/{instance.id}{ext}"


class HomeworkFile(models.Model):
    """A file of the student's submission (several per homework)."""
    SUBMISSION = 'submission'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='files')
    kind = models.CharField(max_length=20, default=SUBMISSION)
    file = models.FileField(upload_to=homework_file_path, max_length=512)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    extension = models.CharField(max_length=16, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_homework_files',
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'homework_files'
        verbose_name = 'Homework File'
        verbose_name_plural = 'Homework Files'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.kind} for {self.homework_id}: {self.file_name}"

    def link_path(self):
        return reverse('homework:homework-file', args=[self.id])


@receiver(post_delete, sender=HomeworkFile)
def _delete_homework_file_bytes(sender, instance, **kwargs):
    """Dropping the row drops the bytes too, including on cascade from the homework."""
    if instance.file:
        instance.file.delete(save=False)
