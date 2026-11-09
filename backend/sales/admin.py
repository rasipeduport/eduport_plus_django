from django.contrib import admin

from bookings.admin import ReadOnlyAdmin

from .models import PricingVersion, Syllabus, SyllabusChapter, SyllabusRevision


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
