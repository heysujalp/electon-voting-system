"""
API views for ElectON.

Endpoints:
    GET  /api/elections/                         - List admin's elections
    GET  /api/elections/<uuid>/                   - Election detail + stats
    GET  /api/elections/<uuid>/results/           - Public results
    POST /api/voting/login/                       - Voter login
    POST /api/voting/cast/                        - Cast votes
    GET  /api/blockchain/verify/<uuid>/           - Verify vote on-chain
    GET  /api/health/                             - Health check
"""

import logging

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.voting.models import Vote, VoterCredential

from .permissions import HasVoterSession, IsElectionOwner
from .serializers import (
    BlockchainVerifySerializer,
    ElectionDetailSerializer,
    ElectionListSerializer,
    ElectionResultsSerializer,
    VoteCastSerializer,
    VoterLoginSerializer,
)
from .throttling import BlockchainVerifyThrottle, PublicResultsThrottle, VoteCastThrottle, VoterLoginThrottle

logger = logging.getLogger("electon.api")


# ──────────────────────────────────────────────
#  Health check
# ──────────────────────────────────────────────

class HealthCheckView(APIView):
    """Health check with database and cache connectivity verification."""

    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        health = {"status": "ok", "timestamp": timezone.now().isoformat()}

        # Check database connectivity
        try:
            from django.db import connection
            connection.ensure_connection()
            health["database"] = "ok"
        except Exception:
            health["database"] = "error: unavailable"
            health["status"] = "degraded"

        # Check cache connectivity
        try:
            from django.core.cache import cache
            cache.set("health_check", True, 10)
            if cache.get("health_check"):
                health["cache"] = "ok"
            else:
                health["cache"] = "error: unable to read"
                health["status"] = "degraded"
        except Exception:
            health["cache"] = "error: unavailable"
            health["status"] = "degraded"

        resp_status = status.HTTP_200_OK if health["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(health, status=resp_status)


# ──────────────────────────────────────────────
#  Election endpoints (admin)
# ──────────────────────────────────────────────

class ElectionListView(APIView):
    """List elections created by the authenticated admin."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        elections = (
            Election.objects.filter(created_by=request.user)
            .annotate(
                post_count=models.Count("posts", distinct=True),
                voter_count=models.Count("voter_credentials", distinct=True),
            )
            .order_by("-created_at")
        )
        serializer = ElectionListSerializer(elections, many=True)
        return Response(serializer.data)


class ElectionDetailView(APIView):
    """Election detail with full posts, candidates, and stats."""

    permission_classes = [IsAuthenticated, IsElectionOwner]

    def get(self, request, election_uuid):
        # MED-22: Check permission early before expensive query
        try:
            election_simple = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            return Response(
                {"error": "Election not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.check_object_permissions(request, election_simple)

        try:
            election = (
                Election.objects.annotate(
                    post_count=models.Count("posts", distinct=True),
                    voter_count=models.Count("voter_credentials", distinct=True),
                    votes_cast=models.Count(
                        "votes__voter_hash",
                        distinct=True,
                    ),
                )
                .prefetch_related("posts__candidates")
                .get(election_uuid=election_uuid)
            )
        except Election.DoesNotExist:
            return Response(
                {"error": "Election not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ElectionDetailSerializer(election, context={"request": request})
        return Response(serializer.data)


# ──────────────────────────────────────────────
#  Results endpoint (public when enabled)
# ──────────────────────────────────────────────

class ElectionResultsView(APIView):
    """
    Public election results.
    Only accessible if the election's voter_results_visibility is True
    and the election is in 'completed' status.
    """

    permission_classes = [AllowAny]
    throttle_classes = [PublicResultsThrottle]

    def get(self, request, election_uuid):
        try:
            election = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            return Response(
                {"error": "Election not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not election.allow_voter_results_view:
            return Response(
                {"error": "Results are not publicly visible for this election."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if election.current_status != "Concluded":
            return Response(
                {"error": "Results are only available after the election has concluded."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Build results — annotated queries instead of N+1
        total_voters = VoterCredential.objects.filter(election=election).count()
        total_votes = (
            Vote.objects.filter(election=election)
            .values("voter_hash")
            .distinct()
            .count()
        )
        turnout = (total_votes / total_voters * 100) if total_voters > 0 else 0.0

        posts_data = []
        for post in election.posts.order_by('order', 'created_at'):
            candidates_qs = (
                post.candidates
                .annotate(vote_count=models.Count('votes'))
                .order_by('-vote_count', 'name')
            )
            candidates_data = [
                {
                    "id": c.pk,
                    "name": c.name,
                    "vote_count": c.vote_count,
                }
                for c in candidates_qs
            ]
            posts_data.append({
                "id": post.pk,
                "name": post.name,
                "candidates": candidates_data,
            })

        result = {
            "election_uuid": election.election_uuid,
            "election_name": election.name,
            "total_voters": total_voters,
            "total_votes_cast": total_votes,
            "turnout_percentage": round(turnout, 2),
            "posts": posts_data,
        }

        serializer = ElectionResultsSerializer(result)
        return Response(serializer.data)


# ──────────────────────────────────────────────
#  Voter authentication
# ──────────────────────────────────────────────

class VoterLoginView(APIView):
    """Authenticate a voter and create a session."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [VoterLoginThrottle]

    def post(self, request):
        serializer = VoterLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        election_uuid = serializer.validated_data["election_uuid"]

        try:
            election = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            # MED-23: Uniform error to prevent election enumeration
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if election.current_status != "Active":
            return Response(
                {"error": "This election is not currently accepting votes."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            credential = VoterCredential.objects.get(
                election=election, one_time_username=username
            )
        except VoterCredential.DoesNotExist:
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not credential.check_password(password):
            return Response(
                {"error": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if credential.is_revoked:
            return Response(
                {"error": "Access has been revoked."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if credential.has_voted:
            return Response(
                {"error": "You have already voted in this election."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # SEC: Cycle session key before storing voter data (prevent session fixation)
        request.session.cycle_key()
        request.session["voter_credential_id"] = credential.pk
        request.session["election_uuid"] = str(election.election_uuid)
        request.session.set_expiry(1800)  # 30 minutes

        return Response({
            "message": "Login successful.",
            "election_name": election.name,
            "election_uuid": str(election.election_uuid),
        })


# ──────────────────────────────────────────────
#  Vote casting
# ──────────────────────────────────────────────

class VoteCastView(APIView):
    """Cast votes for an election."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [HasVoterSession]
    throttle_classes = [VoteCastThrottle]

    def post(self, request):
        serializer = VoteCastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        credential_id = request.session.get("voter_credential_id")
        election_uuid = request.session.get("election_uuid")

        # Wrap in transaction so select_for_update lock is effective
        with transaction.atomic():
            try:
                # Lock the credential row to prevent double-vote race condition
                credential = VoterCredential.objects.select_for_update().select_related("election").get(
                    pk=credential_id
                )
            except VoterCredential.DoesNotExist:
                return Response(
                    {"error": "Invalid voter session."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            election = credential.election

            if str(election.election_uuid) != election_uuid:
                return Response(
                    {"error": "Session election mismatch."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if election.current_status != "Active":
                return Response(
                    {"error": "This election is not currently accepting votes."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if credential.has_voted:
                return Response(
                    {"error": "You have already voted."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            votes_data = serializer.validated_data["votes"]

            # Validate that all post_ids belong to this election
            election_post_ids = set(
                election.posts.values_list("id", flat=True)
            )
            submitted_post_ids = set()

            for post_id_str, candidate_id in votes_data.items():
                try:
                    post_id = int(post_id_str)
                except (ValueError, TypeError):
                    return Response(
                        {"error": f"Invalid post ID: {post_id_str}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if post_id not in election_post_ids:
                    return Response(
                        {"error": f"Post {post_id} does not belong to this election."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # FEAT-01: Handle abstain values — skip candidate validation
                if candidate_id is None or str(candidate_id) == 'abstain':
                    submitted_post_ids.add(post_id)
                    continue

                # Validate candidate belongs to this post
                try:
                    cid = int(candidate_id)
                except (ValueError, TypeError):
                    return Response(
                        {"error": f"Invalid candidate ID: {candidate_id} for post {post_id}."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not Candidate.objects.filter(pk=cid, post_id=post_id).exists():
                    return Response(
                        {"error": f"Candidate {cid} is not valid for post {post_id}."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                submitted_post_ids.add(post_id)

            # Ensure all posts have a vote (unless abstain is allowed)
            missing = election_post_ids - submitted_post_ids
            if missing and not election.allow_abstain:
                return Response(
                    {"error": f"Missing votes for posts: {sorted(missing)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Cast votes via service
            from apps.voting.services.vote_service import VoteService

            try:
                VoteService.cast_votes(
                    credential=credential,
                    votes_data={int(k): v for k, v in votes_data.items()},
                )
            except Exception as exc:
                logger.exception("Vote casting failed via API")
                return Response(
                    {"error": "Failed to record votes. Please try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # BE-64: Clear voter session — credential already marked as voted
        # so a retry after flush shows "already voted" instead of "invalid session"
        try:
            request.session.flush()
        except Exception:
            logger.warning("Session flush failed after vote cast for credential %s", credential_id)

        return Response(
            {"message": "Your votes have been recorded successfully."},
            status=status.HTTP_201_CREATED,
        )


# ──────────────────────────────────────────────
#  Blockchain verification
# ──────────────────────────────────────────────

class BlockchainVerifyView(APIView):
    """Public endpoint to verify a vote on Solana."""

    permission_classes = [AllowAny]
    throttle_classes = [BlockchainVerifyThrottle]

    def get(self, request, election_uuid):
        voter_hash = request.query_params.get("voter_hash", "").strip()

        if not voter_hash:
            return Response(
                {"error": "voter_hash query param is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate hex
        try:
            bytes.fromhex(voter_hash)
        except ValueError:
            return Response(
                {"error": "voter_hash must be a valid hex string."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            election = Election.objects.get(election_uuid=election_uuid)
        except Election.DoesNotExist:
            return Response(
                {"error": "Election not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from apps.blockchain.services.verification_service import VerificationService

        svc = VerificationService()
        result = svc.verify_vote(election, voter_hash)

        serializer = BlockchainVerifySerializer(result)
        resp_status = status.HTTP_200_OK if result["error"] is None else status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response(serializer.data, status=resp_status)
