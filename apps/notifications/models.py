"""
ElectON v2 — Notifications models.

NEW: ``EmailLog`` tracks every email sent through the system for
auditing and retry purposes.
"""
from django.core.exceptions import ValidationError
from django.db import models


class EmailLog(models.Model):
    """Tracks every email sent by the system."""

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    class Provider(models.TextChoices):
        BREVO   = 'brevo',   'Brevo'
        AZURE   = 'azure',   'Azure Communication Services'
        SMTP    = 'smtp',    'SMTP'
        CONSOLE = 'console', 'Console (dev)'

    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255)
    template_name = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    error_message = models.TextField(blank=True, default='')
    # Which email provider delivered (or attempted) this message
    provider = models.CharField(
        max_length=10,
        choices=Provider.choices,
        blank=True,
        default='',
        help_text='Email provider used to send this message.',
    )

    # Optional election link
    election = models.ForeignKey(
        'elections.Election',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='email_logs',
    )

    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['recipient_email']),
            models.Index(fields=['election', 'status']),
        ]

    def __str__(self):
        return f"{self.subject} → {self.recipient_email} ({self.status})"


class Webhook(models.Model):
    """FEAT-06: Webhook endpoint for election event notifications."""

    class EventType(models.TextChoices):
        ELECTION_LAUNCHED = 'election.launched', 'Election Launched'
        ELECTION_ENDED = 'election.ended', 'Election Ended'
        VOTE_CAST = 'vote.cast', 'Vote Cast'
        VOTE_THRESHOLD = 'vote.threshold', 'Vote Threshold Reached'

    election = models.ForeignKey(
        'elections.Election',
        on_delete=models.CASCADE,
        related_name='webhooks',
    )
    url = models.URLField(max_length=500, help_text='HTTPS endpoint to receive event payloads')
    secret = models.CharField(
        max_length=128, blank=True, default='',
        help_text='Shared secret for HMAC-SHA256 signature verification (strongly recommended)',
    )
    events = models.JSONField(
        default=list,
        help_text='List of event types to subscribe to',
    )
    is_active = models.BooleanField(default=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    last_status_code = models.IntegerField(null=True, blank=True)
    failure_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['election', 'is_active']),
        ]

    def clean(self):
        super().clean()
        # Enforce HTTPS
        if self.url and not self.url.startswith('https://'):
            raise ValidationError({'url': 'Webhook URL must use HTTPS.'})
        # Validate events list
        valid_events = {e.value for e in self.EventType}
        if not isinstance(self.events, list) or not self.events:
            raise ValidationError({'events': 'At least one event type is required.'})
        invalid = set(self.events) - valid_events
        if invalid:
            raise ValidationError({'events': f'Invalid event types: {", ".join(sorted(invalid))}'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Webhook {self.pk} → {self.url} ({', '.join(self.events)})"
