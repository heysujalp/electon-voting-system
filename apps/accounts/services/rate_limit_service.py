"""
ElectON v2 — Rate Limit Service.
Unified rate limiting using Django cache backend.
Works with any cache backend (Redis in prod, DB cache in dev).
"""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('electon.security')


class RateLimitService:
    """
    Unified rate limiter for all operations.

    Usage:
        limiter = RateLimitService('admin_login', max_attempts=5, window_seconds=300)
        if not limiter.is_allowed(client_ip):
            return HttpResponse(status=429)
        limiter.record_attempt(client_ip)
    """

    def __init__(self, operation: str, max_attempts: int, window_seconds: int):
        self.operation = operation
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    def _cache_key(self, identifier: str) -> str:
        """Build cache key for this operation + identifier."""
        return f"rl:{self.operation}:{identifier}"

    def is_allowed(self, identifier: str) -> bool:
        """Check if the identifier is allowed to perform the operation."""
        key = self._cache_key(identifier)
        count = cache.get(key)
        if count is None:
            return True
        return count < self.max_attempts

    def record_attempt(self, identifier: str) -> None:
        """Record an attempt for the identifier (atomic increment)."""
        key = self._cache_key(identifier)
        try:
            # Atomic increment — avoids race condition under concurrent requests
            new_count = cache.incr(key)
        except ValueError:
            # Key doesn't exist yet — atomically set initial value
            # MED-39: Use add() instead of set() to prevent race condition
            if cache.add(key, 1, timeout=self.window_seconds):
                new_count = 1
            else:
                # Another thread just created it — retry increment
                try:
                    new_count = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, timeout=self.window_seconds)
                    new_count = 1

        if new_count >= self.max_attempts:
            logger.warning(
                "Rate limit reached: operation=%s, identifier=%s, attempts=%d",
                self.operation, identifier, new_count
            )

    def reset(self, identifier: str) -> None:
        """Reset the rate limit counter for an identifier (e.g., after successful login)."""
        cache.delete(self._cache_key(identifier))

    def get_remaining_attempts(self, identifier: str) -> int:
        """Get the number of remaining attempts."""
        key = self._cache_key(identifier)
        count = cache.get(key)
        if count is None:
            return self.max_attempts
        return max(0, self.max_attempts - count)

    def get_retry_after(self, identifier: str) -> int:
        """Get seconds until the rate limit resets."""
        key = self._cache_key(identifier)
        ttl = cache.ttl(key) if hasattr(cache, 'ttl') else None
        if ttl is not None:
            return max(0, ttl)
        # Fallback for cache backends without ttl()
        return self.window_seconds


def get_client_ip(request) -> str:
    """Extract client IP from request, handling proxies.

    .. deprecated:: Use ``electon.utils.get_client_ip`` instead.
    This re-export is kept for backward compatibility.
    """
    from electon.utils import get_client_ip as _get_client_ip
    return _get_client_ip(request)
