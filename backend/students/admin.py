from django.contrib import admin
from .models import Student

class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_code', 'full_name', 'mobile_number', 'grade', 'status', 'mentor', 'tutor')
    list_filter = ('status', 'grade', 'syllabus', 'admission_date')
    search_fields = ('student_code', 'full_name', 'school_name', 'mobile_number', 'profile__email')
    ordering = ('student_code',)
    
    fieldsets = (
        (None, {'fields': ('profile', 'student_code', 'full_name')}),
        ('Academic Info', {'fields': ('school_name', 'grade', 'syllabus', 'admission_date')}),
        ('Contact Info', {'fields': ('mobile_number', 'country', 'state', 'timezone')}),
        ('Staff Assignment', {'fields': ('mentor', 'tutor', 'meet_link')}),
        ('Quota & Remarks', {'fields': ('total_class_quota', 'remarks_for_mentor')}),
        ('Status', {'fields': ('status', 'status_note')}),
        ('Metadata', {'fields': ('created_at', 'updated_at')}),
    )
    readonly_fields = ('created_at', 'updated_at')

admin.site.register(Student, StudentAdmin)
