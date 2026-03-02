"""
ElectON v2 — Webhook dispatch service.

FEAT-06: Sends event payloads to registered webhook endpoints with
HMAC-SHA256 signature verification.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

import requests
from django.db.models import F
from django.utils import timezone

from apps.notifications.models import Webhook

logger = logging.getLogger(__name__)

# Timeout for outbound webhook requests (seconds)
WEBHOOK_TIMEOUT = 10
# Max consecutive failures before auto-disabling
MAX_FAILURES = 10

# Private/internal IP ranges to block for SSRF protection
_BLOCKED_NETWORKS = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]


class WebhookService:
    """Dispatch events to registered webhooks for an election."""

    @classmethod
    def dispatch(cls, election, event_type, payload=None):
        """
        Fire an event to all active webhooks subscribed to ``event_type``.

        Parameters
        ----------
        election : Election
            The election associated with the event.
        event_type : str
            One of Webhook.EventType values (e.g. 'election.launched').
        payload : dict, optional
            Additional data to include in the webhook body.
        """
        webhooks = Webhook.objects.filter(
            election=election,
            is_active=True,
        )

        for webhook in webhooks:
            if event_type not in (webhook.events or []):
                continue
            cls._send(webhook, event_type, election, payload or {})

    @classmethod
    def _is_url_safe(cls, url: str) -> bool:
        """Validate that a webhook URL does not point to internal/private networks."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False
            hostname = parsed.hostname
            if not hostname:
                return False
            # Resolve hostname to IP and check against blocked ranges
            for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, parsed.port or 443):
                ip = ipaddress.ip_address(sockaddr[0])
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        return False
            return True
        except (socket.gaierror, ValueError, OSError):
            return False

    @classmethod
    def _send(cls, webhook, event_type, election, payload):
        """Send a single webhook request with retry logic."""
        # SSRF protection — validate URL before sending (BE-53)
        if not cls._is_url_safe(webhook.url):
            logger.warning(
                "Webhook %s blocked — URL %s resolves to private/internal network",
                webhook.pk, webhook.url,
            )
            return

        body = {
            'event': event_type,
            'election_uuid': str(election.election_uuid),
            'election_name': election.name,
            'timestamp': timezone.now().isoformat(),
            'data': payload,
        }

        body_bytes = json.dumps(body, separators=(',', ':')).encode('utf-8')

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'ElectON-Webhook/2.0',
            'X-ElectON-Event': event_type,
        }

        # HMAC signature if secret is configured
        if webhook.secret:
            signature = hmac.new(
                webhook.secret.encode('utf-8'),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
            headers['X-ElectON-Signature'] = f'sha256={signature}'

        try:
            response = requests.post(
                webhook.url,
                data=body_bytes,
                headers=headers,
                timeout=WEBHOOK_TIMEOUT,
            )
            webhook.last_triggered = timezone.now()
            webhook.last_status_code = response.status_code

            if response.ok:
                webhook.failure_count = 0
            else:
                # Atomic increment to prevent race conditions (BE-53)
                Webhook.objects.filter(pk=webhook.pk).update(
                    failure_count=F('failure_count') + 1,
                    last_triggered=timezone.now(),
                    last_status_code=response.status_code,
                )
                webhook.refresh_from_db()
                logger.warning(
                    "Webhook %s returned %s for event %s",
                    webhook.pk, response.status_code, event_type,
                )
                # Check auto-disable after atomic update
                if webhook.failure_count >= MAX_FAILURES:
                    Webhook.objects.filter(pk=webhook.pk).update(is_active=False)
                    logger.warning(
                        "Webhook %s auto-disabled after %d consecutive failures",
                        webhook.pk, webhook.failure_count,
                    )
                return

        except requests.RequestException as exc:
            Webhook.objects.filter(pk=webhook.pk).update(
                failure_count=F('failure_count') + 1,
                last_triggered=timezone.now(),
                last_status_code=None,
            )
            webhook.refresh_from_db()
            logger.error(
                "Webhook %s failed for event %s: %s",
                webhook.pk, event_type, exc,
            )
            if webhook.failure_count >= MAX_FAILURES:
                Webhook.objects.filter(pk=webhook.pk).update(is_active=False)
                logger.warning(
                    "Webhook %s auto-disabled after %d consecutive failures",
                    webhook.pk, webhook.failure_count,
                )
            return

        # Success path — save reset counter
        webhook.save(update_fields=[
            'last_triggered', 'last_status_code', 'failure_count',
            'updated_at',
        ])
