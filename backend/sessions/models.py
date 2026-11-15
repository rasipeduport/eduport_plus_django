import uuid
from datetime import timedelta
from urllib.parse import urlparse

from django.db import models
from django.db.models import F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from django.utils import timezone
from students.models import Student

class SessionStatusChoices(models.TextChoices):
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ATTENDED = 'ATTENDED', 'Attended'
    CANCELLED = 'CANCELLED', 'Cancelled'
    # No-show / Not Conducted: the outcome an administrator or the student's
    # mentor recorded after the scheduled end (sessions.lifecycle.record_outcome).
    NOT_CONDUCTED = 'NOT_CONDUCTED', 'Not conducted'


class SessionOutcomeReason(models.TextChoices):
    """Why a class was not conducted. Only a student's no-show keeps its credit used (sessions.services)."""
    STUDENT_NO_SHOW = 'STUDENT_NO_SHOW', 'Student no-show'
    TUTOR_ABSENT = 'TUTOR_ABSENT', 'Tutor absent'
    TECHNICAL_ISSUE = 'TECHNICAL_ISSUE', 'Technical issue'
    OTHER = 'OTHER', 'Other'


class LateNotesStatus(models.TextChoices):
    """Where a tutor's notes submitted after NOTES_DEADLINE stand (sessions.lifecycle)."""
    PENDING = 'PENDING', 'Awaiting approval'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


# The assigned tutor's notes complete a started class only up to this long
# after its scheduled end; later ones wait for an administrator's or the
# student's mentor's approval (sessions.lifecycle).
NOTES_DEADLINE = timedelta(hours=48)


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

    # When the class was started and by whom: Start Session by its assigned
    # tutor, the student's mentor or an administrator, by the server's clock
    # (sessions.lifecycle.start_session). Operational only -- it opens the
    # class and never completes it, and who started it never matters to the
    # completion. Its scheduled time alone never starts a class. NULL = not
    # started, including every class from before Start existed: a start is
    # never made up.
    started_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='started_sessions'
    )
    # The tutor's completion: when its assigned tutor's own notes completed
    # it, and who that was -- notes a started class takes only after its
    # originally scheduled end, within NOTES_DEADLINE, or later once approved
    # (then the moment those late notes came in) (sessions.lifecycle). Written
    # once. An administrator's or mentor's notes, recording or Mark Attended
    # leave both empty -- those are operational attendance, not the tutor's
    # completion.
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_sessions'
    )

    # The tutor's notes submitted after NOTES_DEADLINE: awaiting approval,
    # approved (the class is then completed) or rejected (by the outcome then
    # recorded), and who reviewed them.
    late_notes_status = models.CharField(max_length=20, choices=LateNotesStatus.choices, null=True, blank=True)
    late_notes_submitted_at = models.DateTimeField(null=True, blank=True)
    late_notes_reviewed_at = models.DateTimeField(null=True, blank=True)
    late_notes_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_session_late_notes'
    )

    # No-show / Not Conducted, as recorded (status NOT_CONDUCTED): why, an
    # optional note (required for OTHER), who recorded it and when, and the
    # status the class had before -- given back if an administrator revokes
    # it. An administrator's latest correction of the reason is kept too;
    # every record, correction and revocation is in the activity log.
    outcome_reason = models.CharField(max_length=20, choices=SessionOutcomeReason.choices, null=True, blank=True)
    outcome_note = models.TextField(null=True, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_session_outcomes'
    )
    outcome_prior_status = models.CharField(max_length=20, choices=SessionStatusChoices.choices, null=True, blank=True)
    outcome_corrected_at = models.DateTimeField(null=True, blank=True)
    outcome_corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='corrected_session_outcomes'
    )

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
        constraints = [
            # A start comes with its moment, and so does a completion; who did
            # either may since be gone (SET_NULL), but never without the moment.
            models.CheckConstraint(
                condition=Q(started_by__isnull=True) | Q(started_at__isnull=False),
                name='sessions_started_by_needs_started_at',
            ),
            models.CheckConstraint(
                condition=Q(completed_by__isnull=True) | Q(completed_at__isnull=False),
                name='sessions_completed_by_needs_completed_at',
            ),
            # Completed = attended, and no earlier than the scheduled end of
            # the class.
            models.CheckConstraint(
                condition=Q(completed_at__isnull=True) | (
                    Q(status=SessionStatusChoices.ATTENDED) & Q(completed_at__gte=F('end_time'))
                ),
                name='sessions_completed_is_attended_after_end',
            ),
            # A class is completed only after someone started it, and only
            # within NOTES_DEADLINE of its scheduled end unless its late notes
            # were approved. (Every comparison with a nullable column below
            # says NOT NULL as well: a comparison with NULL lets a check pass.)
            models.CheckConstraint(
                condition=Q(completed_at__isnull=True) | Q(started_at__isnull=False),
                name='sessions_completed_needs_start',
            ),
            models.CheckConstraint(
                condition=(
                    Q(completed_at__isnull=True)
                    | Q(completed_at__lte=F('end_time') + NOTES_DEADLINE)
                    | Q(late_notes_status__isnull=False, late_notes_status=LateNotesStatus.APPROVED)
                ),
                name='sessions_completed_on_time_or_approved',
            ),
            # Late notes: on a started class, after the deadline, each review
            # with its moment; approved ones completed the class, rejected
            # ones went with a recorded outcome, pending ones await either.
            models.CheckConstraint(
                condition=(
                    Q(late_notes_status__isnull=True, late_notes_submitted_at__isnull=True,
                      late_notes_reviewed_at__isnull=True, late_notes_reviewed_by__isnull=True)
                    | (
                        Q(late_notes_status__isnull=False, late_notes_status=LateNotesStatus.PENDING,
                          late_notes_reviewed_at__isnull=True, late_notes_reviewed_by__isnull=True,
                          completed_at__isnull=True)
                        & ~Q(status=SessionStatusChoices.NOT_CONDUCTED)
                    )
                    | Q(late_notes_status__isnull=False, late_notes_status=LateNotesStatus.APPROVED,
                        late_notes_reviewed_at__isnull=False, completed_at__isnull=False)
                    | Q(late_notes_status__isnull=False, late_notes_status=LateNotesStatus.REJECTED,
                        late_notes_reviewed_at__isnull=False, status=SessionStatusChoices.NOT_CONDUCTED)
                ),
                name='sessions_late_notes_review_consistent',
            ),
            models.CheckConstraint(
                condition=Q(late_notes_submitted_at__isnull=True) | (
                    Q(late_notes_status__isnull=False)
                    & Q(started_at__isnull=False)
                    & Q(late_notes_submitted_at__gt=F('end_time') + NOTES_DEADLINE)
                ),
                name='sessions_late_notes_after_deadline',
            ),
            # Not conducted <=> an outcome is recorded, after the scheduled
            # end, from a scheduled or attended class; OTHER carries its note.
            models.CheckConstraint(
                condition=(
                    Q(status=SessionStatusChoices.NOT_CONDUCTED, outcome_reason__isnull=False,
                      outcome_recorded_at__isnull=False, outcome_recorded_at__gte=F('end_time'),
                      outcome_prior_status__isnull=False,
                      outcome_prior_status__in=[SessionStatusChoices.SCHEDULED, SessionStatusChoices.ATTENDED])
                    | (
                        ~Q(status=SessionStatusChoices.NOT_CONDUCTED)
                        & Q(outcome_reason__isnull=True, outcome_note__isnull=True, outcome_recorded_at__isnull=True,
                            outcome_recorded_by__isnull=True, outcome_prior_status__isnull=True,
                            outcome_corrected_at__isnull=True, outcome_corrected_by__isnull=True)
                    )
                ),
                name='sessions_not_conducted_has_outcome',
            ),
            models.CheckConstraint(
                condition=Q(outcome_reason__isnull=True) | ~Q(outcome_reason=SessionOutcomeReason.OTHER)
                | Q(outcome_note__isnull=False),
                name='sessions_other_outcome_has_note',
            ),
            models.CheckConstraint(
                condition=Q(outcome_corrected_by__isnull=True) | Q(outcome_corrected_at__isnull=False),
                name='sessions_outcome_corrected_by_needs_at',
            ),
        ]

    def __str__(self):
        return f"{self.title} - {self.student.full_name} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"

    @property
    def duration_hours(self):
        """
        The class as booked, in hours (one hour = one class credit): its
        scheduled end minus its scheduled start. Never the time its start or
        its notes came in -- and frozen once it has started or been attended,
        since neither may be rescheduled any more (sessions.views).
        """
        return (self.end_time - self.start_time).total_seconds() / 3600

    @property
    def notes_due_by(self):
        """The last moment its tutor's notes complete it without an approval: NOTES_DEADLINE after its scheduled end."""
        return self.end_time + NOTES_DEADLINE

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


