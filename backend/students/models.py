import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class StatusChoices(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    EXPIRED = 'EXPIRED', 'Expired'

class Student(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='students'
    )
    student_code = models.CharField(max_length=50, unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    school_name = models.CharField(max_length=255, blank=True, null=True)
    grade = models.CharField(max_length=50, blank=True, null=True)
    syllabus = models.CharField(max_length=100, blank=True, null=True)
    admission_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mentored_students'
    )
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tutored_students'
    )
    meet_link = models.URLField(max_length=1024, blank=True, null=True)
    # IANA zone the student's sessions are scheduled and displayed in
    # (e.g. Asia/Dubai). NULL means unset; callers fall back to
    # core.timezones.DEFAULT_TIMEZONE (IST), which is how sessions were
    # always entered before the column existed.
    timezone = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="IANA time zone identifier (e.g. Asia/Dubai) used to schedule and display this student's sessions. Blank means unset; callers fall back to Asia/Kolkata.",
    )
    total_class_quota = models.IntegerField(default=0)
    remarks_for_mentor = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
        db_index=True
    )
    status_note = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'students'
        verbose_name = 'Student'
        verbose_name_plural = 'Students'
        ordering = ['student_code']

    def __str__(self):
        return f"{self.full_name} ({self.student_code})"


class StudentNote(models.Model):
    """
    An internal, staff-written note about a student.

    Lives only in the Hub's student profile: every staff role (admin, mentor,
    tutor) may read and write the notes of a student they can already open, and
    nothing in the Learn app ever exposes them -- they are the staff's own
    running commentary, not something the student or their parent reads. That
    is also why they are kept apart from ``remarks_for_mentor`` (a single field
    the enrolment flow fills in) and from ``status_note`` (the reason attached
    to one status change).

    Deliberately not append-only, unlike the activity log: an author may fix
    their own note, and an admin may remove any. Each of those is logged.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='notes')
    body = models.TextField()
    # The note outlives its author's account (SET_NULL), so the display name is
    # snapshotted alongside -- the same trick the activity log uses.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_notes',
    )
    author_name = models.CharField(max_length=255, blank=True, null=True)
    author_role = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    edited_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'student_notes'
        verbose_name = 'Student Note'
        verbose_name_plural = 'Student Notes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', '-created_at'], name='student_notes_student_idx'),
        ]

    def __str__(self):
        return f"Note on {self.student_id} by {self.author_name or 'unknown'}"
