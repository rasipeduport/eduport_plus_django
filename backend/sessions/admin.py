from django.contrib import admin
from .models import Session, SessionFile

class SessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'student', 'tutor', 'start_time', 'end_time', 'status', 'rating')
    list_filter = ('status', 'rating', 'start_time')
    search_fields = ('title', 'student__full_name', 'student__student_code', 'tutor__full_name', 'tutor__email')
    ordering = ('-start_time',)
    
    fieldsets = (
        (None, {'fields': ('student', 'title', 'tutor')}),
        ('Schedule', {'fields': ('start_time', 'end_time')}),
        ('Links', {'fields': ('recording_link', 'notes_link', 'homework_link')}),
        ('Feedback & Status', {'fields': ('status', 'rating', 'cancellation_reason')}),
        ('Series Metadata', {'fields': ('series_id', 'class_number')}),
        ('Metadata', {'fields': ('created_at', 'updated_at')}),
    )
    # Who teaches a class, when, and whether it is still on are scheduling
    # decisions: the sessions API checks them (quota, the student's and the
    # tutor's other classes, Demo/Diagnostic bookings, an active tutor) under
    # the scheduling lock. The admin can neither edit them nor add a class,
    # so it cannot double-book a tutor; links, feedback and deletion stay.
    readonly_fields = ('student', 'tutor', 'start_time', 'end_time', 'status', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

admin.site.register(Session, SessionAdmin)


class SessionFileAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'field', 'session', 'content_type', 'size_bytes', 'uploaded_by', 'created_at')
    list_filter = ('field', 'content_type')
    search_fields = ('file_name', 'session__title', 'session__student__student_code')
    readonly_fields = ('id', 'created_at')

admin.site.register(SessionFile, SessionFileAdmin)
