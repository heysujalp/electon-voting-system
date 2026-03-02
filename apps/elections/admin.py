"""
ElectON v2 — Elections admin configuration.
"""
from django.contrib import admin

from .models import Election, Post


class PostInline(admin.TabularInline):
    model = Post
    extra = 0
    fields = ('name', 'order')


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'current_status', 'start_time', 'end_time', 'created_at')
    list_filter = ('is_launched',)
    search_fields = ('name', 'created_by__username')
    readonly_fields = ('election_uuid', 'created_at', 'updated_at', 'launch_time')
    inlines = [PostInline]
    date_hierarchy = 'created_at'

    @admin.display(description='Status')
    def current_status(self, obj):
        return obj.current_status


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('name', 'election', 'order')
    list_filter = ('election',)
