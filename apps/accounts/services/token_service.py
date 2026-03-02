"""
ElectON v2 — Token Service.
Single source of truth for all token & OTP code generation and verification.
"""
import hashlib
import hmac
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


class TokenService:
    """Generates and verifies all tokens and OTP codes in the system."""

    @staticmethod
    def generate_verification_code(length: int = 6) -> tuple[str, str]:
        """
        Generate a numeric OTP code.

        Returns:
            (plaintext_code, hashed_code)
        """
        code = ''.join(secrets.choice(string.digits) for _ in range(length))
        code_hash = TokenService._hash_value(code)
        return code, code_hash

    @staticmethod
    def generate_secure_token(purpose: str = 'general') -> tuple[str, str]:
        """
        Generate a URL-safe token for links (verification, password reset, etc.).

        Returns:
            (raw_token, token_hash)
        """
        raw_token = secrets.token_urlsafe(48)
        token_hash = TokenService._hash_value(raw_token)
        return raw_token, token_hash

    @staticmethod
    def verify_code(plaintext_code: str, stored_hash: str) -> bool:
        """Verify a code against its stored hash."""
        return hmac.compare_digest(
            TokenService._hash_value(plaintext_code),
            stored_hash,
        )

    @staticmethod
    def verify_token(raw_token: str, stored_hash: str) -> bool:
        """Verify a token against its stored hash."""
        return hmac.compare_digest(
            TokenService._hash_value(raw_token),
            stored_hash,
        )

    @staticmethod
    def generate_password(length: int = 16) -> str:
        """
        Generate a strong random password.
        Used for voter credentials and anywhere a random password is needed.
        Guaranteed to have at least one uppercase, lowercase, digit, and special char.
        """
        special_chars = '!@#$%^&*'
        alphabet = string.ascii_letters + string.digits + special_chars

        while True:
            password = ''.join(secrets.choice(alphabet) for _ in range(length))
            if (
                any(c.isupper() for c in password)
                and any(c.islower() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in special_chars for c in password)
            ):
                return password

    @staticmethod
    def generate_session_id() -> str:
        """Generate a unique session ID for verification sessions."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def get_expiry(seconds: int):
        """Return a timezone-aware datetime `seconds` from now."""
        return timezone.now() + timedelta(seconds=seconds)

    @staticmethod
    def _hash_value(value: str) -> str:
        """Create a SHA-256 hash with a dedicated stable salt.

        Uses TOKEN_HASH_SALT if available, falling back to SECRET_KEY.
        A dedicated salt prevents token invalidation on SECRET_KEY rotation.

        Suitable for high-entropy values (tokens, codes). For low-entropy
        values (security answers), use ``_hash_answer`` instead.
        """
        salt = getattr(settings, 'TOKEN_HASH_SALT', None) or getattr(settings, 'SECRET_KEY', 'fallback-salt')
        return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()

    @staticmethod
    def _hash_answer(value: str, salt: str | None = None) -> str:
        """Hash a low-entropy value (security answer) with PBKDF2.

        Uses 600_000 iterations of SHA-256 to resist offline brute-force.
        A random per-hash salt is generated if not supplied, preventing
        rainbow-table and cross-user correlation attacks.

        The returned string format is ``pbkdf2$<salt_hex>$<dk_hex>`` which
        stores the unique salt alongside the derived key.
        """
        if salt is None:
            salt = secrets.token_hex(16)  # 16 random bytes → 32 hex chars
        dk = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600_000)
        return f"pbkdf2${salt}${dk.hex()}"

    @staticmethod
    def verify_answer(value: str, stored_hash: str) -> bool:
        """Verify a plaintext answer against a stored PBKDF2 hash.

        Supports three formats:
        - New per-salt:  ``pbkdf2$<salt>$<dk>``
        - Legacy PBKDF2: ``pbkdf2$<dk>``  (global salt)
        - Legacy SHA-256: plain hex
        """
        import hmac as _hmac
        normalised = value.strip().lower()

        if stored_hash.startswith('pbkdf2$'):
            parts = stored_hash.split('$', 2)
            if len(parts) == 3:
                # New format: pbkdf2$<salt>$<dk>
                _, salt, _ = parts
                candidate = TokenService._hash_answer(normalised, salt=salt)
                return _hmac.compare_digest(candidate, stored_hash)
            else:
                # Legacy PBKDF2 (global salt): pbkdf2$<dk>
                global_salt = getattr(settings, 'TOKEN_HASH_SALT', None) or getattr(settings, 'SECRET_KEY', 'fallback-salt')
                dk = hashlib.pbkdf2_hmac('sha256', normalised.encode(), global_salt.encode(), 600_000)
                legacy_hash = f"pbkdf2${dk.hex()}"
                return _hmac.compare_digest(legacy_hash, stored_hash)

        # Legacy SHA-256 hash
        return _hmac.compare_digest(
            TokenService._hash_value(normalised),
            stored_hash,
        )
