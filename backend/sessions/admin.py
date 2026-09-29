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
    readonly_fields = ('created_at', 'updated_at')

admin.site.register(Session, SessionAdmin)


class SessionFileAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'field', 'session', 'content_type', 'size_bytes', 'uploaded_by', 'created_at')
    list_filter = ('field', 'content_type')
    search_fields = ('file_name', 'session__title', 'session__student__student_code')
    readonly_fields = ('id', 'created_at')

admin.site.register(SessionFile, SessionFileAdmin)
