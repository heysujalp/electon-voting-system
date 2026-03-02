"""ElectON v2 — Blockchain background tasks (Solana).

Uses Celery @shared_task when available; falls back to synchronous
execution if Celery is not installed.
"""
import logging

from django.conf import settings

logger = logging.getLogger("electon.blockchain")

# Graceful Celery integration (BE-57)
try:
    from celery import shared_task
except ImportError:
    def shared_task(func=None, **kwargs):  # noqa: ARG001
        if func is not None:
            func.delay = lambda *a, **kw: func(*a, **kw)
            func.apply_async = lambda args=(), kwargs=None, **_: func(*args, **(kwargs or {}))
            return func
        def wrapper(fn):
            fn.delay = lambda *a, **kw: fn(*a, **kw)
            fn.apply_async = lambda args=(), kwargs=None, **_: fn(*args, **(kwargs or {}))
            return fn
        return wrapper


@shared_task(bind=True, ignore_result=True, max_retries=3)
def submit_votes_to_chain(self, election_id: int, voter_hash: str, votes_data: dict):
    """Submit votes to Solana after DB commit."""
    try:
        from apps.blockchain.services.program_service import ProgramService
        from apps.candidates.models import Candidate
        from apps.elections.models import Election, Post
        from apps.voting.models import Vote, VoterCredential

        election = Election.objects.get(pk=election_id)
        svc = ProgramService()

        if not election.blockchain_contract_address:
            logger.warning(
                "No Solana deployment for election %s — skipping chain submission",
                election.election_uuid,
            )
            return

        try:
            cred = VoterCredential.objects.get(
                election=election,
                blockchain_voter_hash=voter_hash,
            )
        except VoterCredential.DoesNotExist:
            logger.error(
                "Cannot find VoterCredential with hash %s for election %s",
                voter_hash[:16],
                election.election_uuid,
            )
            return

        voter_index = cred.blockchain_voter_index
        if voter_index is None:
            logger.error(
                "VoterCredential pk=%s has no blockchain_voter_index for election %s",
                cred.pk,
                election.election_uuid,
            )
            return

        posts = list(
            Post.objects
            .filter(election=election)
            .prefetch_related("candidates")
            .order_by("order", "created_at")
        )
        vote_entries = []
        for post_idx, post in enumerate(posts):
            candidate_id_raw = votes_data.get(str(post.pk))
            if candidate_id_raw is None or str(candidate_id_raw) == "abstain":
                continue
            candidate_id = int(candidate_id_raw)
            candidates = list(
                Candidate.objects.filter(post=post).order_by("order", "name")
            )
            cand_idx = next(
                (i for i, c in enumerate(candidates) if c.pk == candidate_id),
                None,
            )
            if cand_idx is not None:
                vote_entries.append({
                    "post_index": post_idx,
                    "candidate_index": cand_idx,
                })

        if not vote_entries:
            logger.info("No vote entries to submit for election %s", election.election_uuid)
            return

        tx_sig = svc.cast_vote(election, voter_hash, voter_index, vote_entries)

        Vote.objects.filter(
            election=election,
            voter_hash=voter_hash,
        ).update(blockchain_tx_hash=tx_sig)

        logger.info(
            "Blockchain votes submitted: election=%s voter_index=%d sig=%s",
            election.election_uuid,
            voter_index,
            tx_sig[:24],
        )

    except Exception as exc:
        logger.exception(
            "submit_votes_to_chain failed for election_id=%s", election_id
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, ignore_result=True, max_retries=3)
def archive_and_close_election(self, election_id: int):
    """Archive on-chain state and close the PDA after the election ends."""
    try:
        from apps.blockchain.services.program_service import ProgramService
        from apps.elections.models import Election

        election = Election.objects.get(pk=election_id)
        svc = ProgramService()

        if not election.blockchain_contract_address:
            logger.warning(
                "Election %s has no Solana deployment — skipping archive",
                election.election_uuid,
            )
            return

        try:
            from apps.blockchain.models import BlockchainArchive
            archive = BlockchainArchive.objects.get(election=election)
            if archive.account_closed_at is not None:
                logger.info("Election %s already archived — skipping", election.election_uuid)
                return
        except Exception:
            pass

        svc.archive_and_close(election)
        logger.info("archive_and_close_election completed for election %s", election.election_uuid)

    except Exception as exc:
        logger.exception("archive_and_close_election failed for election_id=%s", election_id)
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))


