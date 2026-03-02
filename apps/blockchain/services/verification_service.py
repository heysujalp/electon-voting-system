"""Public vote verification service — Solana.

Allows anyone to verify a vote on-chain using the voter's hash, and compare
DB vs on-chain counts for integrity auditing.

Merkle model change
-------------------
With the new Merkle tree architecture, on-chain vote confirmation is checked
via the *voted_bitfield* (one bit per voter index).  The old approach of
searching the ``voter_hashes`` list is gone because that field no longer
exists on ``ElectionState``.

If the election PDA has already been closed (post ``close_election``), we
fall back to ``BlockchainArchive.voter_has_voted()``.
"""
import logging

from django.db.models import Count

from ..models import ContractDeployment  # noqa: F401 — kept for indirect usage
from .program_service import ProgramService

logger = logging.getLogger("electon.blockchain")


class VerificationService:
    """Verify votes and compare DB vs on-chain counts on Solana."""

    def __init__(self):
        self.svc = ProgramService()

    def verify_vote(self, election, voter_hash_hex: str):
        """Verify whether a voter has cast their vote.

        Looks up the ``VoterCredential`` whose ``blockchain_voter_hash`` matches
        ``voter_hash_hex``, then checks bit *voter_index* of the on-chain
        ``voted_bitfield``.  Falls back to ``BlockchainArchive`` if the account
        is already closed.

        Returns::

            {
                'verified': bool,       # True  ⟹ vote confirmed on-chain
                'voter_hash': str,
                'error': str | None,
            }
        """
        try:
            from apps.voting.models import VoterCredential

            voter_hash_hex = voter_hash_hex.replace("0x", "")

            # Resolve voter_index from the credential record
            try:
                cred = VoterCredential.objects.get(
                    election=election,
                    blockchain_voter_hash=voter_hash_hex,
                )
            except VoterCredential.DoesNotExist:
                return {
                    "verified": False,
                    "voter_hash": voter_hash_hex,
                    "error": "Voter hash not registered for this election.",
                }

            voter_index: int = cred.blockchain_voter_index
            if voter_index is None:
                return {
                    "verified": False,
                    "voter_hash": voter_hash_hex,
                    "error": "Voter has no assigned index — election may not have been deployed.",
                }

            # ── Try live on-chain state first ────────────────────────────────
            state = self.svc.get_election_state(election)
            if state is not None:
                bitfield = bytes(state.voted_bitfield)
                byte_idx = voter_index // 8
                bit_idx = voter_index % 8
                verified = (
                    byte_idx < len(bitfield)
                    and bool(bitfield[byte_idx] & (1 << bit_idx))
                )
                return {"verified": verified, "voter_hash": voter_hash_hex, "error": None}

            # ── Fall back to BlockchainArchive if account is closed ──────────
            try:
                archive = election.blockchain_archive
                if archive:
                    verified = archive.voter_has_voted(voter_index)
                    return {"verified": verified, "voter_hash": voter_hash_hex, "error": None}
            except Exception:
                pass

            return {
                "verified": False,
                "voter_hash": voter_hash_hex,
                "error": "No on-chain state found and no archive available.",
            }

        except Exception:
            logger.exception("Vote verification failed for election %s", election.pk)
            return {
                "verified": False,
                "voter_hash": voter_hash_hex,
                "error": "Verification failed. Please try again later.",
            }

    def compare_db_and_chain(self, election):
        """
        Compare vote counts between the database and the Solana program.

        Returns::

            {
                'match': bool,
                'posts': [
                    {
                        'post_index': int,
                        'post_name': str,
                        'candidates': [
                            {
                                'candidate_index': int,
                                'candidate_name': str,
                                'db_count': int,
                                'chain_count': int,
                                'match': bool,
                            }
                        ]
                    }
                ],
                'total_votes_db': int,
                'total_votes_chain': int,
                'error': str | None,
            }
        """
        try:
            from apps.voting.models import Vote

            on_chain = self.svc.get_on_chain_vote_counts(election)
            if not on_chain:
                return {
                    "match": False,
                    "posts": [],
                    "total_votes_db": 0,
                    "total_votes_chain": 0,
                    "error": "No on-chain data available.",
                }

            all_match = True
            posts_report = []
            total_db = 0
            total_chain = 0

            posts = list(
                election.posts
                .prefetch_related("candidates")
                .order_by("order", "created_at")
            )

            for post_idx, post in enumerate(posts):
                candidates = list(post.candidates.order_by("order", "name"))
                candidates_report = []

                db_counts = (
                    Vote.objects.filter(election=election, post=post)
                    .values("candidate_id")
                    .annotate(count=Count("id"))
                )
                db_map = {row["candidate_id"]: row["count"] for row in db_counts}

                chain_post_counts = on_chain.get(post_idx, {})

                for cand_idx, candidate in enumerate(candidates):
                    db_count = db_map.get(candidate.pk, 0)
                    chain_count = chain_post_counts.get(cand_idx, 0)
                    match = db_count == chain_count
                    if not match:
                        all_match = False

                    total_db += db_count
                    total_chain += chain_count

                    candidates_report.append({
                        "candidate_index": cand_idx,
                        "candidate_name": candidate.name,
                        "db_count": db_count,
                        "chain_count": chain_count,
                        "match": match,
                    })

                posts_report.append({
                    "post_index": post_idx,
                    "post_name": post.name,
                    "candidates": candidates_report,
                })

            return {
                "match": all_match,
                "posts": posts_report,
                "total_votes_db": total_db,
                "total_votes_chain": total_chain,
                "error": None,
            }

        except Exception as exc:
            logger.exception("DB vs Solana comparison failed for election %s", election.pk)
            return {"match": False, "posts": [], "total_votes_db": 0, "total_votes_chain": 0, "error": "Comparison failed. Please try again later."}