class SessionContentField(models.TextChoices):
    NOTES = 'notes', 'Notes'
    RECORDING = 'recording', 'Recording'
    HOMEWORK = 'homework', 'Homework'


def session_file_path(instance, filename):
    """Storage key: session-content/<session>/<field>/<file id><ext>. The
    original name lives on the row; the key stays short and safe."""
    ext = instance.extension or ''
    return f"session-content/{instance.session_id}/{instance.field}/{instance.id}{ext}"


class SessionFile(models.Model):
    """
    An uploaded file standing behind one of a session's three content links.

    The link column (``notes_link`` / ``recording_link`` / ``homework_link``)
    stays the single source of truth for "what to open": an upload writes the
    URL of the authenticated download view into it, exactly as a pasted URL
    would be stored. This row only carries the bytes and their metadata, so
    the dialogs can show the file's name and type and the download view can
    authorise and stream it. At most one file per (session, field); replacing
    the link with a URL (or a new upload) removes the old row and its bytes.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='files')
    field = models.CharField(max_length=20, choices=SessionContentField.choices)
    file = models.FileField(upload_to=session_file_path, max_length=512)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    extension = models.CharField(max_length=16, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_session_files',
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'session_files'
        verbose_name = 'Session File'
        verbose_name_plural = 'Session Files'
        constraints = [
            models.UniqueConstraint(fields=['session', 'field'], name='session_files_one_per_field'),
        ]

    def __str__(self):
        return f"{self.get_field_display()} for {self.session_id}: {self.file_name}"

    @property
    def link_field(self):
        return f"{self.field}_link"

    def link_path(self):
        """URL path of the authenticated download view for this file."""
        return reverse('sessions:session-file', args=[self.id])

    def matches_link(self, value):
        """Whether a stored link value still points at this file (host-agnostic)."""
        if not value:
            return False
        return urlparse(value).path == self.link_path()


@receiver(post_delete, sender=SessionFile)
def _delete_session_file_bytes(sender, instance, **kwargs):
    """Dropping the row drops the bytes too, including on cascade from the session."""
    if instance.file:
        instance.file.delete(save=False)
