from django.contrib import admin
from .models import Student, StudentNote

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
        # total_class_quota is read-only: it is synced from the enrolment
        # sheet (students.quota_sync), and an edit here would be reverted by
        # the next sync run. Shown rather than hidden so an operator can still
        # see the figure the sheet produced.
        ('Quota & Remarks', {'fields': ('total_class_quota', 'remarks_for_mentor')}),
        ('Status', {'fields': ('status', 'status_note')}),
        ('Metadata', {'fields': ('created_at', 'updated_at')}),
    )
    readonly_fields = ('created_at', 'updated_at', 'total_class_quota')

admin.site.register(Student, StudentAdmin)


class StudentNoteAdmin(admin.ModelAdmin):
    list_display = ('student', 'author_name', 'author_role', 'created_at', 'edited_at')
    list_filter = ('author_role',)
    search_fields = ('student__student_code', 'student__full_name', 'author_name', 'body')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'edited_at')


admin.site.register(StudentNote, StudentNoteAdmin)
