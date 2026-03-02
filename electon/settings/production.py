"""
ElectON v2 — Production settings.

CF-16: This module deliberately uses ``os.environ`` (not ``decouple.config``)
because the production deployment (Docker / systemd) injects secrets as real
environment variables.  ``base.py`` uses ``decouple.config()`` for local-dev
convenience (.env file support).  Both patterns are standard; the split is
intentional.
"""
import os

import dj_database_url

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

# ─── Debug ────────────────────────────────────────────────────────
DEBUG = False

# ─── Secret Key (MUST come from environment) ─────────────────────
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY environment variable must be set in production.')

# ─── Allowed Hosts ───────────────────────────────────────────────
ALLOWED_HOSTS = [h for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS env variable must be set in production.')

# ─── Database (PostgreSQL via DATABASE_URL) ──────────────────────
if not os.environ.get('DATABASE_URL'):
    raise ImproperlyConfigured('DATABASE_URL environment variable must be set in production.')

DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# ─── Cache (Redis) ──────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

# ─── Session (Redis-backed in production) ────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# ─── Email (smart routing: Brevo 300/day → Azure overflow) ─────────
# Set EMAIL_BACKEND to the routing backend which reads BREVO_API_KEY and
# AZURE_COMM_CONNECTION_STRING to decide which provider to use per-message.
EMAIL_BACKEND = 'apps.notifications.backends.router.ElectONRoutingBackend'
# SMTP is kept as a last-resort fallback if NEITHER provider is configured
EMAIL_PROVIDER_FALLBACK_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# ─── CORS ────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [os.environ.get('SITE_URL', 'https://electon.app')]

# ─── CSRF Trusted Origins ────────────────────────────────────────
_CSRF_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', os.environ.get('SITE_URL', 'https://electon.app'))
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _CSRF_ORIGINS.split(',') if o.strip()]

# ─── Proxy Configuration ─────────────────────────────────────
NUM_PROXIES = int(os.environ.get('NUM_PROXIES', 1))

# ─── Vote Anonymization Salt Validation ──────────────────────
if VOTE_ANONYMIZATION_SALT == 'change-this-in-production':  # noqa: F405
    raise ImproperlyConfigured('VOTE_ANONYMIZATION_SALT must be set in production.')

# ─── SSL / HTTPS ─────────────────────────────────────────────────
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ─── Solana Blockchain (Production) ──────────────────────────────
# CF-14: All Solana settings are env-var-driven for devnet/mainnet flexibility.
SOLANA_NETWORK = os.environ.get('SOLANA_NETWORK', 'mainnet-beta')

_SOLANA_RPC_URL = os.environ.get('SOLANA_RPC_URL', '')
if not _SOLANA_RPC_URL:
    raise ImproperlyConfigured(
        'SOLANA_RPC_URL must be set in production. '
        'Public RPC endpoints are rate-limited — use a paid provider '
        '(Helius, Triton, QuickNode).'
    )
SOLANA_RPC_URL = _SOLANA_RPC_URL

SOLANA_EXPLORER_URL = os.environ.get('SOLANA_EXPLORER_URL', 'https://explorer.solana.com')

# Commitment: "finalized" on mainnet for full security; "confirmed" on devnet for speed.
_SOLANA_COMMITMENT_DEFAULT = 'finalized' if SOLANA_NETWORK == 'mainnet-beta' else 'confirmed'
SOLANA_COMMITMENT = os.environ.get('SOLANA_COMMITMENT', _SOLANA_COMMITMENT_DEFAULT)

# S-06: Validate required Solana credentials at startup
_SOLANA_PRIVATE_KEY = os.environ.get('SOLANA_PRIVATE_KEY', '')
if not _SOLANA_PRIVATE_KEY:
    raise ImproperlyConfigured(
        'SOLANA_PRIVATE_KEY environment variable must be set in production. '
        'Set it to the hex-encoded 64-byte ed25519 keypair (128 hex characters).'
    )

_SOLANA_PROGRAM_ID = os.environ.get('SOLANA_PROGRAM_ID', '')
if not _SOLANA_PROGRAM_ID:
    raise ImproperlyConfigured(
        'SOLANA_PROGRAM_ID environment variable must be set in production. '
        'Set it to the deployed Anchor program ID (base58).'
    )

# ─── Sentry ──────────────────────────────────────────────────────
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN and sentry_sdk:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
    )

# ─── Logging (reduce verbosity in prod) ─────────────────────────
LOGGING['loggers']['electon']['level'] = 'WARNING'  # noqa: F405
LOGGING['loggers']['django']['level'] = 'WARNING'  # noqa: F405

# ─── Cloud Media Storage (S3-compatible — Cloudflare R2) ─────────
# STORAGES['default'] is configured in base.py whenever R2_* env vars are set.
# This block extends CSP directives so the browser can load/upload R2 assets.
_R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '')
_R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY_ID', '')

if _R2_ACCESS_KEY and _R2_ACCOUNT_ID:
    _R2_ENDPOINT = f'https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
    _csp = CONTENT_SECURITY_POLICY['DIRECTIVES']  # noqa: F405
    # Allow direct pre-signed PUT uploads to R2 from the browser (production only)
    _csp['connect-src'] = _csp.get('connect-src', ("'self'",)) + (_R2_ENDPOINT,)
else:
    import warnings
    warnings.warn(
        'R2 storage not configured (R2_ACCESS_KEY_ID / R2_ACCOUNT_ID missing). '
        'Candidate images will fall back to local storage and will NOT persist.',
        stacklevel=1,
    )
