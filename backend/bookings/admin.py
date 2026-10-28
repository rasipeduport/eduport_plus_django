from django.contrib import admin, messages

from .booking_service import cancel_booking
from .models import Booking, BookingSlot, BookingStatus, Lead, SlotTime


class ReadOnlyAdmin(admin.ModelAdmin):
    """
    Booking rows are written only by bookings.booking_service and
    ``manage.py booking_schedule``, which audit every change; the admin shows
    them and offers the audited actions below.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SlotTime)
class SlotTimeAdmin(ReadOnlyAdmin):
    list_display = ('booking_type', 'start_time', 'is_active', 'updated_at')
    list_filter = ('booking_type', 'is_active')


@admin.register(BookingSlot)
class BookingSlotAdmin(ReadOnlyAdmin):
    list_display = ('booking_type', 'local_date', 'local_time', 'capacity', 'closed_at')
    list_filter = ('booking_type',)
    date_hierarchy = 'local_date'


@admin.register(Lead)
class LeadAdmin(ReadOnlyAdmin):
    list_display = ('student_name', 'parent_name', 'phone_key', 'grade', 'source', 'owner_bde', 'created_at')
    list_filter = ('source',)
    search_fields = ('student_name', 'parent_name', 'phone_key')
    list_select_related = ('owner_bde',)


@admin.register(Booking)
class BookingAdmin(ReadOnlyAdmin):
    list_display = ('booking_type', 'slot', 'lead', 'seat', 'status', 'referral_status', 'attributed_bde', 'created_at')
    list_filter = ('booking_type', 'status', 'referral_status')
    list_select_related = ('slot', 'lead', 'attributed_bde')
    actions = ['cancel_selected']

    @admin.action(description='Cancel selected bookings')
    def cancel_selected(self, request, queryset):
        cancelled = 0
        for booking in queryset.filter(status=BookingStatus.BOOKED):
            _booking, changed = cancel_booking(booking, actor=request.user, reason='Cancelled in the Django admin.')
            cancelled += int(changed)
        self.message_user(request, f'Cancelled {cancelled} booking(s).', messages.SUCCESS)
