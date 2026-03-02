"""
ElectON v2 — Audit admin configuration.
"""
from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'user', 'ip_address', 'election')
    list_filter = ('action', 'timestamp')
    search_fields = ('user__username', 'ip_address', 'details')
    readonly_fields = ('action', 'user', 'ip_address', 'user_agent', 'details', 'election', 'timestamp')
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False  # Audit logs are created programmatically only

    def has_change_permission(self, request, obj=None):
        return False  # Immutable

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Only superusers can purge
