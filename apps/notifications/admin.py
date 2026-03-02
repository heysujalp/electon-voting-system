"""ElectON v2 — Notifications admin."""

from django.contrib import admin

from .models import EmailLog, Webhook


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('subject', 'recipient_email', 'status', 'election', 'sent_at', 'created_at')
    list_filter = ('status', 'template_name', 'election')
    search_fields = ('recipient_email', 'subject')
    readonly_fields = ('recipient_email', 'subject', 'template_name', 'status',
                       'error_message', 'election', 'sent_at', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ('pk', 'election', 'url', 'is_active', 'failure_count', 'last_triggered')
    list_filter = ('is_active', 'election')
    search_fields = ('url', 'election__name')
    readonly_fields = ('last_triggered', 'last_status_code', 'failure_count', 'created_at', 'updated_at')
