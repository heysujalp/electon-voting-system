"""Management command — verify the Solana program is deployed and reachable.

The actual program deployment is handled by ``anchor deploy``.
This command validates the on-chain program account.

D-02 fix: renamed from ``deploy_factory`` to ``verify_program`` to accurately
describe what the command actually does (validation, not deployment).

Usage::

    python manage.py verify_program
    python manage.py verify_program --program-id <base58>
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Verify that the Solana program is deployed and reachable on the "
        "configured network. Does NOT deploy the program — use `anchor deploy` "
        "for that."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--program-id",
            type=str,
            default=getattr(settings, "SOLANA_PROGRAM_ID", ""),
            help="Solana program ID (base58). Defaults to SOLANA_PROGRAM_ID setting.",
        )

    def handle(self, *args, **options):
        program_id = options["program_id"]
        if not program_id:
            raise CommandError(
                "No program ID provided. Set SOLANA_PROGRAM_ID in .env "
                "or pass --program-id."
            )

        network = getattr(settings, "SOLANA_NETWORK", "devnet")
        rpc_url = getattr(settings, "SOLANA_RPC_URL", "")
        commitment = getattr(settings, "SOLANA_COMMITMENT", "confirmed")
        self.stdout.write(f"Checking program {program_id} on {network} (commitment={commitment})...")
        self.stdout.write(f"RPC: {rpc_url}")

        from apps.blockchain.services.solana_client import SolanaClient

        client = SolanaClient()

        try:
            from solders.pubkey import Pubkey  # type: ignore

            pubkey = Pubkey.from_string(program_id)
            info = client.get_account_info(pubkey)
        except Exception as exc:
            raise CommandError(f"Failed to query program account: {exc}")

        if info is None:
            raise CommandError(
                f"Program account {program_id} not found on {network}. "
                "Please deploy the program with `anchor deploy` first."
            )

        # GetAccountInfoResp.value is Account | None
        account = info.value  # type: ignore[union-attr]
        if account is None:
            raise CommandError(
                f"Program account {program_id} not found on {network}. "
                "Please deploy the program with `anchor deploy` first."
            )

        owner      = getattr(account, "owner",      "n/a")
        executable = getattr(account, "executable", "n/a")
        lamports   = getattr(account, "lamports",   "n/a")
        self.stdout.write(
            self.style.SUCCESS(
                f"\nProgram verified!\n"
                f"  Program ID: {program_id}\n"
                f"  Network:    {network}\n"
                f"  Owner:      {owner}\n"
                f"  Executable: {executable}\n"
                f"  Lamports:   {lamports}"
            )
        )
