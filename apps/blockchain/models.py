"""
Blockchain models — tracks on-chain election state and Solana transactions.
"""

from django.db import models


class ContractDeployment(models.Model):
    """Tracks a deployed Solana election PDA for a specific election."""

    election = models.OneToOneField(
        "elections.Election",
        on_delete=models.CASCADE,
        related_name="contract_deployment",
    )
    # Solana PDA (base58, ~44 chars)
    program_address = models.CharField(max_length=50, unique=True, default='')
    # Solana tx signature (base58, ~88 chars)
    deploy_tx_signature = models.CharField(max_length=100, default='')
    # Solana slot (not block number)
    deploy_slot = models.PositiveBigIntegerField(default=0)
    network = models.CharField(
        max_length=20,
        choices=[
            ("localnet", "Solana Localnet (test-validator)"),
            ("devnet", "Solana Devnet"),
            ("testnet", "Solana Testnet"),
            ("mainnet-beta", "Solana Mainnet Beta"),
        ],
    )
    deployed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blockchain_contract_deployment"
        ordering = ["-deployed_at"]

    def __str__(self):
        return f"{self.election.name} → {self.program_address[:12]}…"


class BlockchainTransaction(models.Model):
    """Tracks every Solana transaction for audit and monitoring."""

    class TxType(models.TextChoices):
        DEPLOY = "deploy", "Deploy Election"
        REGISTER_VOTERS = "register_voters", "Register Voters"  # legacy — no longer created
        CAST_VOTE = "cast_vote", "Cast Vote"
        FINALIZE = "finalize", "Finalize Election"
        CLOSE = "close_election", "Close Election Account"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"

    election = models.ForeignKey(
        "elections.Election",
        on_delete=models.CASCADE,
        related_name="blockchain_transactions",
    )
    tx_type = models.CharField(max_length=30, choices=TxType.choices)
    # Solana signature (base58, ~88 chars)
    tx_signature = models.CharField(max_length=100, unique=True, default='')
    # Solana slot
    slot = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    # Solana compute units (replaces gas_used)
    compute_units = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "blockchain_transaction"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["election", "tx_type"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_tx_type_display()} — {self.tx_signature[:12]}… ({self.status})"


class BlockchainArchive(models.Model):
    """Snapshot of an election's on-chain state taken before the PDA is closed.

    Once ``close_election`` is called on Solana the account no longer exists;
    this model is the permanent record of the final tally and vote bitfield.
    """

    election = models.OneToOneField(
        "elections.Election",
        on_delete=models.CASCADE,
        related_name="blockchain_archive",
    )
    # 32-byte Merkle root of all eligible voter hashes
    merkle_root = models.BinaryField(max_length=32)
    # 1 bit per voter — bit N set means voter N voted
    voted_bitfield = models.BinaryField()
    # {"post_index": {"candidate_index": vote_count}};  stored as JSON
    vote_counts = models.JSONField(default=dict)
    # 32-byte SHA-256 of the election config snapshot
    config_hash = models.BinaryField(max_length=32)
    total_voters = models.PositiveIntegerField(default=0)
    total_votes_cast = models.PositiveIntegerField(default=0)
    # Solana slot at which the archive was read
    on_chain_slot = models.BigIntegerField(default=0)
    archived_at = models.DateTimeField(auto_now_add=True)
    # Set when the on-chain account was successfully closed
    account_closed_at = models.DateTimeField(null=True, blank=True)
    # Lamports returned to authority after account closure
    rent_recovered_lamports = models.BigIntegerField(default=0)

    class Meta:
        db_table = "blockchain_archive"

    def __str__(self):
        return f"Archive({self.election.name})"

    def voter_has_voted(self, voter_index: int) -> bool:
        """Check whether the voter at *voter_index* voted (bitfield lookup)."""
        bitfield = bytes(self.voted_bitfield)
        byte_idx = voter_index // 8
        bit_idx = voter_index % 8
        if byte_idx >= len(bitfield):
            return False
        return bool(bitfield[byte_idx] & (1 << bit_idx))
