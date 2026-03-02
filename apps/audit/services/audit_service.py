"""
ElectON v2 — Audit service.
Central interface for logging audit events throughout the application.
"""
import logging

from electon.utils import get_client_ip

logger = logging.getLogger('electon.security')


class AuditService:
    """Log security-sensitive actions to the AuditLog model."""

    @staticmethod
    def log(action: str, request=None, user=None, election=None, **details):
        """
        Create an audit log entry.

        Args:
            action: One of AuditLog.Action choices (e.g., 'login_success')
            request: Django HttpRequest (optional, used for IP/user-agent)
            user: The user performing the action (auto-detected from request if not given)
            election: Related election (optional)
            **details: Additional metadata stored as JSON
        """
        # Import here to avoid circular imports at module level
        from apps.audit.models import AuditLog

        # Validate action string against defined choices
        valid_actions = {choice[0] for choice in AuditLog.Action.choices}
        if action not in valid_actions:
            logger.warning(
                "AUDIT: invalid action '%s' — not in AuditLog.Action.choices. "
                "Logging anyway for forensics.", action,
            )

        # Determine user
        if user is None and request and hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user

        # Extract request metadata
        ip_address = None
        user_agent = ''
        if request:
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        try:
            AuditLog.objects.create(
                action=action,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details or {},
                election=election,
            )
        except Exception:
            # Never let audit logging break the application
            logger.exception("Failed to create audit log: action=%s", action)

        # Also log to file for redundancy
        user_str = user.username if user else 'anonymous'
        logger.info(
            "AUDIT: action=%s user=%s ip=%s election=%s details=%s",
            action, user_str, ip_address,
            election.election_uuid if election else None,
            details,
        )
