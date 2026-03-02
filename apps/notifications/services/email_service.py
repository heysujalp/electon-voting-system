"""
ElectON v2 — Unified email service.

Every email is routed through ``ElectONRoutingBackend`` (Brevo → Azure
with automatic daily-limit overflow) and logged to ``EmailLog``.

Key improvements:
  - Pre-validates email address format before attempting delivery.
  - Maps SMTP / Brevo / Azure exceptions to structured error codes
    stored on ``VoterCredential.invitation_error_code``.
  - ``send_voter_invitation()`` returns a rich result dict instead of
    a bare bool, giving callers precise failure information.
  - ``send_bulk_voter_invitations()`` collects per-failure details so
    the frontend popup can list exactly which addresses failed and why.
"""
import logging
import re
import smtplib
from datetime import date

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from apps.notifications.models import EmailLog

logger = logging.getLogger(__name__)

# Simple format check — catches obvious garbage like "@@bad", "no-at-sign"
_EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ──────────────────────────────────────────────────────────────────────────────
# Error-code constants  (mirror VoterCredential.InvitationErrorCode)
# ──────────────────────────────────────────────────────────────────────────────

class InvitationErrorCode:
    INVALID_FORMAT  = 'INVALID_FORMAT'
    SMTP_REJECTED   = 'SMTP_REJECTED'
    SMTP_ERROR      = 'SMTP_ERROR'
    RATE_LIMITED    = 'RATE_LIMITED'
    PROVIDER_ERROR  = 'PROVIDER_ERROR'
    UNKNOWN         = 'UNKNOWN'


# Human-readable labels shown in the failure popup
ERROR_CODE_LABELS = {
    InvitationErrorCode.INVALID_FORMAT:  'Invalid email address format',
    InvitationErrorCode.SMTP_REJECTED:   'Email address rejected by mail server',
    InvitationErrorCode.SMTP_ERROR:      'Mail server / connection failure',
    InvitationErrorCode.RATE_LIMITED:    'Daily sending limit reached',
    InvitationErrorCode.PROVIDER_ERROR:  'Email provider error',
    InvitationErrorCode.UNKNOWN:         'Unknown delivery failure',
}


def _classify_exception(exc: Exception) -> tuple[str, str]:
    """
    Map a caught exception to ``(error_code, human_message)``.

    Works for Django SMTP backend, BrevoEmailBackend, and AzureEmailBackend
    because those backends translate their errors to standard Python exceptions.
    """
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__

    if isinstance(exc, ValueError):
        return InvitationErrorCode.INVALID_FORMAT, str(exc)

    if 'rate_limit' in exc_str or 'rate limit' in exc_str or 'daily limit' in exc_str:
        return InvitationErrorCode.RATE_LIMITED, ERROR_CODE_LABELS[InvitationErrorCode.RATE_LIMITED]

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return InvitationErrorCode.SMTP_ERROR, f"Connection/timeout error: {exc}"

    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return InvitationErrorCode.SMTP_REJECTED, "Email address rejected by the SMTP server"

    if isinstance(exc, (
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
        smtplib.SMTPHeloError,
        smtplib.SMTPAuthenticationError,
    )):
        return InvitationErrorCode.SMTP_ERROR, f"SMTP connection error: {exc_type}"

    if isinstance(exc, smtplib.SMTPException):
        msg = str(exc)
        if 'rate_limit' in msg.lower():
            return InvitationErrorCode.RATE_LIMITED, ERROR_CODE_LABELS[InvitationErrorCode.RATE_LIMITED]
        return InvitationErrorCode.SMTP_ERROR, f"SMTP error: {msg[:200]}"

    if any(kw in exc_str for kw in ('invalid email', 'invalid address', 'invalid_parameter')):
        return InvitationErrorCode.SMTP_REJECTED, "Email address rejected by provider"

    if exc_type == 'ImproperlyConfigured' or 'configured' in exc_str:
        return InvitationErrorCode.PROVIDER_ERROR, f"Email not configured properly: {str(exc)[:200]}"

    return InvitationErrorCode.UNKNOWN, f"Unexpected error ({exc_type}): {str(exc)[:200]}"


def _expected_provider() -> str:
    """
    Return which provider is expected to handle the next email.
    Used to populate EmailLog.provider (best-effort audit record).
    """
    from django.core.cache import cache as django_cache

    brevo_key = (getattr(settings, 'BREVO_API_KEY', '') or '').strip()
    azure_conn = (getattr(settings, 'AZURE_COMM_CONNECTION_STRING', '') or '').strip()

    if not brevo_key and not azure_conn:
        return 'smtp'
    if not brevo_key:
        return 'azure'

    count = django_cache.get(f'brevo:daily:{date.today().isoformat()}', 0)
    limit = int(getattr(settings, 'BREVO_DAILY_LIMIT', 300))
    return 'brevo' if count < limit else 'azure'


