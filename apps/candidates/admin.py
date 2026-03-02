"""ElectON v2 — Candidates admin."""

from django.contrib import admin

from .models import Candidate


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'post', 'election', 'has_image', 'created_at')
    list_filter = ('election', 'post')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(boolean=True, description='Image')
    def has_image(self, obj):
        return bool(obj.image)
