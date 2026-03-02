"""
ElectON v2 — Core voting logic with anonymized dual-write.

``VoteService.cast_votes()`` atomically:
  1. Locks the credential (``select_for_update``)
  2. Re-validates eligibility
  3. Creates ``Vote`` records with an irreversible ``voter_hash``
  4. Marks the credential as voted
  5. (Phase 3) Enqueues blockchain submission after DB commit
"""
import hashlib
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.candidates.models import Candidate
from apps.voting.models import Vote, VoterCredential

logger = logging.getLogger(__name__)


class VoteService:
    """Handles vote casting with DB + blockchain dual-write."""

    # ------------------------------------------------------------------
    # Voter-hash generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_voter_hash(credential_id: int, election_id: int, election_uuid=None) -> str:
        """
        Irreversible SHA-256 hash.

        Uses credential PK + election UUID + deployment salt for added
        entropy, making brute-force impractical even with sequential PKs.
        """
        if election_uuid is None:
            from apps.elections.models import Election
            try:
                election_uuid = Election.objects.values_list(
                    'election_uuid', flat=True
                ).get(pk=election_id)
            except Election.DoesNotExist:
                election_uuid = election_id

        salt = settings.VOTE_ANONYMIZATION_SALT
        data = f"{credential_id}:{election_uuid}:{salt}"
        return hashlib.sha256(data.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Cast votes
    # ------------------------------------------------------------------

    @classmethod
    def cast_votes(cls, credential: VoterCredential, votes_data: dict) -> dict:
        """
        Atomically cast votes for all posts in one election.

        Args:
            credential: Already-authenticated ``VoterCredential``.
            votes_data: ``{post_id: candidate_id, ...}``

        Returns:
            ``{'success': True, 'voter_hash': '<first 16 hex chars>'}``

        Raises:
            ``ValidationError`` on any failure.
        """
        election = credential.election
        voter_hash = cls.generate_voter_hash(credential.pk, election.pk, election_uuid=election.election_uuid)

        with transaction.atomic():
            # Lock the credential row to prevent race conditions
            locked = VoterCredential.objects.select_for_update().get(pk=credential.pk)

            if locked.has_voted:
                raise ValidationError("You have already voted.")
            if locked.is_revoked:
                raise ValidationError("Your access has been revoked.")
            if not election.can_vote:
                raise ValidationError("This election is not currently accepting votes.")

            # Validate every post/candidate pair in a single batch query (OPT-04)
            try:
                candidate_ids = [int(cid) for cid in votes_data.values() if cid is not None and str(cid) != 'abstain']
            except (ValueError, TypeError):
                raise ValidationError("Invalid candidate ID format.")

            candidates_by_pk = {
                c.pk: c
                for c in Candidate.objects.filter(
                    pk__in=candidate_ids, election=election,
                ).select_related('post')
            }

            vote_objects = []
            for post_id_str, candidate_id_raw in votes_data.items():
                try:
                    post_id = int(post_id_str)
                except (ValueError, TypeError):
                    raise ValidationError(f"Invalid post ID: {post_id_str}")

                # FEAT-01: Support abstain/NOTA
                if candidate_id_raw is None or str(candidate_id_raw) == 'abstain':
                    if not election.allow_abstain:
                        raise ValidationError("Abstaining is not allowed for this election.")
                    # Skip creating a Vote record for abstained posts
                    continue

                candidate_id = int(candidate_id_raw)
                candidate = candidates_by_pk.get(candidate_id)
                if candidate is None:
                    raise ValidationError(f"Candidate {candidate_id} not found in this election.")
                if candidate.post_id != post_id:
                    raise ValidationError(
                        f"Candidate {candidate.name} does not belong to post {post_id}."
                    )

                vote_objects.append(
                    Vote(
                        election=election,
                        post_id=post_id,
                        candidate=candidate,
                        voter_hash=voter_hash,
                    )
                )

            # Bulk-create all votes in one query
            Vote.objects.bulk_create(vote_objects)

            # Mark credential as voted
            locked.has_voted = True
            locked.voted_at = timezone.now()
            locked.save(update_fields=['has_voted', 'voted_at', 'updated_at'])

        # --- After DB commit: invalidate analytics cache (OPT-03) ---
        from django.core.cache import cache as django_cache
        django_cache.delete(f'election_stats:{election.pk}')
        django_cache.delete(f'chartjs_pie:{election.pk}')
        django_cache.delete(f'chartjs_turnout:{election.pk}')
        django_cache.delete(f'chartjs_timeline:{election.pk}')

        # --- FEAT-06: Fire webhook for vote.cast ---
        try:
            from apps.notifications.services.webhook_service import WebhookService
            WebhookService.dispatch(election, 'vote.cast', {
                'voter_hash': hashlib.sha256(voter_hash.encode()).hexdigest()[:16],
                'posts_voted': len(vote_objects),
            })
        except Exception:
            logger.debug("Webhook dispatch failed for vote.cast", exc_info=True)

        # SSE: push vote_cast event with live turnout stats
        try:
            from apps.elections.event_emitter import emit_event, build_stats_payload
            emit_event(
                election.election_uuid, 'vote_cast',
                build_stats_payload(election),
                user_id=election.created_by_id,
            )
        except Exception:
            logger.debug("SSE emit failed for vote.cast", exc_info=True)

        # --- After DB commit: blockchain submission via Celery (async) ---
        try:
            from apps.blockchain.tasks import submit_votes_to_chain
            submit_votes_to_chain.delay(
                election_id=election.pk,
                voter_hash=voter_hash,
                votes_data=votes_data,
            )
        except Exception:
            logger.exception(
                "Blockchain submission failed for election %s", election.election_uuid,
            )

        logger.info(
            "Votes cast: election=%s posts=%d",
            election.election_uuid,
            len(vote_objects),
        )

        return {
            'success': True,
            'voter_hash': hashlib.sha256(voter_hash.encode()).hexdigest()[:16],  # MED-13: Double-hash for receipt (matches webhook)
        }
