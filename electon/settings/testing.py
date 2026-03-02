"""
ElectON v2 — Testing settings.
"""
from .base import *  # noqa: F401, F403

# ─── Debug ────────────────────────────────────────────────────────
DEBUG = False

# ─── Secret Key ──────────────────────────────────────────────────
SECRET_KEY = 'test-secret-key-for-automated-tests-only'

# ─── Allowed Hosts ───────────────────────────────────────────────
ALLOWED_HOSTS = ['*']

# ─── Database (in-memory SQLite for speed) ───────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# ─── Cache (in-memory for tests) ────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# ─── Email (in-memory) ──────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# ─── Password Hashing (fast for tests) ──────────────────────────
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# ─── Solana Blockchain (mock in tests) ───────────────────────────
SOLANA_RPC_URL = 'http://localhost:8899'
SOLANA_PROGRAM_ID = '11111111111111111111111111111111'
SOLANA_NETWORK = 'devnet'

# ─── Disable Logging Noise ──────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'handlers': {
        'null': {'class': 'logging.NullHandler'},
    },
    'root': {
        'handlers': ['null'],
        'level': 'CRITICAL',
    },
}