@shared_task(ignore_result=True)
def trigger_archive_ended_elections():
    """Periodic: find ended elections without archives and queue closure tasks."""
    try:
        from django.utils import timezone
        from apps.elections.models import Election

        now = timezone.now()
        ended = (
            Election.objects.filter(
                is_launched=True,
                end_time__lt=now,
                blockchain_contract_address__isnull=False,
            )
            .exclude(blockchain_contract_address="")
            .exclude(blockchain_archive__account_closed_at__isnull=False)
        )

        for election in ended:
            archive_and_close_election.delay(election.pk)  # type: ignore[attr-defined]
            logger.info("Queued archive_and_close_election for election %s", election.election_uuid)

    except Exception:
        logger.exception("trigger_archive_ended_elections task failed")


@shared_task(bind=True, ignore_result=True, max_retries=5)
def confirm_pending_transactions(self):
    """Poll Solana for confirmation of PENDING BlockchainTransaction rows.

    B-03 fix: batch size default raised to 500 (was 50).
    N-11 fix: retries transient errors instead of silently swallowing them.
    """
    from django.utils import timezone
    from apps.blockchain.models import BlockchainTransaction
    from apps.blockchain.services.solana_client import SolanaClient
    from apps.voting.models import Vote

    try:
        client = SolanaClient()
    except Exception as exc:
        logger.exception("confirm_pending_transactions: cannot connect to Solana RPC")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

    batch_size = getattr(settings, "SOLANA_TX_CONFIRM_BATCH_SIZE", 500)
    pending = BlockchainTransaction.objects.filter(
        status=BlockchainTransaction.Status.PENDING
    ).order_by("created_at")[:batch_size]

    errors = 0
    for tx in pending:
        try:
            status = client.get_signature_status(tx.tx_signature)
            if status is None:
                continue

            if status.err is None and status.confirmation_status is not None:
                tx.slot = status.slot
                tx.status = BlockchainTransaction.Status.CONFIRMED
                tx.confirmed_at = timezone.now()
                tx.save(update_fields=["slot", "status", "confirmed_at"])

                if tx.tx_type == BlockchainTransaction.TxType.CAST_VOTE:
                    Vote.objects.filter(
                        election=tx.election,
                        blockchain_tx_hash=tx.tx_signature,
                    ).update(blockchain_confirmed=True)

                logger.info("TX confirmed: %s at slot %s", tx.tx_signature[:16], tx.slot)

                # SSE: push blockchain confirmation
                try:
                    from apps.elections.event_emitter import emit_event
                    emit_event(tx.election.election_uuid, 'blockchain_update', {
                        'tx_hash': tx.tx_signature[:16],
                        'status': 'confirmed',
                        'slot': tx.slot,
                        'tx_type': tx.tx_type,
                    })
                except Exception:
                    logger.debug("SSE emit failed for blockchain_update", exc_info=True)

            elif status.err is not None:
                tx.status = BlockchainTransaction.Status.FAILED
                tx.error_message = str(status.err)
                tx.save(update_fields=["status", "error_message"])
                logger.warning("TX failed: %s — %s", tx.tx_signature[:16], status.err)

        except Exception:
            errors += 1
            logger.exception("Failed to check TX %s", tx.tx_signature[:16])

    # If more than half the batch errored, retry the entire task
    if errors > 0 and errors >= len(pending) // 2:
        logger.warning(
            "confirm_pending_transactions: %d/%d errors — scheduling retry",
            errors, len(pending),
        )
        raise self.retry(countdown=30 * (2 ** self.request.retries))
