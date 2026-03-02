"""
ElectON v2 — Accounts middleware.
"""
import logging

from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('electon')


class SessionCleanupMiddleware:
    """
    Periodically clean up expired sessions.
    Uses a cache key to throttle cleanup to once per hour.
    """
    CLEANUP_INTERVAL = 3600  # 1 hour
    CACHE_KEY = 'session_cleanup_last_run'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._maybe_cleanup()
        response = self.get_response(request)
        return response

    def _maybe_cleanup(self):
        """Run cleanup if the interval has elapsed."""
        if cache.get(self.CACHE_KEY):
            return  # Already ran recently

        try:
            deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
            if deleted:
                logger.info("Cleaned up %d expired sessions", deleted)
            cache.set(self.CACHE_KEY, True, timeout=self.CLEANUP_INTERVAL)
        except Exception:
            # Don't let cleanup errors break the request
            logger.exception("Session cleanup failed")
