"""
ElectON v2 — Development settings.
"""
from .base import *  # noqa: F401, F403

# ─── Debug ────────────────────────────────────────────────────────
DEBUG = True

# ─── Secret Key (fixed in dev — never regenerated) ───────────────
SECRET_KEY = 'dev-secret-key-DO-NOT-USE-IN-PRODUCTION-change-me'

# ─── Allowed Hosts ───────────────────────────────────────────────
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

# ─── Database (PostgreSQL via DATABASE_URL from .env) ────────────────
import dj_database_url as _dj_db
DATABASES = {
    'default': _dj_db.parse(
        str(config('DATABASE_URL', cast=str)),  # noqa: F405 — config imported via base *
        conn_max_age=60,
        conn_health_checks=True,
    )
}

# ─── Cache (Redis — same as production) ────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://localhost:6379/0'),  # noqa: F405
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

# ─── Email Routing Backend ────────────────────────────────────────
# Always use the routing backend so the Brevo/Azure provider logic is
# active even in development.  The fallback is console (no SMTP config)
# or SMTP if EMAIL_HOST_USER is set in .env.
EMAIL_BACKEND = 'apps.notifications.backends.router.ElectONRoutingBackend'
EMAIL_PROVIDER_FALLBACK_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend'
    if EMAIL_HOST_USER  # noqa: F405
    else 'django.core.mail.backends.console.EmailBackend'
)

# ─── CORS (explicit localhost only) ──────────────────────────────
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# ─── Session (Redis-backed — same as production) ──────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# ─── Solana Blockchain ────────────────────────────────────────────
# SOLANA_* settings come from .env (localnet by default).
# base.py reads them via env(); do NOT override here.

# ─── Debug Toolbar (optional) ────────────────────────────────────
try:
    import debug_toolbar  # type: ignore[import-untyped]  # noqa: F401
    INSTALLED_APPS += ['debug_toolbar']  # noqa: F405
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')  # noqa: F405
    INTERNAL_IPS = ['127.0.0.1']
except ImportError:
    pass

# ─── Logging Override ────────────────────────────────────────────
LOGGING['loggers']['electon']['level'] = 'DEBUG'  # noqa: F405

# ─── R2 Operation Logging ─────────────────────────────────────────
# Monkey-patch S3Boto3Storage so every PUT, DELETE, HEAD, and LIST
# is printed to the console.  Lets you see exactly which R2 ops each
# request causes and verify that uploads use exactly 1 Class-A PUT.
import logging as _logging
_r2_log = _logging.getLogger('electon.r2')
try:
    from storages.backends.s3boto3 import S3Boto3Storage as _S3

    _S3_real_save    = _S3._save
    _S3_real_delete  = _S3.delete
    _S3_real_exists  = _S3.exists
    _S3_real_listdir = _S3.listdir

    def _r2_save(self, name, content):
        _r2_log.warning('\n  ⚡ R2 PUT  [Class-A]: %s', name)
        return _S3_real_save(self, name, content)

    def _r2_delete(self, name):
        _r2_log.warning('\n  ⚡ R2 DEL  [Class-A]: %s', name)
        return _S3_real_delete(self, name)

    def _r2_exists(self, name):
        _r2_log.warning('\n  ⚡ R2 HEAD [Class-B]: %s', name)
        return _S3_real_exists(self, name)

    def _r2_listdir(self, path):
        _r2_log.warning('\n  ⚡ R2 LIST [Class-A]: prefix=%s', path)
        return _S3_real_listdir(self, path)

    _S3._save   = _r2_save
    _S3.delete  = _r2_delete
    _S3.exists  = _r2_exists
    _S3.listdir = _r2_listdir
    _r2_log.info('R2 operation logging ACTIVE — every storage call will be printed.')
except ImportError:
    pass  # django-storages not installed
