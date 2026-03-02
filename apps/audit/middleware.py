"""
ElectON v2 — Audit middleware.
Logs security-relevant requests automatically.
"""
import logging

from electon.utils import get_client_ip

logger = logging.getLogger('electon.security')


class AuditMiddleware:
    """
    Lightweight middleware that logs security-relevant request patterns.
    Heavy audit logging is done via AuditService in views/services.
    """

    # Paths that indicate security-sensitive actions
    MONITORED_PATHS = [
        '/accounts/login/',
        '/accounts/register/',
        '/accounts/forgot-password/',
        '/accounts/settings/delete-account/',
        '/voting/login/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Log failed security-relevant requests (4xx on monitored paths)
        if request.method == 'POST' and response.status_code >= 400:
            for path in self.MONITORED_PATHS:
                if request.path.startswith(path):
                    logger.warning(
                        "Security-relevant failure: method=%s path=%s status=%d ip=%s",
                        request.method,
                        request.path,
                        response.status_code,
                        get_client_ip(request),
                    )
                    break

        return response