class EmailService:
    """
    Unified email service.

    Every ``send_email`` call:
      1. Creates an ``EmailLog`` entry.
      2. Sends via the routing backend (Brevo → Azure → SMTP fallback).
      3. Updates the log with final status / error.

    ``send_voter_invitation`` additionally:
      - Pre-validates the recipient email format.
      - Classifies failures and persists the structured error code on
        ``VoterCredential.invitation_error_code``.
    """

    # ------------------------------------------------------------------
    # Core send
    # ------------------------------------------------------------------

    @staticmethod
    def send_email(
        recipient: str,
        subject: str,
        template: str,
        context: dict,
        election=None,
    ) -> bool:
        """
        Render *template* (under ``templates/emails/``), send HTML email,
        and log the result.

        Returns ``True`` on success, ``False`` on failure.
        """
        provider = _expected_provider()

        log = EmailLog.objects.create(
            recipient_email=recipient,
            subject=subject,
            template_name=template,
            election=election,
            provider=provider,
        )

        try:
            html = render_to_string(f'emails/{template}', context)
            text = strip_tags(html)

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
            )
            msg.attach_alternative(html, 'text/html')
            msg.send()

            log.status = EmailLog.Status.SENT
            log.sent_at = timezone.now()
            log.save(update_fields=['status', 'sent_at'])
            logger.info("Email sent (%s): %s → %s", provider, subject, recipient)
            return True

        except Exception as exc:
            log.status = EmailLog.Status.FAILED
            log.error_message = str(exc)
            log.save(update_fields=['status', 'error_message'])
            logger.exception("Email failed (%s): %s → %s", provider, subject, recipient)
            return False



    # ------------------------------------------------------------------
    # Voter invitation (rich result)
    # ------------------------------------------------------------------

    @classmethod
    def send_voter_invitation(cls, credential, election, plain_password: str) -> dict:
        """
        Send one-time credentials to a voter.

        Returns::

            {
                'success':       bool,
                'error_code':    str | None,   # InvitationErrorCode constant
                'error_message': str,
            }

        Always persists ``invitation_sent``, ``invitation_error``,
        ``invitation_error_code``, and ``invited_at`` on the credential.

        NOTE: Signature changed from ``-> bool`` to ``-> dict``.
        Callers that previously checked ``if send_voter_invitation(...):``
        should now check ``if send_voter_invitation(...)['success']:``.
        ``send_bulk_voter_invitations`` already uses the dict result.
        """
        site_url = getattr(settings, 'SITE_URL', '')

        # ── Step 1: Pre-validate email format ────────────────────────────
        email = credential.voter_email
        if not _EMAIL_REGEX.match(email):
            error_msg = f"Invalid email address format: '{email}'"
            logger.warning("send_voter_invitation: %s", error_msg)
            credential.invitation_sent = False
            credential.invitation_error = error_msg
            credential.invitation_error_code = credential.InvitationErrorCode.INVALID_FORMAT
            credential.save(update_fields=[
                'invitation_sent', 'invitation_error',
                'invitation_error_code', 'updated_at',
            ])
            return {
                'success':       False,
                'error_code':    InvitationErrorCode.INVALID_FORMAT,
                'error_message': error_msg,
            }

        # ── Step 2: Send via routing backend ─────────────────────────────
        provider = _expected_provider()
        log = EmailLog.objects.create(
            recipient_email=email,
            subject=f'Invitation to Vote: {election.name}',
            template_name='voter_invitation.html',
            election=election,
            provider=provider,
        )

        try:
            html = render_to_string('emails/voter_invitation.html', {
                'voter_name': credential.voter_name,
                'election': election,
                'election_name': election.name,
                'username': credential.one_time_username,
                'password': plain_password,
                'voting_url': f"{site_url}/voting/login/",
                'site_name': 'ElectON',
            })
            text = strip_tags(html)

            msg = EmailMultiAlternatives(
                subject=f'Invitation to Vote: {election.name}',
                body=text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            msg.attach_alternative(html, 'text/html')
            msg.send()

            # ── Success ──────────────────────────────────────────────────
            log.status = EmailLog.Status.SENT
            log.sent_at = timezone.now()
            log.save(update_fields=['status', 'sent_at'])

            credential.invitation_sent = True
            credential.invited_at = timezone.now()
            credential.invitation_error = ''
            credential.invitation_error_code = ''
            credential.save(update_fields=[
                'invitation_sent', 'invited_at',
                'invitation_error', 'invitation_error_code', 'updated_at',
            ])
            logger.info(
                "send_voter_invitation: sent to %s via %s (election=%s)",
                email, provider, election.election_uuid,
            )
            return {'success': True, 'error_code': None, 'error_message': ''}

        except Exception as exc:
            error_code, error_msg = _classify_exception(exc)

            log.status = EmailLog.Status.FAILED
            log.error_message = error_msg
            log.save(update_fields=['status', 'error_message'])

            credential.invitation_sent = False
            credential.invitation_error = error_msg
            credential.invitation_error_code = error_code
            credential.save(update_fields=[
                'invitation_sent', 'invitation_error',
                'invitation_error_code', 'updated_at',
            ])
            logger.error(
                "send_voter_invitation: FAILED for %s [%s] — %s",
                email, error_code, error_msg,
            )
            return {
                'success':       False,
                'error_code':    error_code,
                'error_message': error_msg,
            }

    @classmethod
    def send_bulk_voter_invitations(
        cls,
        credentials_with_passwords,
        election,
    ) -> dict:
        """
        Send invitations to a list of ``(credential, plain_password)`` pairs.

        Returns::

            {
                'sent':   int,
                'failed': int,
                'errors': [
                    {
                        'voter_email':   str,
                        'voter_name':    str,
                        'error_code':    str,
                        'error_message': str,
                    },
                    ...
                ],
            }
        """
        sent = 0
        failed_details = []

        for credential, pwd in credentials_with_passwords:
            try:
                result = cls.send_voter_invitation(credential, election, pwd)
                if result['success']:
                    sent += 1
                else:
                    failed_details.append({
                        'voter_email':   credential.voter_email,
                        'voter_name':    credential.voter_name or '',
                        'error_code':    result['error_code'],
                        'error_message': result['error_message'],
                    })
            except Exception as exc:
                error_code, error_msg = _classify_exception(exc)
                failed_details.append({
                    'voter_email':   credential.voter_email,
                    'voter_name':    credential.voter_name or '',
                    'error_code':    error_code,
                    'error_message': error_msg,
                })

        return {
            'sent':   sent,
            'failed': len(failed_details),
            'errors': failed_details,
        }

