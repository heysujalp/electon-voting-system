"""Blockchain app views — public vote verification (Solana)."""

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import JsonResponse
from django.views import View

from apps.elections.models import Election
from electon.utils import get_client_ip
from .services.verification_service import VerificationService

logger = logging.getLogger("electon.blockchain")

# S-04: Per-IP rate limit for the public VerifyVoteView
_VERIFY_RATE_LIMIT = 10   # requests
_VERIFY_RATE_WINDOW = 60  # seconds


def _check_ip_rate_limit(request, limit: int, window: int, prefix: str) -> bool:
    """Return True if the request is within rate limits; False if exceeded.

    Uses Django's cache backend (Redis in production, LocMemCache in dev).
    N-03 fix: uses get_client_ip() which respects NUM_PROXIES.
    N-04 fix: uses atomic cache.add + cache.incr to prevent TOCTOU races.
    """
    ip = get_client_ip(request)
    cache_key = f"{prefix}:{ip}"
    # Atomically set the key if it doesn't exist (returns True on success)
    cache.add(cache_key, 0, timeout=window)
    try:
        current = cache.incr(cache_key)
    except ValueError:
        # Key expired between add and incr (extremely rare) — reset
        cache.set(cache_key, 1, timeout=window)
        current = 1
    return current <= limit


class VerifyVoteView(View):
    """Public endpoint for verifying a vote on Solana.

    POST /blockchain/<election_uuid>/verify/
    Body: { "voter_hash": "<hex-sha256>" }

    Rate limited to 10 requests per 60 s per IP (S-04).
    """

    http_method_names = ["post"]

    def post(self, request, election_uuid):
        # S-04: rate limit
        if not _check_ip_rate_limit(
            request,
            limit=_VERIFY_RATE_LIMIT,
            window=_VERIFY_RATE_WINDOW,
            prefix="verify_vote_rl",
        ):
            return JsonResponse(
                {"error": "Too many requests. Please wait before trying again."},
                status=429,
            )

        try:
            election = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            return JsonResponse({"error": "Election not found."}, status=404)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        voter_hash = body.get("voter_hash", "").strip()

        if not voter_hash:
            return JsonResponse({"error": "voter_hash is required."}, status=400)

        try:
            bytes.fromhex(voter_hash)
        except ValueError:
            return JsonResponse(
                {"error": "voter_hash must be a valid hex string."},
                status=400,
            )

        svc = VerificationService()
        result = svc.verify_vote(election, voter_hash)

        status_code = 200 if result["error"] is None else 500
        return JsonResponse(result, status=status_code)


class IntegrityCheckView(LoginRequiredMixin, View):
    """
    Admin endpoint for comparing DB vs on-chain vote counts.
    GET /blockchain/<election_uuid>/integrity/
    """

    http_method_names = ["get"]
    raise_exception = True  # Return 403 instead of redirect for unauthenticated

    def get(self, request, election_uuid):
        try:
            election = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            return JsonResponse({"error": "Election not found."}, status=404)

        # Allow staff OR the election owner
        if not request.user.is_staff and election.created_by_id != request.user.pk:
            return JsonResponse({"error": "Unauthorized."}, status=403)

        svc = VerificationService()
        result = svc.compare_db_and_chain(election)

        status_code = 200 if result["error"] is None else 500
        return JsonResponse(result, status=status_code)
