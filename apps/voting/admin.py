"""ElectON v2 — Voting admin."""

from django.contrib import admin

from .models import Vote, VoterAccessRequest, VoterCredential


@admin.register(VoterCredential)
class VoterCredentialAdmin(admin.ModelAdmin):
    list_display = (
        'voter_email', 'voter_name', 'election', 'one_time_username',
        'has_voted', 'is_revoked', 'invitation_sent', 'created_at',
    )
    list_filter = ('election', 'has_voted', 'is_revoked', 'invitation_sent')
    search_fields = ('voter_email', 'voter_name', 'one_time_username')
    readonly_fields = ('one_time_password_hash', 'created_at', 'updated_at')


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('election', 'post', 'candidate', 'voter_hash_short', 'timestamp')
    list_filter = ('election', 'post', 'blockchain_confirmed')
    readonly_fields = ('voter_hash', 'timestamp', 'blockchain_tx_hash', 'blockchain_slot')

    @admin.display(description='Voter Hash')
    def voter_hash_short(self, obj):
        return obj.voter_hash[:16] + '…'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VoterAccessRequest)
class VoterAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'election', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'election')
    search_fields = ('email', 'name')
    readonly_fields = ('created_at', 'updated_at')
