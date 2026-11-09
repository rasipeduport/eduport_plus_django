"""
Sales Management: the syllabuses the Admin offers and the global price per
class they are sold at.

A syllabus is the identity and lifecycle of one offering; everything it says
-- its titles, grade, board, plan types, inclusions and chapters -- is held by
its revisions. A syllabus has at most one draft revision, which the Admin edits
and previews, and it is published only on explicit confirmation. Publishing
never changes an earlier revision: the newest published revision is what the
syllabus offers, and every older one stays as it was published, for the sales
made from it. Editing a published syllabus starts a new draft copied from the
published revision.

Pricing is one common rate for every plan, versioned: each change adds a
PricingVersion that takes effect when it is saved, and the price applying at
any moment is the newest version effective by then.

Published revisions, their chapters and every pricing version are immutable:
database triggers refuse any change (sales.0002), so neither the ORM, the
Django admin nor raw SQL can rewrite what was published or charged. Syllabuses
and revisions are written only by sales.services, which audits every change.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Length, Mod
from django.db.models.lookups import Exact, LessThanOrEqual
from django.utils import timezone

# Caps on what a syllabus holds.
MIN_GRADE, MAX_GRADE = 1, 12
TITLE_CHARS = 120
PACKAGE_TITLE_CHARS = 160
SYLLABUS_VERSION_CHARS = 50
CHAPTER_NAME_CHARS = 200
MAX_CHAPTERS = 60
INCLUSION_CHARS = 120
MAX_INCLUSIONS = 6
# Class counts are whole or half classes (a chapter may take 1.5 revision classes).
CLASS_STEP = Decimal('0.5')
MAX_CLASSES_PER_CHAPTER = Decimal('99.5')


class Structure(models.TextChoices):
    CHAPTER_WISE = 'CHAPTER_WISE', 'Chapter-wise'
    BRIDGE_COURSE = 'BRIDGE_COURSE', 'Bridge Course'


class PlanType(models.TextChoices):
    """What a syllabus may be sold as. Chapter Plan sells a choice of the syllabus's own chapters."""
    REGULAR = 'REGULAR', 'Regular'
    REVISION = 'REVISION', 'Revision'
    CHAPTER_PLAN = 'CHAPTER_PLAN', 'Chapter Plan'
    BRIDGE_COURSE = 'BRIDGE_COURSE', 'Bridge Course'
    REGULAR_REVISION = 'REGULAR_REVISION', 'Regular + Revision'


# The plan types each structure offers: a Bridge Course is sold only as itself.
STRUCTURE_PLAN_TYPES = {
    Structure.CHAPTER_WISE: (PlanType.REGULAR, PlanType.REVISION, PlanType.CHAPTER_PLAN, PlanType.REGULAR_REVISION),
    Structure.BRIDGE_COURSE: (PlanType.BRIDGE_COURSE,),
}
# The plan types a package card is printed for (sales.pricing.card_plan_types), and so the
# only ones a single-payment privilege can apply to: Regular + Revision prints the Regular
# and Revision cards, and a Chapter Plan has no card yet.
PRIVILEGE_PLAN_TYPES = (PlanType.REGULAR, PlanType.REVISION, PlanType.BRIDGE_COURSE)


class Board(models.TextChoices):
    """The curricula, as the lead forms and the Hub name them (bookings.public_serializers.SYLLABI)."""
    CBSE = 'CBSE', 'CBSE'
    ICSE = 'ICSE', 'ICSE'
    IGCSE = 'IGCSE', 'IGCSE'
    IB = 'IB', 'IB'
    OTHERS = 'Others', 'Others'


class SyllabusStatus(models.TextChoices):
    """A syllabus's status, derived (sales.services.status_of): it is never stored."""
    DRAFT = 'DRAFT', 'Draft'
    PUBLISHED = 'PUBLISHED', 'Published'
    INACTIVE = 'INACTIVE', 'Inactive'


def _has_text(field):
    return Q(**{f'{field}__regex': r'\S'})


def _text_within(field, cap):
    """``field`` holds more than blanks, and at most ``cap`` characters."""
    return _has_text(field) & Q(LessThanOrEqual(Length(field), cap))


def _empty_or_text_within(field, cap):
    """``field`` is empty (its default wording applies) or holds text as _text_within allows."""
    return Q(**{field: ''}) | _text_within(field, cap)


def _classes(field):
    """``field`` is a whole or half number of classes, from 0 to MAX_CLASSES_PER_CHAPTER."""
    step = Value(CLASS_STEP, output_field=models.DecimalField(max_digits=2, decimal_places=1))
    return Q(**{f'{field}__gte': 0, f'{field}__lte': MAX_CLASSES_PER_CHAPTER}) & Q(Exact(Mod(F(field), step), 0))


