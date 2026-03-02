"""
ElectON v2 — Brevo Transactional Email Backend.

Implements Django's BaseEmailBackend interface using Brevo's
SMTP API v3 (REST). Does NOT require the brevo-python SDK —
uses only ``requests``, which is already in requirements.txt.

Usage:
    EMAIL_BACKEND = 'apps.notifications.backends.brevo.BrevoEmailBackend'
    BREVO_API_KEY = 'xkeysib-...'
    BREVO_SENDER_NAME = 'ElectON'
    DEFAULT_FROM_EMAIL = 'noreply@electon.app'
"""
import logging
import smtplib

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

# Brevo Transactional SMTP API endpoint
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


class BrevoEmailBackend(BaseEmailBackend):
    """
    Send emails via Brevo's Transactional Email API (v3).

    Raises standard Python / smtplib exceptions so that
    ``EmailService.send_email()`` can classify failures using
    the same exception map as SMTP and Azure backends.

    Exception translation:
      - 400 invalid address / bad payload → ``ValueError``
      - 401 bad API key                   → ``smtplib.SMTPException``
      - 402 credits/payment issue         → smtplib.SMTPException('rate_limit')
      - 429 too many requests             → smtplib.SMTPException('rate_limit')
      - network failure                   → ``ConnectionError``
      - requests.Timeout                  → ``TimeoutError``
      - other non-2xx                     → ``smtplib.SMTPException``
    """

    def __init__(self, api_key: str = '', fail_silently: bool = False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, 'BREVO_API_KEY', '') or ''
        self.sender_name = getattr(settings, 'BREVO_SENDER_NAME', 'ElectON')

    # ------------------------------------------------------------------
    # BaseEmailBackend interface
    # ------------------------------------------------------------------

    def open(self):
        """No persistent connection needed for REST API."""
        return True

    def close(self):
        """No connection to close."""
        pass

    def send_messages(self, email_messages):
        """Send a list of EmailMessage objects via Brevo API.

        Returns the number of successfully accepted messages.
        Raises exceptions (when fail_silently=False) so callers can classify.
        """
        if not email_messages:
            return 0

        if not self.api_key:
            err = smtplib.SMTPException('Brevo API key is not configured (BREVO_API_KEY).')
            if self.fail_silently:
                logger.error("BrevoBackend: %s", err)
                return 0
            raise err

        num_sent = 0
        headers = {
            'api-key': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        for message in email_messages:
            try:
                self._send_one(message, headers)
                num_sent += 1
            except Exception as exc:
                logger.exception("BrevoBackend: failed to send to %s — %s", message.to, exc)
                if not self.fail_silently:
                    raise

        return num_sent

    # ------------------------------------------------------------------
    # Internal send
    # ------------------------------------------------------------------

    def _send_one(self, message, headers: dict):
        """Send a single EmailMessage. Raises on failure."""
        from_email = message.from_email or settings.DEFAULT_FROM_EMAIL

        # Parse "Name <email>" format
        if '<' in from_email:
            sender_name = from_email.split('<')[0].strip().strip('"')
            sender_email = from_email.split('<')[1].rstrip('>').strip()
        else:
            sender_name = self.sender_name
            sender_email = from_email

        # Build recipient list
        to_list = [self._parse_address(addr) for addr in message.to]

        # Build payload — prefer HTML if present, fall back to text body
        html_content = None
        text_content = message.body or ''

        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                html_content = content
                break

        payload = {
            'sender': {'name': sender_name, 'email': sender_email},
            'to': to_list,
            'subject': message.subject,
            'textContent': text_content,
        }
        if html_content:
            payload['htmlContent'] = html_content

        # Attachments (not used by voter invitations, but kept for completeness)
        if message.attachments:
            import base64
            payload['attachment'] = []
            for attachment in message.attachments:
                name, content, mime = attachment
                if isinstance(content, str):
                    content = content.encode('utf-8')
                payload['attachment'].append({
                    'name': name,
                    'content': base64.b64encode(content).decode(),
                })

        try:
            response = requests.post(
                BREVO_API_URL,
                json=payload,
                headers=headers,
                timeout=15,
            )
        except requests.Timeout:
            raise TimeoutError(f"Brevo API request timed out for {message.to}")
        except requests.ConnectionError as exc:
            raise ConnectionError(f"Brevo API connection failed: {exc}")

        self._check_response(response, message.to)

    def _check_response(self, response, recipients):
        """Translate non-2xx Brevo responses to standard exceptions."""
        if response.status_code in (200, 201):
            return  # Success

        try:
            body = response.json()
            code = body.get('code', '')
            msg = body.get('message', response.text)
        except Exception:
            code = ''
            msg = response.text

        status = response.status_code

        if status == 400:
            # Brevo returns 400 for invalid email addresses / bad parameters
            raise ValueError(f"Brevo rejected message (invalid data): {code} — {msg}")

        if status == 401:
            raise smtplib.SMTPException(f"Brevo API key invalid or unauthorized: {msg}")

        if status in (402, 429):
            # 402 = account credits exhausted; 429 = rate limited
            raise smtplib.SMTPException(f"rate_limit: Brevo sending limit reached: {msg}")

        if status >= 500:
            raise smtplib.SMTPException(f"Brevo server error ({status}): {msg}")

        raise smtplib.SMTPException(f"Brevo API error ({status}): {code} — {msg}")

    @staticmethod
    def _parse_address(addr: str) -> dict:
        """Convert 'Name <email>' or plain 'email' to Brevo address dict."""
        addr = addr.strip()
        if '<' in addr:
            name = addr.split('<')[0].strip().strip('"')
            email = addr.split('<')[1].rstrip('>').strip()
            return {'name': name, 'email': email}
        return {'email': addr}
