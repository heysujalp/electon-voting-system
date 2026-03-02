"""
ElectON v2 — Accounts models.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.accounts.constants import SECURITY_QUESTIONS


class CustomUser(AbstractUser):
    """Extended user model for election administrators."""
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)  # Active only after email verification
    email_verified = models.BooleanField(default=False)

    # Change-cooldown tracking (email & username locked for 6 months after update)
    email_last_changed = models.DateTimeField(null=True, blank=True)
    username_last_changed = models.DateTimeField(null=True, blank=True)
    password_last_changed = models.DateTimeField(null=True, blank=True)

    # Pending email change (requires verification before applying)
    pending_email = models.EmailField(null=True, blank=True)
    pending_email_code_hash = models.CharField(max_length=128, null=True, blank=True)
    pending_email_code_expires = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'full_name']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.username} ({self.email})"

    # ─── Cooldown helpers (6-month lock after email/username change) ───
    CHANGE_COOLDOWN_DAYS = 183  # ~6 months

    def can_change_email(self) -> bool:
        if not self.email_last_changed:
            return True
        return (timezone.now() - self.email_last_changed).total_seconds() >= self.CHANGE_COOLDOWN_DAYS * 86400

    def can_change_username(self) -> bool:
        if not self.username_last_changed:
            return True
        return (timezone.now() - self.username_last_changed).total_seconds() >= self.CHANGE_COOLDOWN_DAYS * 86400

    def next_email_change_date(self):
        if not self.email_last_changed:
            return None
        from datetime import timedelta
        return self.email_last_changed + timedelta(days=self.CHANGE_COOLDOWN_DAYS)

    def next_username_change_date(self):
        if not self.username_last_changed:
            return None
        from datetime import timedelta
        return self.username_last_changed + timedelta(days=self.CHANGE_COOLDOWN_DAYS)


class EmailVerificationSession(models.Model):
    """
    Stores pending registration data during email verification.
    User account is only created after successful verification.
    """
    email = models.EmailField(db_index=True)
    session_id = models.CharField(max_length=100, unique=True, db_index=True)

    # Verification (stored as hashes — never plaintext)
    verification_code_hash = models.CharField(max_length=128)
    verification_token_hash = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    code_expires_at = models.DateTimeField()

    # Resend tracking
    resend_attempts = models.IntegerField(default=0)
    next_resend_available_at = models.DateTimeField(null=True, blank=True)

    # Pending registration data (saved here until verification succeeds)
    pending_username = models.CharField(max_length=150, null=True, blank=True)
    pending_full_name = models.CharField(max_length=255, null=True, blank=True)
    pending_password_hash = models.CharField(max_length=128, null=True, blank=True)

    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'code_expires_at']),
        ]

    def __str__(self):
        return f"Verification for {self.email}"

    def is_code_expired(self) -> bool:
        return timezone.now() >= self.code_expires_at

    def can_resend(self) -> bool:
        if not self.next_resend_available_at:
            return True
        return timezone.now() >= self.next_resend_available_at


class PasswordResetSession(models.Model):
    """
    Stores pending password reset data during the multi-step flow.
    Created at Step 1 (email), used through Step 4 (new password).
    """
    email = models.EmailField(db_index=True)
    session_id = models.CharField(max_length=100, unique=True, db_index=True)

    # Verification code (stored as hash — never plaintext)
    verification_code_hash = models.CharField(max_length=128, null=True, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)

    # Resend tracking
    resend_attempts = models.IntegerField(default=0)
    next_resend_available_at = models.DateTimeField(null=True, blank=True)

    # Flow flags
    security_questions_verified = models.BooleanField(default=False)
    code_verified = models.BooleanField(default=False)

    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'created_at']),
        ]

    def __str__(self):
        return f"Password reset for {self.email}"

    def is_code_expired(self) -> bool:
        if not self.code_expires_at:
            return True
        return timezone.now() >= self.code_expires_at

    def can_resend(self) -> bool:
        if not self.next_resend_available_at:
            return True
        return timezone.now() >= self.next_resend_available_at


class AdminLoginVerification(models.Model):
    """
    2FA verification triggered after repeated failed admin login attempts.
    Sends a code via email that must be entered to proceed.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_login_verifications',
    )
    verification_code_hash = models.CharField(max_length=128)
    code_expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Login verification for {self.user.username}"

    def is_expired(self) -> bool:
        return timezone.now() >= self.code_expires_at

    def has_attempts_remaining(self) -> bool:
        return self.attempts < self.max_attempts


class SecurityQuestion(models.Model):
    """
    Stores a user's security question and hashed answer.
    Each user must have exactly SECURITY_QUESTIONS_REQUIRED (3) of these.
    Used for: forgot-password verification, account deletion confirmation.
    """
    QUESTION_CHOICES = SECURITY_QUESTIONS

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_questions',
    )
    question_key = models.CharField(
        max_length=30,
        help_text='Key identifying the chosen security question.',
    )
    answer_hash = models.CharField(
        max_length=128,
        help_text='SHA-256 hash of the normalised answer.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        unique_together = [('user', 'question_key')]

    def __str__(self):
        return f"SecurityQ({self.question_key}) for {self.user.username}"

    @property
    def question_text(self) -> str:
        """Return the human-readable question text."""
        for key, text in self.QUESTION_CHOICES:
            if key == self.question_key:
                return text
        return self.question_key

    def verify_answer(self, plaintext_answer: str) -> bool:
        """Verify a plaintext answer against the stored hash.

        Supports legacy SHA-256, legacy PBKDF2 (global salt), and new
        per-salt PBKDF2 hashes.  Transparently upgrades old formats.
        """
        from apps.accounts.services.token_service import TokenService
        normalised = plaintext_answer.strip().lower()

        matched = TokenService.verify_answer(normalised, self.answer_hash)

        if matched:
            # Transparently upgrade old formats to new per-salt PBKDF2
            parts = self.answer_hash.split('$', 2) if self.answer_hash.startswith('pbkdf2$') else []
            is_new_format = len(parts) == 3
            if not is_new_format:
                self.answer_hash = TokenService._hash_answer(normalised)
                self.save(update_fields=['answer_hash'])

        return matched

    @staticmethod
    def hash_answer(plaintext_answer: str) -> str:
        """Hash an answer for storage using PBKDF2."""
        from apps.accounts.services.token_service import TokenService
        return TokenService._hash_answer(plaintext_answer.strip().lower())