class Syllabus(models.Model):
    """
    One offering the Admin sells: its revisions hold what it says. Its status
    is derived -- Inactive once deactivated, else Published once a revision
    has been published, else Draft. Deactivating hides it from the sales to
    come and never touches a revision.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_syllabi'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # Whoever last changed it or its draft, and when (any revision, any action).
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='updated_syllabi'
    )
    updated_at = models.DateTimeField(default=timezone.now)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='deactivated_syllabi'
    )
    # The reference PDF a syllabus was loaded from (``manage.py load_reference_syllabi``,
    # D8), e.g. "6th (New Syllabus)  Plan & Price.pdf"; NULL for one the Admin added.
    # Never edited: it is how a second run knows the reference was loaded, whatever the
    # Admin has since changed in its draft.
    reference_key = models.CharField(max_length=80, null=True, blank=True, editable=False)

    class Meta:
        db_table = 'sales_syllabi'
        verbose_name = 'Syllabus'
        verbose_name_plural = 'Syllabuses'
        ordering = ['-updated_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(deactivated_at__isnull=True, deactivated_by__isnull=True)
                | Q(deactivated_at__isnull=False, deactivated_by__isnull=False),
                name='sales_syllabi_deactivation_fields_together',
            ),
            models.UniqueConstraint(
                fields=['reference_key'],
                condition=Q(reference_key__isnull=False),
                name='sales_syllabi_one_per_reference',
            ),
        ]

    def __str__(self):
        return f'Syllabus {self.id}'


class SyllabusRevision(models.Model):
    """
    One version of what a syllabus says. The one with no publication is its
    draft -- at most one per syllabus, edited freely and deleted when the
    Admin discards it. Publishing stamps it; from then on neither it nor its
    chapters can change (sales.0002), and a later edit starts the next draft.

    The structure is the syllabus's from its first publication on
    (sales.services); its plan types are those the structure offers.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    syllabus = models.ForeignKey(Syllabus, on_delete=models.PROTECT, related_name='revisions')
    number = models.PositiveIntegerField()
    # The blue heading on the chapter pages (any text, e.g. "Grade 7 CBSE (Old Syllabus)"),
    # the line under it, and the heading of the packages page. Left empty, the line under
    # the title and the packages page's heading take their reference wording when drawn
    # (sales.wording), so they follow the structure and the title.
    title = models.CharField(max_length=TITLE_CHARS)
    subtitle = models.CharField(max_length=TITLE_CHARS, blank=True, default='')
    package_title = models.CharField(max_length=PACKAGE_TITLE_CHARS, blank=True, default='')
    grade = models.PositiveSmallIntegerField()
    board = models.CharField(max_length=10, choices=Board.choices)
    # e.g. "New Syllabus", "Old Syllabus"; empty when there is only one.
    syllabus_version = models.CharField(max_length=SYLLABUS_VERSION_CHARS, blank=True, default='')
    structure = models.CharField(max_length=20, choices=Structure.choices)
    # In PlanType order, each once (sales.services).
    plan_types = ArrayField(models.CharField(max_length=20, choices=PlanType.choices))
    # The packages page's closing list ("Personalized 1:1 live sessions", ...).
    inclusions = ArrayField(models.CharField(max_length=INCLUSION_CHARS), default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_syllabus_revisions'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='updated_syllabus_revisions'
    )
    updated_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='published_syllabus_revisions'
    )

    class Meta:
        db_table = 'sales_syllabus_revisions'
        verbose_name = 'Syllabus revision'
        verbose_name_plural = 'Syllabus revisions'
        ordering = ['syllabus', 'number']
        constraints = [
            models.UniqueConstraint(fields=['syllabus', 'number'], name='sales_syllabus_revisions_one_per_number'),
            models.UniqueConstraint(
                fields=['syllabus'],
                condition=Q(published_at__isnull=True),
                name='sales_syllabus_revisions_one_draft',
            ),
            models.CheckConstraint(condition=Q(number__gte=1), name='sales_syllabus_revisions_from_one'),
            models.CheckConstraint(
                condition=Q(published_at__isnull=True, published_by__isnull=True)
                | Q(published_at__isnull=False, published_by__isnull=False),
                name='sales_syllabus_revisions_publication_fields_together',
            ),
            models.CheckConstraint(
                condition=_text_within('title', TITLE_CHARS),
                name='sales_syllabus_revisions_title_text',
            ),
            models.CheckConstraint(
                condition=_empty_or_text_within('subtitle', TITLE_CHARS),
                name='sales_syllabus_revisions_subtitle_text',
            ),
            models.CheckConstraint(
                condition=_empty_or_text_within('package_title', PACKAGE_TITLE_CHARS),
                name='sales_syllabus_revisions_package_title_text',
            ),
            models.CheckConstraint(
                condition=Q(grade__gte=MIN_GRADE, grade__lte=MAX_GRADE),
                name='sales_syllabus_revisions_known_grade',
            ),
            models.CheckConstraint(condition=Q(board__in=Board.values), name='sales_syllabus_revisions_known_board'),
            models.CheckConstraint(
                condition=(
                    Q(structure=Structure.CHAPTER_WISE, plan_types__len__gte=1,
                      plan_types__contained_by=list(STRUCTURE_PLAN_TYPES[Structure.CHAPTER_WISE]))
                    | Q(structure=Structure.BRIDGE_COURSE, plan_types=list(STRUCTURE_PLAN_TYPES[Structure.BRIDGE_COURSE]))
                ),
                name='sales_syllabus_revisions_plan_types_of_structure',
            ),
            models.CheckConstraint(
                condition=Q(inclusions__len__lte=MAX_INCLUSIONS),
                name='sales_syllabus_revisions_inclusions_count',
            ),
        ]

    def __str__(self):
        return f'{self.syllabus_id} r{self.number}'

    @property
    def is_draft(self):
        return self.published_at is None


