"""
ElectON v2 — Audit models.
Immutable audit trail for all security-sensitive actions.
"""
from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Immutable audit trail entry."""

    class Action(models.TextChoices):
        # Authentication
        LOGIN_SUCCESS = 'login_success', 'Login Success'
        LOGIN_FAILURE = 'login_failure', 'Login Failure'
        LOGOUT = 'logout', 'Logout'
        REGISTER = 'register', 'Register'
        PASSWORD_RESET = 'password_reset', 'Password Reset'
        PASSWORD_CHANGE = 'password_change', 'Password Change'

        # Elections
        ELECTION_CREATE = 'election_create', 'Election Created'
        ELECTION_LAUNCH = 'election_launch', 'Election Launched'
        ELECTION_END = 'election_end', 'Election Ended'
        ELECTION_DELETE = 'election_delete', 'Election Deleted'
        ELECTION_UPDATE = 'election_update', 'Election Updated'

        # Voting
        VOTE_CAST = 'vote_cast', 'Vote Cast'
        VOTER_REGISTERED = 'voter_registered', 'Voter Registered'
        VOTER_REVOKED = 'voter_revoked', 'Voter Revoked'
        VOTER_IMPORT = 'voter_import', 'Voters Imported'

        # Account
        ACCOUNT_DELETE = 'account_delete', 'Account Deleted'
        ACCOUNT_UPDATE = 'account_update', 'Account Updated'

    action = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    election = models.ForeignKey(
        'elections.Election',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['user', 'action']),
            models.Index(fields=['election', 'action']),
        ]
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'

    def __str__(self):
        user_str = self.user.username if self.user else 'anonymous'
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.action} by {user_str}"

    def save(self, *args, **kwargs):
        """Enforce immutability: only allow INSERT, never UPDATE."""
        if self.pk is not None:
            raise ValueError(
                "AuditLog entries are immutable and cannot be modified after creation."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of audit log entries."""
        raise ValueError(
            "AuditLog entries are immutable and cannot be deleted."
        )
