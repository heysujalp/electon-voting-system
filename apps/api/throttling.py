"""
Custom DRF throttle classes for rate-limiting specific API endpoints.
Global defaults (30/min anon, 120/min user) are in settings.
These classes provide stricter limits for sensitive endpoints.
"""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class VoterLoginThrottle(AnonRateThrottle):
    """Stricter rate limit for voter login attempts."""

    rate = "10/minute"


class VoteCastThrottle(SimpleRateThrottle):
    """Rate limit for vote casting per session."""

    scope = "vote_cast"
    rate = "30/minute"

    def get_cache_key(self, request, view):
        voter_id = request.session.get("voter_credential_id")
        if voter_id:
            return self.cache_format % {"scope": self.scope, "ident": voter_id}
        # MED-24: Return None to skip throttle for unauthenticated requests
        # (permission class will reject them instead)
        return None


class BlockchainVerifyThrottle(AnonRateThrottle):
    """Rate limit for public blockchain verification (hits Solana RPC)."""

    rate = "10/minute"


class PublicResultsThrottle(AnonRateThrottle):
    """Rate limit for public election results endpoint."""

    rate = "30/minute"
