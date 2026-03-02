"""
Management command to sync pending Solana transactions.
Checks for transactions still in 'pending' status and updates them.

Usage:
    python manage.py sync_blockchain
    python manage.py sync_blockchain --max-age 3600
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger("electon.blockchain")


class Command(BaseCommand):
    help = "Sync pending Solana transactions — confirm or mark failed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age",
            type=int,
            default=3600,
            help="Max age in seconds for pending TX before marking failed (default 3600).",
        )

    def handle(self, *args, **options):
        from apps.blockchain.models import BlockchainTransaction
        from apps.blockchain.services.solana_client import SolanaClient

        client = SolanaClient()
        max_age = options["max_age"]
        cutoff = timezone.now() - timedelta(seconds=max_age)

        pending = BlockchainTransaction.objects.filter(status="pending")
        total = pending.count()
        confirmed = 0
        failed = 0
        still_pending = 0

        self.stdout.write(f"Found {total} pending transactions.")

        for tx in pending.iterator():
            try:
                status = client.get_signature_status(tx.tx_signature)

                if status is not None and status.err is None and status.confirmation_status is not None:
                    tx.status = "confirmed"
                    tx.slot = status.slot
                    tx.confirmed_at = timezone.now()
                    tx.save(update_fields=["status", "slot", "confirmed_at"])
                    confirmed += 1
                elif status is not None and status.err is not None:
                    tx.status = "failed"
                    tx.error_message = str(status.err)[:500]
                    tx.save(update_fields=["status", "error_message"])
                    failed += 1
                else:
                    # Still pending — mark failed if too old
                    if tx.created_at < cutoff:
                        tx.status = "failed"
                        tx.error_message = f"Timed out after {max_age}s."
                        tx.save(update_fields=["status", "error_message"])
                        failed += 1
                    else:
                        still_pending += 1
            except Exception as exc:
                logger.warning("Error syncing TX %s: %s", tx.tx_signature[:16], exc)
                if tx.created_at < cutoff:
                    tx.status = "failed"
                    tx.error_message = str(exc)[:500]
                    tx.save(update_fields=["status", "error_message"])
                    failed += 1
                else:
                    still_pending += 1

        self.stdout.write(self.style.SUCCESS(
            f"Sync complete: {confirmed} confirmed, {failed} failed, "
            f"{still_pending} still pending."
        ))
