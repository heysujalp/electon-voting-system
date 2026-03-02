"""
ElectON v2 — Smart Email Routing Backend.

Routes outgoing email between Brevo and Azure based on:

  1. Configuration:
       - If BREVO_API_KEY is NOT set:
           → All mail goes to Azure (AZURE_COMM_CONNECTION_STRING must be set).
       - If BREVO_API_KEY IS set:
           → Mail goes to Brevo until BREVO_DAILY_LIMIT is hit (default 300/day).
           → After the limit, emails overflow to Azure.
       - If neither provider is configured:
           → Falls back to EMAIL_PROVIDER_FALLBACK_BACKEND
             (SMTP in production, console in development).

  2. Daily counter:
       - Stored in Django's cache under 'brevo:daily:{YYYY-MM-DD}' (UTC).
       - Incremented only on successful Brevo sends.
       - Expires automatically at midnight + 1 hour buffer.
       - Thread-safe: uses cache.add() for atomic initialisation.

  3. Per-message routing decision:
       - Decision is made individually for each message so partial batches
         split correctly (e.g. 290/300 used → 10 via Brevo, 90 via Azure
         in a 100-message batch).

Usage (settings.py):
    EMAIL_BACKEND = 'apps.notifications.backends.router.ElectONRoutingBackend'
    EMAIL_PROVIDER_FALLBACK_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    BREVO_API_KEY          = 'xkeysib-...'         # optional
    BREVO_SENDER_NAME      = 'ElectON'              # optional
    BREVO_DAILY_LIMIT      = 300                    # optional (default 300)
    AZURE_COMM_CONNECTION_STRING = 'endpoint=...'  # optional (needed for overflow)
    AZURE_COMM_SENDER_ADDRESS    = 'no-reply@...'  # optional
"""
import logging
import smtplib
from datetime import date, datetime, timezone

from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


def _cache_increment_brevo(cache_key: str, ttl_seconds: int) -> int:
    """
    Atomically increment the Brevo daily send counter.

    Returns the NEW count after incrementing.
    Uses add() for atomic creation to avoid race conditions.
    """
    from django.core.cache import cache

    # Try to add (initialises to 1 if key doesn't exist)
    added = cache.add(cache_key, 1, timeout=ttl_seconds)
    if added:
        return 1  # We just created it with value 1

    # Key already exists — increment it
    try:
        new_val = cache.incr(cache_key)
        return new_val
    except ValueError:
        # Key expired between add() and incr() — rare race condition
        cache.set(cache_key, 1, timeout=ttl_seconds)
        return 1


def _brevo_daily_count(cache_key: str) -> int:
    """Return the current Brevo daily send counter (0 if not set)."""
    from django.core.cache import cache
    return cache.get(cache_key, 0)


def _seconds_until_midnight_utc() -> int:
    """Seconds from now until the next UTC midnight + 1 hour buffer."""
    now = datetime.now(tz=timezone.utc)
    tomorrow = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    # Add 1 day to get tomorrow's midnight
    from datetime import timedelta
    tomorrow += timedelta(days=1)
    diff = int((tomorrow - now).total_seconds())
    return diff + 3600  # 1 hr buffer so midnight clock skew doesn't reset early


class ElectONRoutingBackend(BaseEmailBackend):
    """
    Smart routing backend — see module docstring for full routing logic.
    """

    # ------------------------------------------------------------------
    # BaseEmailBackend interface
    # ------------------------------------------------------------------

    def open(self):
        return True

    def close(self):
        pass

    def send_messages(self, email_messages):
        """
        Route each message to the appropriate provider and return the
        total number of messages successfully submitted.
        """
        if not email_messages:
            return 0

        from django.conf import settings

        brevo_key = (getattr(settings, 'BREVO_API_KEY', '') or '').strip()
        azure_conn = (getattr(settings, 'AZURE_COMM_CONNECTION_STRING', '') or '').strip()
        fallback_backend = getattr(
            settings,
            'EMAIL_PROVIDER_FALLBACK_BACKEND',
            'django.core.mail.backends.smtp.EmailBackend',
        )

        # ── No transactional providers configured ──────────────────────
        if not brevo_key and not azure_conn:
            logger.debug(
                "ElectONRoutingBackend: no providers configured, using fallback: %s",
                fallback_backend,
            )
            try:
                conn = get_connection(backend=fallback_backend, fail_silently=self.fail_silently)
                return conn.send_messages(email_messages)
            except Exception as exc:
                if self.fail_silently:
                    logger.error("ElectONRoutingBackend: fallback backend failed — %s", exc)
                    return 0
                raise

        # ── Set up providers ───────────────────────────────────────────
        brevo_limit = int(getattr(settings, 'BREVO_DAILY_LIMIT', 300))
        today_key = f"brevo:daily:{date.today().isoformat()}"
        ttl = _seconds_until_midnight_utc()

        # Lazy-import backends to avoid circular init
        from apps.notifications.backends.brevo import BrevoEmailBackend
        from apps.notifications.backends.azure import AzureEmailBackend

        num_sent = 0

        for message in email_messages:
            provider = self._choose_provider(
                brevo_key, azure_conn, brevo_limit, today_key,
            )
            try:
                if provider == 'brevo':
                    backend = BrevoEmailBackend(api_key=brevo_key, fail_silently=False)
                    sent = backend.send_messages([message])
                    if sent:
                        _cache_increment_brevo(today_key, ttl)
                        num_sent += 1
                    # sent == 0 with no exception should not happen, but treat as failure
                    elif not self.fail_silently:
                        raise smtplib.SMTPException("BrevoBackend returned 0 without exception.")

                elif provider == 'azure':
                    backend = AzureEmailBackend(
                        connection_string=azure_conn, fail_silently=False,
                    )
                    sent = backend.send_messages([message])
                    if sent:
                        num_sent += 1
                    elif not self.fail_silently:
                        raise smtplib.SMTPException("AzureBackend returned 0 without exception.")

                else:
                    # No provider available at all
                    raise smtplib.SMTPException(
                        "ElectONRoutingBackend: no email provider available. "
                        "Configure BREVO_API_KEY or AZURE_COMM_CONNECTION_STRING."
                    )

            except Exception as exc:
                logger.exception(
                    "ElectONRoutingBackend: %s provider failed for %s — %s",
                    provider, message.to, exc,
                )
                if not self.fail_silently:
                    raise

        return num_sent

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    @staticmethod
    def _choose_provider(
        brevo_key: str,
        azure_conn: str,
        brevo_limit: int,
        today_key: str,
    ) -> str:
        """
        Return the provider name to use for the NEXT single message.

        Logic:
          - No brevo_key                       → 'azure'  (or 'none' if no azure)
          - brevo_key + count < limit          → 'brevo'
          - brevo_key + count >= limit         → 'azure'  (or 'none' if no azure)
        """
        if not brevo_key:
            return 'azure' if azure_conn else 'none'

        current_count = _brevo_daily_count(today_key)
        if current_count < brevo_limit:
            return 'brevo'

        # Brevo daily limit reached
        logger.info(
            "ElectONRoutingBackend: Brevo daily limit (%d) reached (%d sent today). "
            "Routing to Azure.",
            brevo_limit,
            current_count,
        )
        return 'azure' if azure_conn else 'none'
