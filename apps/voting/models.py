"""
ElectON v2 — Voting models.

CRITICAL CHANGE vs V1:
  ``Vote`` no longer has a FK to ``VoterCredential``.  Instead an
  irreversible ``voter_hash`` (SHA-256 of credential-id + election-id
  + deployment salt) links a voter to their votes for uniqueness
  enforcement only.  DB access alone cannot reveal who voted for whom.

VoterCredential is essentially unchanged apart from:
  - Unnecessary ``phone`` / ``department`` / ``notes`` fields removed
  - ``invitation_successful`` renamed ``invitation_sent``
  - ``last_email_error_reason`` renamed ``invitation_error``
  - Blockchain fields for Merkle tree model
  - N-13: Dead code removed (blockchain_secret, _get_fernet, etc.)
  - N-14: Deprecated blockchain_registered field removed
"""
import secrets
import string

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


OFFLINE_VOTER_DOMAIN = '@electon.local'


# ------------------------------------------------------------------
# VoterCredential
# ------------------------------------------------------------------

class VoterCredential(models.Model):
    """One-time credential issued to a voter for a specific election."""

    election = models.ForeignKey(
        'elections.Election',
        on_delete=models.CASCADE,
        related_name='voter_credentials',
    )
    voter_email = models.EmailField()
    voter_name = models.CharField(max_length=255, blank=True, default='')

    one_time_username = models.CharField(max_length=255, unique=True)
    one_time_password_hash = models.CharField(max_length=255)

    # Status
    has_voted = models.BooleanField(default=False)
    is_revoked = models.BooleanField(default=False)
    invitation_sent = models.BooleanField(default=False)
    invitation_error = models.TextField(blank=True, default='')

    # Structured error code for invitation failures (allows UI to show clear reason)
    class InvitationErrorCode(models.TextChoices):
        INVALID_FORMAT  = 'INVALID_FORMAT',  'Invalid email address format'
        SMTP_REJECTED   = 'SMTP_REJECTED',   'Address rejected by mail server'
        SMTP_ERROR      = 'SMTP_ERROR',      'Mail server connection failure'
        RATE_LIMITED    = 'RATE_LIMITED',    'Daily sending limit reached'
        PROVIDER_ERROR  = 'PROVIDER_ERROR',  'Email provider error'
        UNKNOWN         = 'UNKNOWN',         'Unknown delivery failure'

    invitation_error_code = models.CharField(
        max_length=30,
        choices=InvitationErrorCode.choices,
        blank=True,
        default='',
        help_text='Machine-readable reason for invitation failure.',
    )

    # Batch tracking (for offline PDF credentials)
    batch_number = models.CharField(max_length=20, blank=True, default='', db_index=True)

    # Timestamps for audit trail
    invited_at = models.DateTimeField(null=True, blank=True)
    voted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    credentials_resent_at = models.DateTimeField(null=True, blank=True)

    # Blockchain integration (Merkle Tree model)
    # Hex-encoded 32-byte SHA-256 leaf hash committed to the Merkle tree
    blockchain_voter_hash = models.CharField(max_length=66, blank=True, default='')
    # 0-based position in the Merkle tree (set during deploy_election)
    blockchain_voter_index = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['election', 'voter_email'], name='unique_voter_per_election'),
            # N-12: Prevent duplicate voter indices within an election
            models.UniqueConstraint(
                fields=['election', 'blockchain_voter_index'],
                condition=models.Q(blockchain_voter_index__isnull=False),
                name='unique_voter_index_per_election',
            ),
        ]
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['election', 'has_voted']),
            models.Index(fields=['election', 'invitation_sent']),
            # N-05: Index for fast voter hash lookups during vote submission & verification
            models.Index(fields=['election', 'blockchain_voter_hash'], name='idx_cred_bc_hash'),
        ]

    def __str__(self):
        return f"{self.voter_email} — {self.election.name}"

    # ------------------------------------------------------------------
    # Credential generation
    # ------------------------------------------------------------------

    @classmethod
    def generate_credentials(cls, election, voter_email, voter_name=''):
        """Create a credential with auto-generated username & password."""
        username = cls._generate_unique_username()
        password = cls._generate_password()

        credential = cls.objects.create(
            election=election,
            voter_email=voter_email,
            voter_name=voter_name,
            one_time_username=username,
            one_time_password_hash=make_password(password),
        )
        # Attach the plaintext password so callers can email it
        credential._plain_password = password  # noqa: SLF001
        return credential

    @classmethod
    def _generate_unique_username(cls):
        """XXXXXXXX (8-char alphanumeric) with collision protection."""
        charset = string.ascii_uppercase + string.digits
        for _ in range(1000):
            username = ''.join(secrets.choice(charset) for _ in range(8))
            if not cls.objects.filter(one_time_username=username).exists():
                return username
        raise RuntimeError("Unable to generate unique username after 1000 attempts")

    @classmethod
    def _generate_password(cls):
        """10-char password guaranteed to contain upper, lower, digit, symbol."""
        lower = string.ascii_lowercase
        upper = string.ascii_uppercase
        digits = string.digits
        symbols = '!@#$%^&*'

        pwd = [
            secrets.choice(lower),
            secrets.choice(upper),
            secrets.choice(digits),
            secrets.choice(symbols),
        ]
        all_chars = lower + upper + digits + symbols
        pwd += [secrets.choice(all_chars) for _ in range(6)]
        secrets.SystemRandom().shuffle(pwd)
        return ''.join(pwd)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def check_password(self, raw_password):
        return check_password(raw_password, self.one_time_password_hash)

    @property
    def is_offline(self):
        """True if this is an offline (on-site) voter credential."""
        return self.voter_email.endswith(OFFLINE_VOTER_DOMAIN)

    def can_vote(self):
        return not self.has_voted and not self.is_revoked and self.election.can_vote

    @property
    def display_name(self):
        return self.voter_name or self.voter_email

    @property
    def voting_status(self):
        """
        Return the voter's display status.

        Email voters:     Revoked | Voted | Invited | Invitation Failed | Pending
        In-person voters: Revoked | Voted | Registered

        'Registered' is ONLY for in-person voters whose PDF credentials have
        been generated.  Email voters that have not yet received an invitation
        show 'Pending' instead — they exist in the DB but no email has landed.
        """
        if self.is_revoked:
            return 'Revoked'
        if self.has_voted:
            return 'Voted'
        if self.is_offline:
            # In-person voter: credential generated = Registered
            return 'Registered'
        # Email voter path (no "Registered" state)
        if self.invitation_sent:
            return 'Invited'
        if self.invitation_error:
            return 'Invitation Failed'
        return 'Pending'


