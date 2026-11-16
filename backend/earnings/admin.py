from django.contrib import admin

from .models import (
    EarningEntry,
    EarningReview,
    EarningsRate,
    EarningsSyncRun,
    TutorEarningsActivation,
    TutorEarningsPricing,
    TutorPayment,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Shown for audit only: rates, the ledger and payments change through the Hub's audited actions, never here."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TutorEarningsActivation)
class TutorEarningsActivationAdmin(ReadOnlyAdmin):
    """Shows when Tutor Earnings was activated; recorded by its migration, never edited here."""

    list_display = ('activated_at',)
    readonly_fields = ('activated_at',)


@admin.register(TutorEarningsPricing)
class TutorEarningsPricingAdmin(ReadOnlyAdmin):
    list_display = ('started_at', 'started_by')


@admin.register(EarningsRate)
class EarningsRateAdmin(ReadOnlyAdmin):
    list_display = ('class_type', 'tutor', 'amount', 'effective_from', 'initial', 'created_by', 'created_at')
    list_filter = ('class_type', 'initial')


@admin.register(EarningEntry)
class EarningEntryAdmin(ReadOnlyAdmin):
    list_display = ('kind', 'tutor', 'class_type', 'month', 'units', 'rate', 'rate_source', 'amount', 'created_at')
    list_filter = ('kind', 'class_type', 'rate_source')


@admin.register(EarningReview)
class EarningReviewAdmin(ReadOnlyAdmin):
    list_display = ('entry', 'created_by', 'created_at')


@admin.register(TutorPayment)
class TutorPaymentAdmin(ReadOnlyAdmin):
    list_display = ('tutor', 'amount', 'paid_on', 'method', 'reference', 'recorded_by', 'voided_at')
    list_filter = ('method',)


@admin.register(EarningsSyncRun)
class EarningsSyncRunAdmin(ReadOnlyAdmin):
    list_display = ('started_at', 'status', 'trigger', 'earned_count', 'waiting_count', 'skipped_count')
    list_filter = ('status', 'trigger')
