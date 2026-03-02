"""
Solana RPC client wrapper.

Requires:
    pip install solana solders

Environment variables (via settings):
    SOLANA_RPC_URL   — Solana JSON-RPC endpoint
    SOLANA_PRIVATE_KEY — Hex-encoded ed25519 keypair (64 bytes)

Fixes:
    Q-01: Added retry with exponential backoff for transient RPC errors.
    Q-02: Added clear_payer_cache() classmethod for key invalidation.
    Q-03: Sync Client is still used for simple RPC calls (get_slot, etc.)
          but ProgramService manages AsyncClient separately — this is
          acceptable since they serve different purposes (sync helper calls
          vs. Anchor program interactions).
"""
import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger("electon.blockchain")

# Lazy imports — only resolved when actually used
_client = None
_client_lock = threading.Lock()  # BE-58: Thread-safe singleton

# Q-01: Retry configuration for transient RPC errors
_RPC_MAX_RETRIES = 3
_RPC_RETRY_BASE_DELAY = 1.0  # seconds


def _get_rpc_url() -> str:
    url = getattr(settings, "SOLANA_RPC_URL", "")
    if not url:
        raise ValueError(
            "SOLANA_RPC_URL is not configured. "
            "Set it in your .env or settings (e.g. https://api.devnet.solana.com)."
        )
    return url


class SolanaClient:
    """Low-level Solana RPC wrapper.  Lazy-initialises on first use."""

    _payer_cache = None  # Class-level cache (not module global)

    def __init__(self):
        global _client
        if _client is None:
            with _client_lock:  # BE-58: Double-checked locking
                if _client is None:
                    try:
                        from solana.rpc.api import Client
                    except ImportError as exc:
                        raise ImportError(
                            "The 'solana' package is required for blockchain features. "
                            "Install with:  pip install solana solders"
                        ) from exc

                    _client = Client(
                        _get_rpc_url(),
                        timeout=30,  # Prevent indefinite hangs on slow/dead RPC
                    )
                    logger.info("SolanaClient connected to %s", _get_rpc_url())

        self.client = _client
        self.payer = self._load_payer()

        # Read commitment level from settings (auto-resolved per network)
        self.commitment = getattr(settings, "SOLANA_COMMITMENT", "confirmed")

    # ── Key management ──

    @classmethod
    def _load_payer(cls):
        """Load the deployer/payer keypair from settings (class-level cache)."""
        if cls._payer_cache is not None:
            return cls._payer_cache

        from solders.keypair import Keypair  # type: ignore[import-untyped]

        pk_hex = getattr(settings, "SOLANA_PRIVATE_KEY", "")
        if not pk_hex:
            raise ValueError(
                "SOLANA_PRIVATE_KEY is not configured.  "
                "Set it to a hex-encoded 64-byte ed25519 keypair."
            )
        # BE-56: Validate key length before parsing
        if len(pk_hex) != 128:
            raise ValueError(
                f"SOLANA_PRIVATE_KEY must be exactly 128 hex characters "
                f"(64 bytes), got {len(pk_hex)}."
            )
        try:
            cls._payer_cache = Keypair.from_bytes(bytes.fromhex(pk_hex))
        except ValueError:
            # Sanitise: never include key material or raw exception details
            raise ValueError(
                "SOLANA_PRIVATE_KEY contains invalid hex characters. "
                "Ensure it is a valid 128-character hex string."
            )
        return cls._payer_cache

    @classmethod
    def clear_payer_cache(cls):
        """Q-02: Invalidate the cached keypair (e.g. after key rotation)."""
        cls._payer_cache = None

    # ── Transaction helpers ──

    def _retry_rpc(self, fn, *args, **kwargs):
        """Q-01: Retry RPC calls with exponential backoff on transient errors."""
        last_exc = None
        for attempt in range(_RPC_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                err_msg = str(exc).lower()
                # Only retry transient errors (connection, timeout, 429, 503)
                transient = any(kw in err_msg for kw in [
                    "timeout", "connection", "429", "503", "502",
                    "service unavailable", "too many requests",
                ])
                if not transient or attempt == _RPC_MAX_RETRIES - 1:
                    raise
                delay = _RPC_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "RPC transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _RPC_MAX_RETRIES, delay, exc,
                )
                time.sleep(delay)
        raise last_exc  # unreachable but makes type checkers happy

    def send_transaction(self, tx):
        """Sign and send a transaction.  Returns the signature string."""
        from solana.rpc.types import TxOpts

        tx.sign(self.payer)
        opts = TxOpts(skip_preflight=False, preflight_commitment=self.commitment)

        def _send():
            return self.client.send_transaction(tx, self.payer, opts=opts)

        result = self._retry_rpc(_send)
        sig = str(result.value)
        logger.info("Solana TX sent: %s", sig[:24])
        return sig

    def confirm_transaction(self, signature: str, commitment: str = None) -> bool:
        """Wait for a transaction to be confirmed.  Returns True on success."""
        if commitment is None:
            commitment = self.commitment
        result = self._retry_rpc(self.client.confirm_transaction, signature, commitment)
        # result.value is a list of RpcResponseAndContext; first entry's err field
        try:
            err = result.value[0].err
        except (IndexError, AttributeError, TypeError):
            err = None

        if err is not None:
            logger.warning("TX %s confirmation error: %s", signature[:24], err)
            return False
        return True

    def get_slot(self) -> int:
        """Return the current slot number at the configured commitment."""
        return self._retry_rpc(
            self.client.get_slot, commitment=self.commitment
        ).value

    def get_signature_status(self, signature: str):
        """Return the status of a single signature."""
        from solders.signature import Signature  # type: ignore[import-untyped]

        sig = Signature.from_string(signature)

        def _get():
            return self.client.get_signature_statuses([sig])

        resp = self._retry_rpc(_get)
        statuses = resp.value
        return statuses[0] if statuses else None

    # ── Account reads ──

    def get_account_info(self, pubkey):
        """Fetch raw account info for a given Pubkey."""
        return self._retry_rpc(
            self.client.get_account_info, pubkey, commitment=self.commitment
        )
