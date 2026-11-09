"""
What the Admin sends to write a syllabus draft or a pricing version, checked
here before sales.services writes it. Errors come back per field, a chapter's
by its row's index: ``{"chapters": {"1": {"revision_classes": [...]}}}``.
"""
from decimal import Decimal

from rest_framework import serializers

from .models import (
    CHAPTER_NAME_CHARS, CLASS_STEP, INCLUSION_CHARS, MAX_CHAPTERS, MAX_CLASSES_PER_CHAPTER, MAX_GRADE, MAX_INCLUSIONS,
    MIN_GRADE, PACKAGE_TITLE_CHARS, PRIVILEGE_PLAN_TYPES, STRUCTURE_PLAN_TYPES, SYLLABUS_VERSION_CHARS, TITLE_CHARS,
    Board, PlanType, Structure,
)
from .wording import default_inclusions


def ordered_plan_types(plan_types):
    """``plan_types`` each once, in PlanType order -- how a revision stores them."""
    return [plan_type for plan_type in PlanType.values if plan_type in set(plan_types)]


class ClassCountField(serializers.DecimalField):
    """A number of classes: whole or half (1, 1.5), from 0 to MAX_CLASSES_PER_CHAPTER."""

    def __init__(self, **kwargs):
        super().__init__(
            max_digits=3, decimal_places=1, min_value=Decimal('0'), max_value=MAX_CLASSES_PER_CHAPTER,
            required=False, allow_null=True, **kwargs,
        )

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value % CLASS_STEP:
            raise serializers.ValidationError('Use whole or half classes, such as 2 or 1.5.')
        return value


class ChapterSerializer(serializers.Serializer):
    # A draft chapter's id keeps the row when the draft is saved again; a new row has none.
    id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(max_length=CHAPTER_NAME_CHARS)
    regular_classes = ClassCountField()
    revision_classes = ClassCountField()
    bridge_classes = ClassCountField()


class SyllabusContentSerializer(serializers.Serializer):
    """
    Everything a revision says. A subtitle or package title left empty stays
    empty: it takes the reference wording when shown or drawn (sales.wording).
    Inclusions left out take the reference's three lines for the board.
    """
    title = serializers.CharField(max_length=TITLE_CHARS)
    subtitle = serializers.CharField(max_length=TITLE_CHARS, required=False, allow_blank=True, default='')
    package_title = serializers.CharField(max_length=PACKAGE_TITLE_CHARS, required=False, allow_blank=True, default='')
    grade = serializers.IntegerField(min_value=MIN_GRADE, max_value=MAX_GRADE)
    board = serializers.ChoiceField(choices=Board.choices)
    syllabus_version = serializers.CharField(
        max_length=SYLLABUS_VERSION_CHARS, required=False, allow_blank=True, default='',
    )
    structure = serializers.ChoiceField(choices=Structure.choices)
    plan_types = serializers.ListField(child=serializers.ChoiceField(choices=PlanType.choices), allow_empty=True)
    # Left out: the reference's three lines. An empty list: none.
    inclusions = serializers.ListField(
        child=serializers.CharField(max_length=INCLUSION_CHARS), max_length=MAX_INCLUSIONS, required=False,
    )
    chapters = ChapterSerializer(many=True, allow_empty=False, max_length=MAX_CHAPTERS)

    def validate(self, data):
        structure = data['structure']
        errors = {}

        plan_types = ordered_plan_types(data['plan_types'])
        if structure == Structure.BRIDGE_COURSE:
            # A Bridge Course is sold as itself, whatever was ticked: whole, or by the day when it is bought.
            plan_types = list(STRUCTURE_PLAN_TYPES[structure])
        elif not plan_types:
            errors['plan_types'] = ['Choose at least one plan type.']
        elif set(plan_types) - set(STRUCTURE_PLAN_TYPES[structure]):
            errors['plan_types'] = ['Bridge Course is a structure of its own: it is not a plan of a chapter-wise syllabus.']
        data['plan_types'] = plan_types

        # Keyed by row, failing rows only -- the shape DRF gives the rows' own field errors.
        chapter_errors = {
            index: row_errors for index, chapter in enumerate(data['chapters'])
            if (row_errors := self._chapter_errors(chapter, structure))
        }
        if chapter_errors:
            errors['chapters'] = chapter_errors
        ids = [str(chapter['id']) for chapter in data['chapters'] if chapter.get('id')]
        if len(ids) != len(set(ids)):
            errors.setdefault('chapters', ['Each chapter may appear only once.'])
        if errors:
            raise serializers.ValidationError(errors)

        for chapter in data['chapters']:
            if structure == Structure.BRIDGE_COURSE:
                chapter['regular_classes'] = chapter['revision_classes'] = None
            else:
                chapter['bridge_classes'] = None
        data['subtitle'] = data['subtitle'].strip()
        data['package_title'] = data['package_title'].strip()
        data['syllabus_version'] = data['syllabus_version'].strip()
        if 'inclusions' not in data:
            data['inclusions'] = default_inclusions(data['board'])
        data['inclusions'] = [line.strip() for line in data['inclusions'] if line.strip()]
        return data

    @staticmethod
    def _chapter_errors(chapter, structure):
        needed = ('bridge_classes',) if structure == Structure.BRIDGE_COURSE else ('regular_classes', 'revision_classes')
        return {field: ['Enter the number of classes.'] for field in needed if chapter.get(field) is None}


class SyllabusDraftSerializer(SyllabusContentSerializer):
    """A save of an existing draft: its content, and the draft as the caller last saw it."""
    updated_at = serializers.DateTimeField()


class DraftTokenSerializer(serializers.Serializer):
    """Publishing or discarding a draft names the draft the caller saw: its number and when it was last saved."""
    revision = serializers.IntegerField(min_value=1)
    updated_at = serializers.DateTimeField()


class PricingVersionSerializer(serializers.Serializer):
    currency = serializers.RegexField(r'^[A-Za-z]{3}$', error_messages={'invalid': 'Use a three-letter currency code, such as AED.'})
    standard_fee = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    offer_fee = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    single_payment_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('99.99'),
    )
    # Only the packages a card is printed for: Regular + Revision prints the Regular and
    # Revision cards, and a Chapter Plan has none yet (models.PRIVILEGE_PLAN_TYPES).
    single_payment_plan_types = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[(value, PlanType(value).label) for value in PRIVILEGE_PLAN_TYPES],
            error_messages={'invalid_choice': 'The privilege applies to the Regular, Revision or Bridge Course package.'},
        ),
        allow_empty=True, required=False, default=list,
    )
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')

    def validate_currency(self, value):
        return value.upper()

    def validate(self, data):
        if data['offer_fee'] > data['standard_fee']:
            raise serializers.ValidationError({'offer_fee': ['The offer fee cannot be more than the standard fee.']})
        # The privilege is on (a discount and the packages it applies to) or off (neither): packages
        # chosen with no discount would read as on while the PDFs show no Single-Payment Privilege box.
        if data['single_payment_percent'] and not data['single_payment_plan_types']:
            raise serializers.ValidationError(
                {'single_payment_plan_types': ['Choose the plans the single-payment privilege applies to.']},
            )
        if not data['single_payment_percent'] and data['single_payment_plan_types']:
            raise serializers.ValidationError(
                {'single_payment_percent': ['Enter the single-payment discount for the packages you chose, or choose none.']},
            )
        data['single_payment_plan_types'] = ordered_plan_types(data['single_payment_plan_types'])
        data['note'] = data['note'].strip()
        return data
