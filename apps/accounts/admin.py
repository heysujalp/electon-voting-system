"""
ElectON v2 — Accounts admin configuration.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AdminLoginVerification, CustomUser, EmailVerificationSession


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'full_name', 'email_verified', 'is_active', 'created_at')
    list_filter = ('email_verified', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'full_name')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('ElectON', {
            'fields': (
                'full_name',
                'email',
                'email_verified',
                'is_active',
                'is_staff',
                'is_superuser',
                'created_at',
                'updated_at',
            ),
        }),
        ('Permissions', {'fields': ('groups', 'user_permissions')}),
    )


@admin.register(EmailVerificationSession)
class EmailVerificationSessionAdmin(admin.ModelAdmin):
    list_display = ('email', 'session_id', 'code_expires_at', 'resend_attempts', 'created_at')
    readonly_fields = ('created_at',)
    search_fields = ('email',)


@admin.register(AdminLoginVerification)
class AdminLoginVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_verified', 'attempts', 'code_expires_at', 'created_at')
    readonly_fields = ('created_at',)
    list_filter = ('is_verified',)
