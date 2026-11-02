"""
Assessment reports (Phase 5.2, design A.3): the tutor's report on one
Diagnostic or Demo booking, and every version it has had. report_shares is
kept but unused since the P9 revision: the owner BDE sends a report from the
enquiry page, and the Hub records no send (F.4).

Each report type has a table of its own, one-to-one with its booking table:
diagnostic_reports follows the two-page Academic Report, demo_reports the
one-page Demo Report. Reports are written only by reports.services, as bookings
are only by bookings.booking_service: the first save completes the booking, and
every save -- the first included -- adds a revision holding the report as saved.

Revisions and shares are append-only: database triggers refuse every update and
delete (reports.0002), so a report's history can never be rewritten. A report
with a revision can no longer be deleted either.

The caps on the tutor's text keep each PDF to its page count (A7). The system
fields -- the student's name and grade, the tutor's name -- are copies taken at
each save, as the report prints them (D7). The parent's name and phone are
never copied here, and a share stores no number: it is read from the lead.
"""
import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import BooleanField, F, Func, Q, Value
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual
from django.utils import timezone

from bookings.models import BookingType, DemoBooking, DiagnosticBooking

# Caps from the design (A.3, D15, A7): items per list, characters per item or field.
MAX_ITEMS = 15
ITEM_CHARS = 120
TEACHER_REMARKS_CHARS = 2000
SUGGESTED_PLAN_CHARS = 1000
DEMO_FIELD_CHARS = 1200
MAX_SCORE_LIMIT = 1000


class PerformanceLevel(models.TextChoices):
    EXCELLENT = 'EXCELLENT', 'Excellent'
    GOOD = 'GOOD', 'Good'
    AVERAGE = 'AVERAGE', 'Average'
    BELOW_AVERAGE = 'BELOW_AVERAGE', 'Below Average'


class ShareChannel(models.TextChoices):
    """How a report reached the parent, for a ReportShare (unused since the P9 revision, F.4)."""
    WHATSAPP_MANUAL = 'WHATSAPP_MANUAL', 'WhatsApp, attached by hand'


def _text_within(field, cap):
    """``field`` holds at most ``cap`` characters, and more than blanks: empty text is no answer."""
    return Q(**{f'{field}__regex': r'\S'}) & Q(LessThanOrEqual(Length(field), cap))


def _items_within(field):
    """
    ``field`` lists 1 to MAX_ITEMS items of at most ITEM_CHARS characters,
    none blank. A check constraint cannot look inside an array itself (and
    PostgreSQL does not apply a varchar length to array items), so it calls
    report_items_valid, made by reports.0001, which does.
    """
    return Q(Func(
        F(field), Value(MAX_ITEMS), Value(ITEM_CHARS), function='report_items_valid', output_field=BooleanField(),
    ))


class ReportBase(models.Model):
    """
    What both report types share. Each concrete report adds its booking (a
    one-to-one with its own booking table) and the fields the tutor writes.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Starts at 1 and goes up by one with every saved edit; an edit names the
    # version it was made from, and a stale one is refused (F.1).
    version = models.IntegerField(default=1)
    # The system fields as the report prints them, copied at every save (D7).
    student_name_snapshot = models.CharField(max_length=255)
    grade_snapshot = models.CharField(max_length=50)
    tutor_name_snapshot = models.CharField(max_length=255)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_%(class)ss'
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='updated_%(class)ss'
    )
    updated_at = models.DateTimeField(default=timezone.now)

    BOOKING_TYPE = None
    # The fields the tutor writes, in the order the report prints them.
    TUTOR_FIELDS = ()

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name='%(class)s_version_from_one'),
            models.CheckConstraint(condition=Q(updated_at__gte=F('submitted_at')), name='%(class)s_updated_after_submitted'),
            models.CheckConstraint(
                condition=~Q(student_name_snapshot='') & ~Q(grade_snapshot='') & ~Q(tutor_name_snapshot=''),
                name='%(class)s_snapshots_present',
            ),
        ]

    def __str__(self):
        # The id and version, never the student's or the tutor's name.
        return f'{self._meta.verbose_name.capitalize()} {self.id} (v{self.version})'

    @property
    def booking_type(self):
        return self.BOOKING_TYPE


class DiagnosticReport(ReportBase):
    """The two-page Academic Report on a Diagnostic booking."""
    BOOKING_TYPE = BookingType.DIAGNOSTIC
    TUTOR_FIELDS = (
        'score', 'max_score', 'performance_level', 'strength_areas', 'skills_to_strengthen', 'teacher_remarks',
        'suggested_plan',
    )

    booking = models.OneToOneField(DiagnosticBooking, on_delete=models.PROTECT, related_name='report')
    # Whole numbers (A12): the score out of the test's maximum.
    score = models.SmallIntegerField()
    max_score = models.SmallIntegerField()
    performance_level = models.CharField(max_length=20, choices=PerformanceLevel.choices)
    # Free text, one topic per item (D15).
    strength_areas = ArrayField(models.TextField())
    skills_to_strengthen = ArrayField(models.TextField())
    teacher_remarks = models.TextField()
    suggested_plan = models.TextField()

    class Meta(ReportBase.Meta):
        db_table = 'diagnostic_reports'
        verbose_name = 'Diagnostic report'
        verbose_name_plural = 'Diagnostic reports'
        constraints = [
            *ReportBase.Meta.constraints,
            models.CheckConstraint(
                condition=Q(max_score__gte=1, max_score__lte=MAX_SCORE_LIMIT),
                name='%(class)s_max_score_range',
            ),
            models.CheckConstraint(
                condition=Q(score__gte=0, score__lte=F('max_score')),
                name='%(class)s_score_within_max',
            ),
            models.CheckConstraint(
                condition=Q(performance_level__in=PerformanceLevel.values),
                name='%(class)s_known_performance_level',
            ),
            models.CheckConstraint(condition=_items_within('strength_areas'), name='%(class)s_strength_areas_items'),
            models.CheckConstraint(
                condition=_items_within('skills_to_strengthen'),
                name='%(class)s_skills_to_strengthen_items',
            ),
            models.CheckConstraint(
                condition=_text_within('teacher_remarks', TEACHER_REMARKS_CHARS),
                name='%(class)s_teacher_remarks_length',
            ),
            models.CheckConstraint(
                condition=_text_within('suggested_plan', SUGGESTED_PLAN_CHARS),
                name='%(class)s_suggested_plan_length',
            ),
        ]


class DemoReport(ReportBase):
    """The one-page Demo Report on a Demo booking."""
    BOOKING_TYPE = BookingType.DEMO
    TUTOR_FIELDS = ('assessment_review', 'class_observation_review', 'suggested_strategy')

    booking = models.OneToOneField(DemoBooking, on_delete=models.PROTECT, related_name='report')
    assessment_review = models.TextField()
    class_observation_review = models.TextField()
    suggested_strategy = models.TextField()

    class Meta(ReportBase.Meta):
        db_table = 'demo_reports'
        verbose_name = 'Demo report'
        verbose_name_plural = 'Demo reports'
        constraints = [
            *ReportBase.Meta.constraints,
            *(
                models.CheckConstraint(
                    condition=_text_within(field, DEMO_FIELD_CHARS),
                    name=f'%(class)s_{field}_length',
                )
                for field in ('assessment_review', 'class_observation_review', 'suggested_strategy')
            ),
        ]


class RevisionBase(models.Model):
    """
    One saved version of a report: every tutor field and system snapshot as
    saved (``content``), and the names of the fields that save changed.
    Append-only (reports.0002). Each concrete revision adds its report.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.IntegerField()
    content = models.JSONField()
    changed_fields = ArrayField(models.TextField(), default=list, blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='%(class)ss'
    )
    edited_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True
        ordering = ['version']
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name='%(class)s_version_from_one'),
        ]

    def __str__(self):
        return f'{self._meta.verbose_name.capitalize()} v{self.version} of {self.report_id}'


