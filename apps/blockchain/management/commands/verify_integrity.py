"""
Management command to verify data integrity between the database and Solana.
Compares vote counts for all deployed elections.

Usage:
    python manage.py verify_integrity
    python manage.py verify_integrity --election <uuid>
"""

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger("electon.blockchain")


class Command(BaseCommand):
    help = "Compare DB vote counts against on-chain Solana data for deployed elections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--election",
            type=str,
            default=None,
            help="Specific election UUID to verify. If omitted, verifies all.",
        )

    def handle(self, *args, **options):
        from apps.blockchain.models import ContractDeployment
        from apps.blockchain.services.verification_service import VerificationService

        svc = VerificationService()
        election_uuid = options.get("election")

        if election_uuid:
            deployments = ContractDeployment.objects.filter(
                election__election_uuid=election_uuid
            ).select_related("election")
        else:
            deployments = ContractDeployment.objects.select_related("election").all()

        if not deployments.exists():
            self.stdout.write(self.style.WARNING("No Solana-deployed elections found."))
            return

        total = 0
        mismatches = 0

        for deployment in deployments.iterator():
            election = deployment.election
            total += 1
            self.stdout.write(f"\nVerifying: {election.name} ({election.election_uuid})")

            result = svc.compare_db_and_chain(election)

            if result["error"]:
                self.stdout.write(self.style.ERROR(f"  Error: {result['error']}"))
                mismatches += 1
                continue

            self.stdout.write(
                f"  DB votes: {result['total_votes_db']}  "
                f"Chain votes: {result['total_votes_chain']}"
            )

            if result["match"]:
                self.stdout.write(self.style.SUCCESS("  \u2713 All counts match."))
            else:
                mismatches += 1
                self.stdout.write(self.style.ERROR("  \u2717 MISMATCH DETECTED:"))
                for post in result["posts"]:
                    for cand in post["candidates"]:
                        if not cand["match"]:
                            self.stdout.write(self.style.ERROR(
                                f"    Post '{post['post_name']}' \u2192 "
                                f"'{cand['candidate_name']}': "
                                f"DB={cand['db_count']}, Chain={cand['chain_count']}"
                            ))

        self.stdout.write(f"\n{'=' * 50}")
        if mismatches == 0:
            self.stdout.write(self.style.SUCCESS(
                f"All {total} elections verified \u2014 no discrepancies."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{mismatches}/{total} elections have discrepancies!"
            ))