# ------------------------------------------------------------------
# Vote (ANONYMIZED — no FK to VoterCredential)
# ------------------------------------------------------------------

class Vote(models.Model):
    """
    Anonymized vote record.

    Double-vote prevention is enforced by:
      1. ``VoterCredential.has_voted`` flag (DB level)
      2. ``select_for_update()`` in atomic transaction (race-condition)
      3. ``unique_together`` on ``(election, post, voter_hash)``
      4. Blockchain nullifier (on-chain, Phase 3)
    """

    election = models.ForeignKey(
        'elections.Election',
        on_delete=models.CASCADE,
        related_name='votes',
    )
    post = models.ForeignKey(
        'elections.Post',
        on_delete=models.CASCADE,
        related_name='votes',
    )
    candidate = models.ForeignKey(
        'candidates.Candidate',
        on_delete=models.CASCADE,
        related_name='votes',
    )
    timestamp = models.DateTimeField(default=timezone.now)

    # Irreversible hash — links voter to votes for uniqueness only
    voter_hash = models.CharField(
        max_length=64,
        help_text="SHA-256(credential_id:election_id:salt) — cannot be reversed",
    )

    # Blockchain reference (Solana)
    blockchain_tx_hash = models.CharField(max_length=100, blank=True, default='')  # Solana signature (88 chars)
    blockchain_slot = models.PositiveBigIntegerField(null=True, blank=True)
    blockchain_confirmed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['election', 'post', 'voter_hash'], name='unique_vote_per_post'),
        ]
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['election', 'post', 'candidate']),
            models.Index(fields=['voter_hash']),
        ]

    def __str__(self):
        # LOW-16: Use IDs to avoid N+1 FK lookups in admin/logging
        return f"Vote #{self.pk} (post={self.post_id}, candidate={self.candidate_id})"


# ------------------------------------------------------------------
# VoterAccessRequest (voter self-service enrollment)
# ------------------------------------------------------------------

class VoterAccessRequest(models.Model):
    """A request from a prospective voter to join an election.

    Created when someone visits the election's access-request page and
    submits their name + email.  The election admin can then approve
    or reject from the dashboard Voters tab.
    """

    class Status(models.TextChoices):
        PENDING  = 'pending',  'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    election = models.ForeignKey(
        'elections.Election',
        on_delete=models.CASCADE,
        related_name='access_requests',
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    message = models.TextField(
        blank=True, default='',
        help_text='Optional message from the requester.',
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['election', 'email'],
                name='unique_access_request_per_election',
            ),
        ]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['election', 'status']),
        ]

    def __str__(self):
        return f"{self.email} → {self.election.name} ({self.status})"
