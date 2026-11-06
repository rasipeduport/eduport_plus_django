from django.contrib import admin, messages

from .booking_service import BookingError, cancel_booking
from .demo_invites import revoke_invite
from .models import BookingEvent, BookingSlot, CancelReason, DemoBooking, DemoInvite, DiagnosticBooking, Lead, SlotTime


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


class BookingAdmin(ReadOnlyAdmin):
    """
    One booking table (Diagnostic or Demo). The assigned tutor is shown, never
    set here: assignments are made by booking_service.assign_tutor, which
    checks the tutor is free.
    """
    list_display = (
        'slot', 'lead', 'seat', 'status', 'channel', 'assigned_tutor', 'referral_status', 'attributed_bde', 'created_at',
    )
    list_filter = ('status', 'channel', 'referral_status')
    list_select_related = ('slot', 'lead', 'assigned_tutor', 'attributed_bde')
    actions = ['cancel_selected', 'mark_selected_no_show']

    @admin.action(description='Cancel selected bookings (reason: Other)')
    def cancel_selected(self, request, queryset):
        self._cancel(request, queryset, CancelReason.OTHER)

    @admin.action(description='Mark selected bookings as No-show (scheduled time passed)')
    def mark_selected_no_show(self, request, queryset):
        self._cancel(request, queryset, CancelReason.NO_SHOW)

    def _cancel(self, request, queryset, reason_code):
        # Only booked bookings: a completed or rescheduled one can no longer be
        # cancelled, and No-show waits for the slot's scheduled time to pass,
        # whether or not the tutor started it -- the service refuses both too.
        # The reason is a code, never free text (M1).
        cancelled, skipped = 0, 0
        for booking in queryset:
            try:
                _booking, changed = cancel_booking(booking, reason_code=reason_code, actor=request.user)
            except BookingError:
                changed = False
            if changed:
                cancelled += 1
            else:
                skipped += 1
        message = f'Cancelled {cancelled} booking(s).'
        if skipped:
            message += f' Skipped {skipped} that could not be cancelled this way.'
        self.message_user(request, message, messages.SUCCESS)


@admin.register(DiagnosticBooking)
class DiagnosticBookingAdmin(BookingAdmin):
    pass


@admin.register(DemoBooking)
class DemoBookingAdmin(BookingAdmin):
    pass


@admin.register(DemoInvite)
class DemoInviteAdmin(ReadOnlyAdmin):
    """
    Demo invitations (bookings.demo_invites), shown -- never the token, which
    would open the parent's booking page -- and revoked through the audited
    action below; they are issued from the Hub only.
    """
    list_display = ('created_at', 'diagnostic_booking', 'lead', 'status_label', 'expires_at', 'used_at', 'created_by')
    list_select_related = ('diagnostic_booking__slot', 'lead', 'created_by')
    exclude = ('token',)
    actions = ['revoke_selected']

    @admin.display(description='Status')
    def status_label(self, obj):
        return obj.get_status_display()

    @admin.action(description='Revoke selected invitations (their links stop working)')
    def revoke_selected(self, request, queryset):
        revoked = sum(revoke_invite(invite, request.user, request=request)[1] for invite in queryset)
        message = f'Revoked {revoked} invitation(s).'
        if revoked < len(queryset):
            message += f' Skipped {len(queryset) - revoked} that were not active.'
        self.message_user(request, message, messages.SUCCESS)


@admin.register(BookingEvent)
class BookingEventAdmin(ReadOnlyAdmin):
    # Never a name or phone number: the event's data holds ids and values only.
    list_display = ('created_at', 'kind', 'diagnostic_booking', 'demo_booking', 'actor')
    list_filter = ('kind',)
    list_select_related = ('diagnostic_booking', 'demo_booking', 'actor')
