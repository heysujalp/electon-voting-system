"""High-level Solana program interactions for ElectON elections.

Architecture: Merkle Tree model
---------------------------------
Django builds a Merkle tree of voter hashes off-chain and stores only the
32-byte root on-chain (initialize_election).  When a voter casts a ballot,
the Solana program verifies a Merkle proof and records the vote in a compact
bitfield.  There is no register_voters instruction.

After an election ends, archive_and_close reads the full on-chain state into
Django (BlockchainArchive), finalises the account, then closes it to recover
the rent deposit.

Bug fixes:
  B-01: _run_async uses ThreadPoolExecutor to avoid event-loop deadlocks.
  B-02: One AsyncClient per multi-step RPC operation.
  B-04: _compute_config_hash uses deterministic ordering.
  N-06: Merkle tree cached after deployment (avoids O(n) rebuild per vote).
  N-07: filter uses exclude(blockchain_voter_hash='') instead of __isnull=False.
  N-08: archive_and_close is idempotent (checks is_finalized before retrying).
  N-09: deploy_election checks PDA existence to handle partial-deploy retries.
  N-10: Slot captured per-transaction instead of once after both.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from ..models import BlockchainArchive, BlockchainTransaction, ContractDeployment
from .merkle_tree import build_merkle_tree, get_merkle_proof
from .solana_client import SolanaClient

logger = logging.getLogger("electon.blockchain")

IDL_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "electon_voting.json"
)


def _get_program_id():
    from solders.pubkey import Pubkey  # type: ignore
    pid = getattr(settings, "SOLANA_PROGRAM_ID", "")
    if not pid:
        raise ValueError("SOLANA_PROGRAM_ID is not configured.")
    return Pubkey.from_string(pid)


def _get_rpc_url() -> str:
    url = getattr(settings, "SOLANA_RPC_URL", "")
    if not url:
        raise ValueError(
            "SOLANA_RPC_URL is not configured. "
            "Set it in .env or as an environment variable."
        )
    return url


def _get_commitment() -> str:
    """Return the configured Solana commitment level."""
    return getattr(settings, "SOLANA_COMMITMENT", "confirmed")


def _is_mainnet() -> bool:
    return getattr(settings, "SOLANA_NETWORK", "devnet") == "mainnet-beta"


def _run_async(coro):
    """Fix B-01: always run in a fresh ThreadPoolExecutor thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=120)


