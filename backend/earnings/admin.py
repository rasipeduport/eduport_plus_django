from django.contrib import admin

from .models import TutorEarningsActivation


@admin.register(TutorEarningsActivation)
class TutorEarningsActivationAdmin(admin.ModelAdmin):
    """Shows when Tutor Earnings was activated; recorded by its migration, never edited here."""

    list_display = ('activated_at',)
    readonly_fields = ('activated_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
