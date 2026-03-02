"""
ElectON v2 — Elections models.
"""
import secrets
import string
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Election(models.Model):
    """Represents a single election created by an admin."""

    # Lifecycle status constants (LOW-08)
    STATUS_PRE_LAUNCH = 'Pre-launch'
    STATUS_INACTIVE = 'Inactive'
    STATUS_ACTIVE = 'Active'
    STATUS_CONCLUDED = 'Concluded'

    election_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    timezone = models.CharField(max_length=255, default='UTC')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='elections',
    )

    # Status flags
    is_launched = models.BooleanField(default=False)
    launch_time = models.DateTimeField(null=True, blank=True)

    # Settings
    allow_voter_results_view = models.BooleanField(
        default=True,
        help_text='Allow voters to see results (always enabled — blockchain transparency).',
    )
    allow_abstain = models.BooleanField(
        default=False,
        help_text='Allow voters to abstain/skip individual posts.',
    )
    admin_message = models.TextField(blank=True, default='')
    access_code = models.CharField(
        max_length=8, blank=True, default='',
        db_index=True,
        help_text='Short access code for voter-friendly election URL.',
    )

    # Blockchain integration (Solana)
    blockchain_contract_address = models.CharField(max_length=50, blank=True, default='')  # Solana pubkey (44 chars)
    blockchain_deploy_tx = models.CharField(max_length=100, blank=True, default='')  # Solana signature (88 chars)
    config_hash = models.CharField(max_length=66, blank=True, default='')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_by', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['access_code'],
                condition=~models.Q(access_code=''),
                name='unique_nonempty_access_code',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.election_uuid})"

    def save(self, *args, **kwargs):
        # FEAT-05: Auto-generate access code if not set
        if not self.access_code:
            self.access_code = self._generate_access_code()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_access_code(cls):
        """Generate a unique 8-character alphanumeric access code."""
        charset = string.ascii_uppercase + string.digits
        for _ in range(100):
            code = ''.join(secrets.choice(charset) for _ in range(8))
            if not cls.objects.filter(access_code=code).exists():
                return code
        raise RuntimeError("Unable to generate unique access code")

    @property
    def current_status(self) -> str:
        """Calculate the current lifecycle status of the election.

        Statuses:
        - Pre-launch (Blue): Not yet launched by the admin.
        - Inactive (Yellow): Launched but start time hasn't arrived yet.
        - Active (Green): Launched and within the voting window.
        - Concluded (Red): Launched and past the end time.
        """
        if not self.is_launched:
            return self.STATUS_PRE_LAUNCH
        now = timezone.now()
        if now < self.start_time:
            return self.STATUS_INACTIVE
        if self.start_time <= now <= self.end_time:
            return self.STATUS_ACTIVE
        return self.STATUS_CONCLUDED

    @property
    def is_active(self) -> bool:
        """Check if election is currently accepting votes."""
        now = timezone.now()
        return (
            self.is_launched
            and self.start_time <= now <= self.end_time
        )

    @property
    def duration_display(self) -> str:
        """Human-readable election duration (e.g., '2 days, 4 hours')."""
        diff = self.end_time - self.start_time
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return '0 minutes'
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        parts = []
        if days:
            parts.append(f'{days} {"day" if days == 1 else "days"}')
        if hours:
            parts.append(f'{hours} {"hour" if hours == 1 else "hours"}')
        if minutes and not days:  # skip minutes if duration is in days
            parts.append(f'{minutes} {"min" if minutes == 1 else "mins"}')
        return ', '.join(parts) or '0 minutes'

    @property
    def has_ended(self) -> bool:
        """Check if the election has concluded (past end time)."""
        return self.is_launched and timezone.now() > self.end_time

    @property
    def is_draft(self) -> bool:
        """Check if the election is in draft (pre-launch) state."""
        return not self.is_launched

    @property
    def can_vote(self) -> bool:
        """Check if voting is currently allowed.

        .. deprecated:: 2.1
            Use :attr:`is_active` directly.
        """
        return self.is_active

    @property
    def can_edit(self) -> bool:
        """Check if election settings can be modified."""
        return self.is_draft

    @property
    def can_delete(self) -> bool:
        """Check if the election can be deleted.

        Only Active elections block deletion. Pre-launch, Inactive,
        and Concluded elections can always be deleted.
        """
        return self.current_status != self.STATUS_ACTIVE

    @property
    def can_launch(self) -> bool:
        """Check if the election meets launch requirements.

        Uses annotated count to avoid N+1 queries on posts/candidates.
        """
        if not self.is_draft:
            return False
        from django.db.models import Count
        posts = self.posts.annotate(candidate_count=Count('candidates'))
        if not posts.exists():
            return False
        for post in posts:
            if post.candidate_count == 0:
                return False
        if not self.voter_credentials.exists():
            return False
        return True


class Post(models.Model):
    """A position/post within an election (e.g., 'President', 'Secretary')."""

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name='posts')
    name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']
        unique_together = ['election', 'name']

    def __str__(self):
        return f"{self.name} — {self.election.name}"

    # ------------------------------------------------------------------
    # Vote helpers
    # ------------------------------------------------------------------

    def get_winner(self):
        """Return the candidate with the most votes for this post, or *None*.

        Ties are broken deterministically by candidate creation order
        (earliest created_at wins). This is intentional — elections
        requiring a different tie-breaking rule should override this.
        """
        from django.db.models import Count

        winner = (
            self.candidates
            .annotate(_vote_count=Count('votes'))
            .order_by('-_vote_count', 'created_at')
            .first()
        )
        if winner is not None and winner._vote_count > 0:
            return winner
        return None