class DiagnosticReportRevision(RevisionBase):
    # The unique (report, version) index serves the foreign key too.
    report = models.ForeignKey(DiagnosticReport, on_delete=models.PROTECT, related_name='revisions', db_index=False)

    class Meta(RevisionBase.Meta):
        db_table = 'diagnostic_report_revisions'
        verbose_name = 'Diagnostic report revision'
        verbose_name_plural = 'Diagnostic report revisions'
        constraints = [
            *RevisionBase.Meta.constraints,
            models.UniqueConstraint(fields=['report', 'version'], name='%(class)s_one_per_version'),
        ]


class DemoReportRevision(RevisionBase):
    report = models.ForeignKey(DemoReport, on_delete=models.PROTECT, related_name='revisions', db_index=False)

    class Meta(RevisionBase.Meta):
        db_table = 'demo_report_revisions'
        verbose_name = 'Demo report revision'
        verbose_name_plural = 'Demo report revisions'
        constraints = [
            *RevisionBase.Meta.constraints,
            models.UniqueConstraint(fields=['report', 'version'], name='%(class)s_one_per_version'),
        ]


class ReportShare(models.Model):
    """
    One time a report was sent to the parent: which version, how, by whom and
    when. Append-only (reports.0002). No phone number is kept: it is always
    read from the lead. Unused since the P9 revision (F.4): the Hub records no
    send, so nothing writes this table. It is kept, not removed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Exactly one is set. The (report, shared_at) indexes serve the foreign keys.
    diagnostic_report = models.ForeignKey(
        DiagnosticReport,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='shares',
        db_index=False
    )
    demo_report = models.ForeignKey(
        DemoReport,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='shares',
        db_index=False
    )
    report_version = models.IntegerField()
    channel = models.CharField(max_length=20, choices=ShareChannel.choices, default=ShareChannel.WHATSAPP_MANUAL)
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='report_shares')
    shared_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'report_shares'
        verbose_name = 'Report share'
        verbose_name_plural = 'Report shares'
        ordering = ['shared_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(diagnostic_report__isnull=False, demo_report__isnull=True)
                    | Q(diagnostic_report__isnull=True, demo_report__isnull=False)
                ),
                name='report_shares_one_report',
            ),
            models.CheckConstraint(condition=Q(report_version__gte=1), name='report_shares_version_from_one'),
            models.CheckConstraint(condition=Q(channel__in=ShareChannel.values), name='report_shares_known_channel'),
        ]
        indexes = [
            models.Index(fields=['diagnostic_report', 'shared_at'], name='report_shares_diag_idx'),
            models.Index(fields=['demo_report', 'shared_at'], name='report_shares_demo_idx'),
        ]

    def __str__(self):
        return f'{self.get_channel_display()} v{self.report_version} ({self.shared_at:%Y-%m-%d %H:%M})'

    @property
    def report(self):
        return self.diagnostic_report or self.demo_report


# Every report table, and the one holding each booking type's reports.
REPORT_MODELS = (DiagnosticReport, DemoReport)
_REPORT_BY_TYPE = {model.BOOKING_TYPE: model for model in REPORT_MODELS}


def report_model(booking_type):
    """The report table of ``booking_type`` (a BookingType value)."""
    return _REPORT_BY_TYPE[booking_type]