class ProgramService:
    """Election-level Solana program operations."""

    def __init__(self):
        self.client = SolanaClient()
        self.program_id = _get_program_id()

    def get_election_pda(self, election):
        from solders.pubkey import Pubkey  # type: ignore
        seeds = [b"election", election.election_uuid.bytes]
        pda, _bump = Pubkey.find_program_address(seeds, self.program_id)
        return pda

    # -------------------------------------------------------------------
    #  Deploy
    # -------------------------------------------------------------------

    def deploy_election(self, election) -> str:
        """Initialize the election on Solana with a Merkle tree root.

        N-09: If the PDA already exists (e.g. prior deploy succeeded on-chain
        but DB save failed), skip the on-chain call and just record in DB.
        N-06: Caches the Merkle tree layers after building.
        """
        from apps.voting.models import VoterCredential

        election_pda = self.get_election_pda(election)
        config_hash = self._compute_config_hash(election)

        posts = list(
            election.posts.prefetch_related("candidates").order_by("order", "created_at")
        )
        candidates_per_post: List[int] = [p.candidates.count() for p in posts]

        credentials = list(VoterCredential.objects.filter(election=election).order_by("pk"))
        if not credentials:
            raise ValueError(
                f"Election {election.election_uuid} has no registered voters."
            )

        salt: str = getattr(settings, "VOTE_ANONYMIZATION_SALT", "")
        leaves: List[bytes] = []
        for idx, cred in enumerate(credentials):
            raw = f"{cred.pk}:{election.election_uuid}:{salt}"
            leaf = hashlib.sha256(raw.encode()).digest()
            cred.blockchain_voter_hash = leaf.hex()
            cred.blockchain_voter_index = idx
            leaves.append(leaf)

        VoterCredential.objects.bulk_update(
            credentials,
            ["blockchain_voter_hash", "blockchain_voter_index"],
            batch_size=500,
        )

        merkle_root, layers = build_merkle_tree(leaves)

        # N-06: Cache the Merkle tree layers so cast_vote doesn't rebuild
        cache.set(
            f"merkle_tree:{election.election_uuid}",
            layers,
            timeout=None,  # never expires — tree is immutable after deploy
        )

        # N-09: Check if PDA already exists on-chain (idempotent deploy)
        existing_account = self.client.get_account_info(election_pda)
        pda_exists = existing_account and existing_account.value is not None

        if pda_exists:
            logger.info(
                "PDA already exists for election %s — recording in DB only",
                election.election_uuid,
            )
            # Retrieve the existing deploy signature if available
            sig = "pda-already-existed"
        else:
            sig = _run_async(
                self._async_initialize_election(
                    election_pda=election_pda,
                    election_uuid_bytes=list(election.election_uuid.bytes),
                    config_hash_bytes=list(config_hash),
                    merkle_root_bytes=list(merkle_root),
                    num_voters=len(credentials),
                    num_posts=len(posts),
                    candidates_per_post=candidates_per_post,
                    start_time=int(election.start_time.timestamp()),
                    end_time=int(election.end_time.timestamp()),
                )
            )

        slot = self.client.get_slot()
        network = getattr(settings, "SOLANA_NETWORK", "devnet")
        commitment = _get_commitment()

        with transaction.atomic():
            ContractDeployment.objects.update_or_create(
                election=election,
                defaults={
                    "program_address": str(election_pda),
                    "deploy_tx_signature": sig,
                    "deploy_slot": slot,
                    "network": network,
                },
            )
            BlockchainTransaction.objects.update_or_create(
                election=election,
                tx_type=BlockchainTransaction.TxType.DEPLOY,
                defaults={
                    "tx_signature": sig,
                    "slot": slot,
                    "status": BlockchainTransaction.Status.CONFIRMED,
                    "confirmed_at": timezone.now(),
                },
            )
            election.blockchain_contract_address = str(election_pda)
            election.blockchain_deploy_tx = sig
            election.save(
                update_fields=["blockchain_contract_address", "blockchain_deploy_tx", "updated_at"]
            )

        logger.info(
            "Election %s deployed: PDA=%s sig=%s root=%s",
            election.election_uuid,
            str(election_pda)[:16],
            sig[:24],
            merkle_root.hex()[:16],
        )
        return sig

    async def _async_initialize_election(
        self, *, election_pda, election_uuid_bytes, config_hash_bytes,
        merkle_root_bytes, num_voters, num_posts, candidates_per_post,
        start_time, end_time,
    ) -> str:
        from solana.rpc.async_api import AsyncClient  # type: ignore
        from solders.system_program import ID as SYS_PROGRAM_ID  # type: ignore

        commitment = _get_commitment()
        async with AsyncClient(_get_rpc_url(), commitment=commitment) as client:
            program = self._make_program(client)
            sig = await program.rpc["initialize_election"](
                bytes(election_uuid_bytes),
                bytes(config_hash_bytes),
                bytes(merkle_root_bytes),
                num_voters,
                num_posts,
                bytes(candidates_per_post),  # borsh Bytes requires bytes, not list
                start_time,
                end_time,
                ctx=self._ctx({
                    "election_state": election_pda,
                    "authority": self.client.payer.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                }),
            )
            return str(sig)

    # -------------------------------------------------------------------
    #  Cast vote
    # -------------------------------------------------------------------

    def cast_vote(self, election, voter_hash_hex: str, voter_index: int, votes: List[Dict]) -> str:
        from apps.voting.models import VoterCredential

        election_pda = self.get_election_pda(election)
        voter_hash_bytes = bytes.fromhex(voter_hash_hex)

        # N-06: Try cached Merkle tree first; rebuild only on cache miss.
        layers = self._get_or_rebuild_merkle_tree(election)
        proof = get_merkle_proof(layers, voter_index)

        sig = _run_async(
            self._async_cast_vote(
                election_pda=election_pda,
                voter_index=voter_index,
                voter_hash_bytes=voter_hash_bytes,
                proof=proof,
                votes=votes,
            )
        )

        slot = self.client.get_slot()
        BlockchainTransaction.objects.create(
            election=election,
            tx_type=BlockchainTransaction.TxType.CAST_VOTE,
            tx_signature=sig,
            slot=slot,
            status=BlockchainTransaction.Status.PENDING,
        )
        logger.info("Vote submitted: election=%s idx=%d sig=%s", election.election_uuid, voter_index, sig[:24])
        return sig

    async def _async_cast_vote(self, *, election_pda, voter_index, voter_hash_bytes, proof, votes) -> str:
        from solana.rpc.async_api import AsyncClient  # type: ignore

        commitment = _get_commitment()
        async with AsyncClient(_get_rpc_url(), commitment=commitment) as client:
            program = self._make_program(client)
            sig = await program.rpc["cast_vote"](
                voter_index,
                voter_hash_bytes,            # borsh Bytes requires bytes, not list
                [list(p) for p in proof],   # Vec<[u8;32]> → list-of-lists-of-ints is correct
                votes,
                ctx=self._ctx({
                    "election_state": election_pda,
                    "authority": self.client.payer.pubkey(),
                }),
            )
            return str(sig)

    # -------------------------------------------------------------------
    #  Archive & close
    # -------------------------------------------------------------------

    def archive_and_close(self, election) -> None:
        _run_async(self._async_archive_and_close(election))

    async def _async_archive_and_close(self, election) -> None:
        """Archive on-chain state, finalize, and close the PDA account.

        N-08: Idempotent — checks is_finalized before calling finalize,
        and checks account existence before calling close.
        N-10: Captures slot per-transaction instead of once after both.
        """
        from solana.rpc.async_api import AsyncClient  # type: ignore

        election_pda = self.get_election_pda(election)
        commitment = _get_commitment()

        async with AsyncClient(_get_rpc_url(), commitment=commitment) as client:
            program = self._make_program(client)

            # Check if account still exists (may have been closed already)
            acct_info = await client.get_account_info(election_pda)
            if acct_info.value is None:
                logger.info(
                    "Election %s PDA already closed — skipping archive_and_close",
                    election.election_uuid,
                )
                return

            state = await program.account["ElectionState"].fetch(election_pda)

            cpp = list(state.candidates_per_post)
            flat = list(state.vote_counts)
            structured: Dict[str, Dict[str, int]] = {}
            offset = 0
            for post_idx, n in enumerate(cpp):
                structured[str(post_idx)] = {str(c): flat[offset + c] for c in range(n)}
                offset += n

            slot_resp = await client.get_slot()
            current_slot = slot_resp.value

            with transaction.atomic():
                archive, _ = BlockchainArchive.objects.update_or_create(
                    election=election,
                    defaults={
                        "merkle_root": bytes(state.merkle_root),
                        "voted_bitfield": bytes(state.voted_bitfield),
                        "vote_counts": structured,
                        "config_hash": bytes(state.config_hash),
                        "total_voters": state.num_voters,
                        "total_votes_cast": state.total_votes,
                        "on_chain_slot": current_slot,
                    },
                )

            # N-08: Only finalize if not already finalized (idempotent retry)
            fin_sig = None
            if not state.is_finalized:
                fin_sig = str(await program.rpc["finalize_election"](
                    ctx=self._ctx({"election_state": election_pda, "authority": self.client.payer.pubkey()}),
                ))
            else:
                logger.info("Election %s already finalized on-chain — skipping finalize", election.election_uuid)

            # N-10: Capture slot right after finalize
            fin_slot_resp = await client.get_slot()
            fin_slot = fin_slot_resp.value

            close_sig = str(await program.rpc["close_election"](
                ctx=self._ctx({"election_state": election_pda, "authority": self.client.payer.pubkey()}),
            ))

            # N-10: Capture slot right after close
            close_slot_resp = await client.get_slot()
            close_slot = close_slot_resp.value

        now = timezone.now()
        with transaction.atomic():
            if fin_sig:
                BlockchainTransaction.objects.create(
                    election=election,
                    tx_type=BlockchainTransaction.TxType.FINALIZE,
                    tx_signature=fin_sig,
                    slot=fin_slot,
                    status=BlockchainTransaction.Status.CONFIRMED,
                    confirmed_at=now,
                )
            BlockchainTransaction.objects.create(
                election=election,
                tx_type=BlockchainTransaction.TxType.CLOSE,
                tx_signature=close_sig,
                slot=close_slot,
                status=BlockchainTransaction.Status.CONFIRMED,
                confirmed_at=now,
            )
            archive.account_closed_at = now
            archive.save(update_fields=["account_closed_at"])

        logger.info(
            "Election %s archived/closed: fin=%s close=%s",
            election.election_uuid,
            (fin_sig or "already-finalized")[:24],
            close_sig[:24],
        )

    # -------------------------------------------------------------------
    #  Read state
    # -------------------------------------------------------------------

    def get_election_state(self, election):
        try:
            return _run_async(self._async_fetch_state(self.get_election_pda(election)))
        except Exception as exc:
            logger.warning("Failed to read state for election %s: %s", election.election_uuid, exc)
            return None

    def get_on_chain_vote_counts(self, election) -> Dict[int, Dict[int, int]]:
        try:
            archive = election.blockchain_archive
            if archive:
                return {int(k): {int(ck): cv for ck, cv in v.items()} for k, v in archive.vote_counts.items()}
        except Exception:
            pass

        state = self.get_election_state(election)
        if state is None:
            return {}

        flat = list(state.vote_counts)
        cpp = list(state.candidates_per_post)
        result: Dict[int, Dict[int, int]] = {}
        offset = 0
        for post_idx, n in enumerate(cpp):
            result[post_idx] = {c: flat[offset + c] if offset + c < len(flat) else 0 for c in range(n)}
            offset += n
        return result

    def verify_config_hash(self, election) -> Optional[Tuple[bool, str]]:
        """Q-04: Compare on-chain config_hash with locally computed hash.

        Returns (match: bool, detail: str) or None if state unavailable.
        """
        state = self.get_election_state(election)
        if state is None:
            # Try the archive fallback
            try:
                archive = election.blockchain_archive
                if archive:
                    on_chain_hash = bytes(archive.config_hash)
                else:
                    return None
            except Exception:
                return None
        else:
            on_chain_hash = bytes(state.config_hash)

        expected_hash = self._compute_config_hash(election)
        match = on_chain_hash == expected_hash
        detail = "config_hash matches" if match else (
            f"MISMATCH: on-chain={on_chain_hash.hex()[:16]}… "
            f"expected={expected_hash.hex()[:16]}…"
        )
        return match, detail

    # -------------------------------------------------------------------
    #  Helpers
    # -------------------------------------------------------------------

    def _get_or_rebuild_merkle_tree(self, election) -> List[List[bytes]]:
        """Return cached Merkle tree layers; rebuild from DB on cache miss.

        N-06: The Merkle tree is immutable after deployment. Caching avoids
        an O(n) rebuild on every cast_vote call.
        N-07: Uses exclude(blockchain_voter_hash='') instead of __isnull=False
        since CharField defaults to '' not NULL.
        """
        from apps.voting.models import VoterCredential

        cache_key = f"merkle_tree:{election.election_uuid}"
        layers = cache.get(cache_key)
        if layers is not None:
            return layers

        credentials = list(
            VoterCredential.objects.filter(election=election)
            .exclude(blockchain_voter_hash="")
            .order_by("blockchain_voter_index")
        )
        leaves = [bytes.fromhex(c.blockchain_voter_hash) for c in credentials]
        _root, layers = build_merkle_tree(leaves)

        # Cache indefinitely — tree is immutable after deploy
        cache.set(cache_key, layers, timeout=None)
        return layers

    @staticmethod
    def _compute_config_hash(election) -> bytes:
        """SHA-256 of election config (B-04 fix: deterministic ordering)."""
        posts = election.posts.prefetch_related("candidates").order_by("order", "created_at")
        parts: List[str] = [str(election.election_uuid), election.name]
        for post in posts:
            cands = ",".join(c.name for c in post.candidates.order_by("order", "name"))
            parts.append(f"{post.name}:[{cands}]")
        return hashlib.sha256("|".join(parts).encode()).digest()

    async def _async_fetch_state(self, election_pda):
        from solana.rpc.async_api import AsyncClient  # type: ignore

        commitment = _get_commitment()
        async with AsyncClient(_get_rpc_url(), commitment=commitment) as client:
            program = self._make_program(client)
            return await program.account["ElectionState"].fetch(election_pda)

    def _make_program(self, async_client):
        from anchorpy import Idl, Program, Provider, Wallet  # type: ignore

        if not IDL_PATH.exists():
            raise FileNotFoundError(f"Anchor IDL not found at {IDL_PATH}.")
        with open(IDL_PATH) as fh:
            idl = Idl.from_json(fh.read())
        provider = Provider(async_client, Wallet(self.client.payer))
        return Program(idl, self.program_id, provider)

    @staticmethod
    def _ctx(accounts: dict):
        from anchorpy import Context  # type: ignore
        return Context(accounts=accounts)