class SyllabusChapter(models.Model):
    """
    One row of a revision's chapter table, at ``position`` (its serial number,
    or its day in a Bridge Course). A chapter-wise syllabus counts its Regular
    and Revision classes; a Bridge Course only its classes. A Chapter Plan sells
    a choice of these rows: it has none of its own.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # A draft's chapters go with it when it is discarded; a published
    # revision can be deleted by nothing (sales.0002), nor its chapters.
    revision = models.ForeignKey(SyllabusRevision, on_delete=models.CASCADE, related_name='chapters')
    position = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=CHAPTER_NAME_CHARS)
    regular_classes = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    revision_classes = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    bridge_classes = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)

    class Meta:
        db_table = 'sales_syllabus_chapters'
        verbose_name = 'Syllabus chapter'
        verbose_name_plural = 'Syllabus chapters'
        ordering = ['revision', 'position']
        constraints = [
            # Deferred, so a reordered draft can swap positions inside one transaction.
            models.UniqueConstraint(
                fields=['revision', 'position'],
                name='sales_syllabus_chapters_one_per_position',
                deferrable=models.Deferrable.DEFERRED,
            ),
            models.CheckConstraint(condition=Q(position__gte=1), name='sales_syllabus_chapters_from_one'),
            models.CheckConstraint(
                condition=_text_within('name', CHAPTER_NAME_CHARS),
                name='sales_syllabus_chapters_name_text',
            ),
            # Chapter-wise counts, or a Bridge Course's -- never both.
            models.CheckConstraint(
                condition=(
                    Q(regular_classes__isnull=False, revision_classes__isnull=False, bridge_classes__isnull=True)
                    | Q(regular_classes__isnull=True, revision_classes__isnull=True, bridge_classes__isnull=False)
                ),
                name='sales_syllabus_chapters_counts_of_one_structure',
            ),
            models.CheckConstraint(
                condition=Q(regular_classes__isnull=True) | _classes('regular_classes'),
                name='sales_syllabus_chapters_regular_classes_half_steps',
            ),
            models.CheckConstraint(
                condition=Q(revision_classes__isnull=True) | _classes('revision_classes'),
                name='sales_syllabus_chapters_revision_classes_half_steps',
            ),
            models.CheckConstraint(
                condition=Q(bridge_classes__isnull=True) | _classes('bridge_classes'),
                name='sales_syllabus_chapters_bridge_classes_half_steps',
            ),
        ]

    def __str__(self):
        return f'{self.position}. {self.name}'


class PricingVersion(models.Model):
    """
    One version of the global pricing: a per-class standard fee and the offer
    fee packages are priced at, in one currency, and the single-payment
    privilege -- ``single_payment_percent`` off the packages it lists
    (PRIVILEGE_PLAN_TYPES), rounded to the nearest whole currency unit (sales.pricing). It takes effect when
    saved (``effective_from``) and applies until the next version does. Never
    changed or removed (sales.0002): a change adds the next version.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(unique=True)
    # ISO 4217, e.g. "AED".
    currency = models.CharField(max_length=3)
    standard_fee = models.DecimalField(max_digits=10, decimal_places=2)
    offer_fee = models.DecimalField(max_digits=10, decimal_places=2)
    single_payment_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    single_payment_plan_types = ArrayField(
        models.CharField(max_length=20, choices=PlanType.choices), default=list, blank=True,
    )
    # Why it changed, for the history.
    note = models.CharField(max_length=255, blank=True, default='')
    effective_from = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='pricing_versions'
    )

    class Meta:
        db_table = 'sales_pricing_versions'
        verbose_name = 'Pricing version'
        verbose_name_plural = 'Pricing versions'
        ordering = ['-version']
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name='sales_pricing_versions_from_one'),
            models.CheckConstraint(condition=Q(currency__regex=r'^[A-Z]{3}$'), name='sales_pricing_versions_currency_code'),
            models.CheckConstraint(condition=Q(standard_fee__gt=0), name='sales_pricing_versions_standard_fee_positive'),
            models.CheckConstraint(
                condition=Q(offer_fee__gt=0, offer_fee__lte=F('standard_fee')),
                name='sales_pricing_versions_offer_within_standard',
            ),
            models.CheckConstraint(
                condition=Q(single_payment_percent__gte=0, single_payment_percent__lt=100),
                name='sales_pricing_versions_single_payment_percent_range',
            ),
            models.CheckConstraint(
                condition=Q(single_payment_plan_types__contained_by=list(PRIVILEGE_PLAN_TYPES)),
                name='sales_pricing_versions_known_plan_types',
            ),
        ]

    def __str__(self):
        return f'Pricing v{self.version}'
