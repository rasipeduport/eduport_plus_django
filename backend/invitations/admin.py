from django.contrib import admin
from .models import Invitation

class InvitationAdmin(admin.ModelAdmin):
    list_display = ('student', 'account', 'role', 'status', 'invited_by', 'created_at')
    list_filter = ('role', 'status', 'created_at')
    search_fields = ('email', 'invited_by__full_name', 'invited_by__email')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('email', 'role', 'status')}),
        ('Invitation Details', {'fields': ('student', 'account', 'activated_at', 'invited_by', 'extra_data')}),
        ('Metadata', {'fields': ('created_at', 'updated_at')}),
    )
    readonly_fields = ('student', 'account', 'activated_at', 'created_at', 'updated_at')

admin.site.register(Invitation, InvitationAdmin)
