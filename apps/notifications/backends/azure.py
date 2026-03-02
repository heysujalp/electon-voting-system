"""
ElectON v2 — Azure Communication Services Email Backend.

Implements Django's BaseEmailBackend using the Azure Communication
Services Email SDK.

Requirements (install when activating Azure):
    azure-communication-email>=1.0,<2.0

Usage:
    AZURE_COMM_CONNECTION_STRING = 'endpoint=https://...;accesskey=...'
    AZURE_COMM_SENDER_ADDRESS   = 'DoNotReply@<your-domain>.azurecomm.net'

The backend is import-guarded: if the SDK is not installed, an
``ImproperlyConfigured`` error is raised only when this backend is
actually invoked, not at import time, so the app starts normally when
Azure is not the active provider.
"""
import logging
import smtplib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

# Sentinel — resolved lazily so missing SDK doesn't crash at startup
_azure_client_cls = None


def _get_azure_client_cls():
    """Lazy import azure.communication.email.EmailClient with clear error."""
    global _azure_client_cls
    if _azure_client_cls is not None:
        return _azure_client_cls
    try:
        from azure.communication.email import EmailClient  # type: ignore[import-untyped]  # noqa: PLC0415
        _azure_client_cls = EmailClient
        return _azure_client_cls
    except ImportError:
        raise ImproperlyConfigured(
            "Azure Communication Services Email SDK is not installed. "
            "Run: pip install azure-communication-email>=1.0,<2.0"
        )


class AzureEmailBackend(BaseEmailBackend):
    """
    Send emails via Azure Communication Services Email SDK.

    Exception translation (mirrors BrevoEmailBackend for consistent
    classification in EmailService):
      - HttpResponseError 4xx invalid address → ``ValueError``
      - HttpResponseError 4xx other           → ``smtplib.SMTPRecipientsRefused``
      - HttpResponseError 429                 → smtplib.SMTPException('rate_limit')
      - HttpResponseError 5xx                → ``smtplib.SMTPException``
      - Azure SDK not installed               → ``ImproperlyConfigured``
      - network / timeout                     → ``ConnectionError`` / ``TimeoutError``
    """

    def __init__(self, connection_string: str = '', fail_silently: bool = False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.connection_string = (
            connection_string
            or getattr(settings, 'AZURE_COMM_CONNECTION_STRING', '')
            or ''
        )
        self.sender_address = (
            getattr(settings, 'AZURE_COMM_SENDER_ADDRESS', '')
            or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@electon.app')
        )

    # ------------------------------------------------------------------
    # BaseEmailBackend interface
    # ------------------------------------------------------------------

    def open(self):
        return True

    def close(self):
        pass

    def send_messages(self, email_messages):
        """Send a list of EmailMessage objects via Azure ACS Email SDK."""
        if not email_messages:
            return 0

        if not self.connection_string:
            err = ImproperlyConfigured(
                'AZURE_COMM_CONNECTION_STRING is not set. '
                'Provide the Azure Communication Services connection string.'
            )
            if self.fail_silently:
                logger.error("AzureBackend: %s", err)
                return 0
            raise err

        EmailClient = _get_azure_client_cls()

        try:
            client = EmailClient.from_connection_string(self.connection_string)
        except Exception as exc:
            err = ConnectionError(f"AzureBackend: failed to create client — {exc}")
            if self.fail_silently:
                logger.error("%s", err)
                return 0
            raise err

        num_sent = 0
        for message in email_messages:
            try:
                self._send_one(client, message)
                num_sent += 1
            except Exception as exc:
                logger.exception("AzureBackend: failed to send to %s — %s", message.to, exc)
                if not self.fail_silently:
                    raise

        return num_sent

    # ------------------------------------------------------------------
    # Internal send
    # ------------------------------------------------------------------

    def _send_one(self, client, message):
        """Send a single message. Raises on failure."""
        # Resolve sender address
        from_address = message.from_email or self.sender_address
        if '<' in from_address:
            from_address = from_address.split('<')[1].rstrip('>').strip()

        # Build recipient list
        to_recipients = []
        for addr in message.to:
            addr = addr.strip()
            if '<' in addr:
                email = addr.split('<')[1].rstrip('>').strip()
            else:
                email = addr
            to_recipients.append({'address': email})

        # Build content
        html_content = None
        text_content = message.body or ''
        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                html_content = content
                break

        email_msg = {
            'senderAddress': from_address,
            'recipients': {'to': to_recipients},
            'content': {
                'subject': message.subject,
                'plainText': text_content,
            },
        }
        if html_content:
            email_msg['content']['html'] = html_content

        try:
            poller = client.begin_send(email_msg)
            # Wait for the operation to complete (with a generous timeout)
            result = poller.result(timeout=30)
            logger.info(
                "AzureBackend: message sent successfully, status=%s",
                getattr(result, 'status', 'unknown'),
            )
        except Exception as exc:
            self._translate_azure_exception(exc)

    @staticmethod
    def _translate_azure_exception(exc):
        """Translate Azure SDK exceptions to standard Python exceptions."""
        exc_name = type(exc).__name__
        exc_str = str(exc).lower()

        # Try to detect azure.core.exceptions.HttpResponseError
        status_code = getattr(exc, 'status_code', None)

        if status_code is not None:
            if status_code == 400:
                if 'invalid' in exc_str or 'address' in exc_str:
                    raise ValueError(f"Azure rejected email address: {exc}")
                raise smtplib.SMTPRecipientsRefused({exc: (status_code, str(exc))})  # type: ignore[arg-type]
            if status_code == 429:
                raise smtplib.SMTPException(f"rate_limit: Azure sending limit reached: {exc}")
            if status_code >= 500:
                raise smtplib.SMTPException(f"Azure server error ({status_code}): {exc}")
            raise smtplib.SMTPException(f"Azure API error ({status_code}): {exc}")

        # Network-level errors from the Azure SDK
        if 'timeout' in exc_str or 'timed out' in exc_str:
            raise TimeoutError(f"Azure request timed out: {exc}")
        if 'connection' in exc_str or exc_name in ('ConnectionError', 'ServiceRequestError'):
            raise ConnectionError(f"Azure connection failed: {exc}")

        # Anything else
        raise smtplib.SMTPException(f"Azure error ({exc_name}): {exc}")
