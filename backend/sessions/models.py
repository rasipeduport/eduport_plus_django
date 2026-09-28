import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from students.models import Student

class SessionStatusChoices(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ATTENDED = 'ATTENDED', 'Attended'
    CANCELLED = 'CANCELLED', 'Cancelled'

class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    title = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    
    recording_link = models.TextField(blank=True, null=True)
    notes_link = models.TextField(blank=True, null=True)
    homework_link = models.TextField(blank=True, null=True)
    
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        blank=True,
        null=True
    )
    status = models.CharField(
        max_length=20,
        choices=SessionStatusChoices.choices,
        default=SessionStatusChoices.SCHEDULED,
        db_index=True
    )
    cancellation_reason = models.TextField(blank=True, null=True)
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conducted_sessions'
    )
    series_id = models.UUIDField(blank=True, null=True, db_index=True)
    class_number = models.IntegerField(blank=True, null=True)

    # Post-session content every attended class must end up with, keyed by the
    # short name the API and the SPAs use. Order is the display order.
    REQUIRED_CONTENT = (
        ('notes', 'notes_link'),
        ('recording', 'recording_link'),
        ('homework', 'homework_link'),
    )

    class Meta:
        db_table = 'sessions'
        verbose_name = 'Session'
        verbose_name_plural = 'Sessions'
        ordering = ['-start_time']

    def __str__(self):
        return f"{self.title} - {self.student.full_name} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"

    # Content completion is derived from the link columns every time it is
    # read, never stored: a stored flag would go stale the moment a tutor or
    # mentor edits a link. Attendance (`status`) stays a separate fact --
    # a mentor may mark a class attended before its material exists.

    @property
    def missing_content(self):
        """Short names of the required links that are still empty."""
        return [name for name, field in self.REQUIRED_CONTENT if not (getattr(self, field) or '').strip()]

    @property
    def content_complete(self):
        return not self.missing_content

    @property
    def display_status(self):
        """
        What the UIs label the row: an attended class whose material is still
        incomplete reads as ``pending``; otherwise the lowercase attendance
        status. Scheduled and cancelled classes are never pending -- their
        content does not apply yet / at all.
        """
        if self.status == SessionStatusChoices.ATTENDED and not self.content_complete:
            return 'pending'
        return self.status.lower()
