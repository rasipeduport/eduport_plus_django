from django.contrib import admin

from bookings.admin import ReadOnlyAdmin

from .models import PricingVersion, Quote, QuoteChapter, QuoteLine, Syllabus, SyllabusChapter, SyllabusRevision


@admin.register(Syllabus)
class SyllabusAdmin(ReadOnlyAdmin):
    """Shown and never edited here: syllabuses change only through the Hub (sales.services), which audits each change."""
    list_display = ('id', 'reference_key', 'created_by', 'created_at', 'updated_by', 'updated_at', 'deactivated_at')
    list_select_related = ('created_by', 'updated_by')


class SyllabusChapterInline(admin.TabularInline):
    model = SyllabusChapter
    fields = ('position', 'name', 'regular_classes', 'revision_classes', 'bridge_classes')
    readonly_fields = fields
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SyllabusRevision)
class SyllabusRevisionAdmin(ReadOnlyAdmin):
    """Every revision with its chapters. A published one can never change: a trigger refuses it."""
    list_display = ('title', 'syllabus', 'number', 'grade', 'board', 'structure', 'published_at', 'updated_at')
    list_filter = ('structure', 'board')
    list_select_related = ('syllabus',)
    inlines = [SyllabusChapterInline]


@admin.register(PricingVersion)
class PricingVersionAdmin(ReadOnlyAdmin):
    """Every pricing version, newest first. Append-only: a trigger refuses any change."""
    list_display = ('version', 'currency', 'standard_fee', 'offer_fee', 'single_payment_percent', 'effective_from', 'created_by')
    list_select_related = ('created_by',)


class QuoteLineInline(admin.TabularInline):
    model = QuoteLine
    fields = ('position', 'plan_type', 'title', 'classes', 'fee_per_class', 'total', 'single_payment_price',
              'single_payment_saving')
    readonly_fields = fields
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


class QuoteChapterInline(admin.TabularInline):
    model = QuoteChapter
    fields = ('chapter', 'classes')
    readonly_fields = fields
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Quote)
class QuoteAdmin(ReadOnlyAdmin):
    """Every quote with its packages and chapters, as it was issued. Its figures never change: a trigger refuses it."""
    list_display = ('number', 'status', 'plan_type', 'currency', 'total_fee', 'payable_amount', 'created_by', 'created_at')
    list_filter = ('status', 'plan_type')
    list_select_related = ('created_by',)
    inlines = [QuoteLineInline, QuoteChapterInline]
