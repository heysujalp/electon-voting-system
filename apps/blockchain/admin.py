"""Blockchain app admin — read-only views for Solana deployments and transactions."""

from django.contrib import admin

from .models import BlockchainArchive, BlockchainTransaction, ContractDeployment


@admin.register(ContractDeployment)
class ContractDeploymentAdmin(admin.ModelAdmin):
    list_display = (
        "election",
        "program_address",
        "network",
        "deployed_at",
    )
    list_filter = ("network",)
    search_fields = ("program_address", "deploy_tx_signature")
    readonly_fields = (
        "election",
        "program_address",
        "deploy_tx_signature",
        "deploy_slot",
        "network",
        "deployed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BlockchainTransaction)
class BlockchainTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "tx_sig_short",
        "election",
        "tx_type",
        "status",
        "compute_units",
        "created_at",
    )
    list_filter = ("tx_type", "status")
    search_fields = ("tx_signature",)
    readonly_fields = (
        "election",
        "tx_type",
        "tx_signature",
        "slot",
        "compute_units",
        "status",
        "error_message",
        "created_at",
    )

    def tx_sig_short(self, obj):
        if obj.tx_signature:
            return f"{obj.tx_signature[:10]}…{obj.tx_signature[-6:]}"
        return "—"

    tx_sig_short.short_description = "TX Signature"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BlockchainArchive)
class BlockchainArchiveAdmin(admin.ModelAdmin):
    """Read-only view of post-closure election archives."""

    list_display = (
        "election",
        "total_voters",
        "total_votes_cast",
        "on_chain_slot",
        "archived_at",
        "account_closed_at",
    )
    list_filter = ("archived_at",)
    search_fields = ("election__name",)
    readonly_fields = (
        "election",
        "merkle_root",
        "voted_bitfield",
        "vote_counts",
        "config_hash",
        "total_voters",
        "total_votes_cast",
        "on_chain_slot",
        "archived_at",
        "account_closed_at",
        "rent_recovered_lamports",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False