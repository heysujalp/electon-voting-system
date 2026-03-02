"""
ElectON v2 — Base settings (shared across all environments).
"""
from pathlib import Path

from decouple import config, Csv
from django.core.exceptions import ImproperlyConfigured

# ─── Paths ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Installed Apps ──────────────────────────────────────────────
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'corsheaders',
    'csp',
    'django_celery_beat',
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.elections',
    'apps.candidates',
    'apps.voting',
    'apps.results',
    'apps.notifications',
    'apps.blockchain',
    'apps.audit',
    'apps.api',
    'apps.subscriptions',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ───────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'csp.middleware.CSPMiddleware',
    'apps.audit.middleware.AuditMiddleware',
    # LOW-03: SessionCleanupMiddleware removed — use 'manage.py clearsessions' via cron/Celery beat
]

# ─── URL Configuration ───────────────────────────────────────────
ROOT_URLCONF = 'electon.urls'

# ─── Templates ────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ─── WSGI / ASGI ──────────────────────────────────────────────────
WSGI_APPLICATION = 'electon.wsgi.application'
ASGI_APPLICATION = 'electon.asgi.application'

# ─── Auth ──────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.CustomUser'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/elections/manage/'
LOGOUT_REDIRECT_URL = '/'

# ─── Password Validation ──────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Internationalization ─────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ─── Static Files ─────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ─── Media Files ──────────────────────────────────────────────────
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── Storage — staticfiles + default media ─────────────────────────────────
# R2 (Cloudflare) is used in ALL environments when credentials are present.
# Falls back to local FileSystemStorage when R2 vars are absent.

def _strip_r2_scheme(url: str) -> str:
    """Return bare domain from a URL (strips https:// prefix if present)."""
    if '://' in url:
        return url.split('://', 1)[1].rstrip('/')
    return url.strip().rstrip('/')


_r2_key    = config('R2_ACCESS_KEY_ID',     default='')
_r2_bucket = config('R2_BUCKET_NAME',       default='')
_r2_acct   = config('R2_ACCOUNT_ID',        default='')
_r2_secret = config('R2_SECRET_ACCESS_KEY', default='')
_r2_public = _strip_r2_scheme(config('R2_PUBLIC_URL', default=''))  # bare domain

if _r2_key and _r2_bucket and _r2_acct:
    STORAGES = {
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
            'OPTIONS': {
                'access_key':        _r2_key,
                'secret_key':        _r2_secret,
                'bucket_name':       _r2_bucket,
                'endpoint_url':      f'https://{_r2_acct}.r2.cloudflarestorage.com',
                'custom_domain':     _r2_public or None,
                'default_acl':       None,          # R2 does not use ACL
                'file_overwrite':    True,          # UUIDs guarantee uniqueness; skip HEAD check
                'object_parameters': {'CacheControl': 'public, max-age=2592000'},
                'signature_version': 's3v4',
                'region_name':       'auto',
            },
        },
    }
else:
    STORAGES = {
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
    }

# ─── Default Auto Field ──────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Session Configuration ────────────────────────────────────────
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# ─── CSRF Configuration ──────────────────────────────────────────
CSRF_COOKIE_HTTPONLY = False  # Must be False so JS can read CSRF token for AJAX
CSRF_COOKIE_SAMESITE = 'Lax'

# ─── Security Headers ────────────────────────────────────────────
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
# SECURE_BROWSER_XSS_FILTER removed — X-XSS-Protection is deprecated by
# modern browsers and can introduce vulnerabilities. CSP provides XSS protection.

# ─── Content Security Policy ─────────────────────────────────────
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': ("'self'",),
        'script-src': ("'self'", "https://cdn.jsdelivr.net"),
        'style-src': ("'self'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"),
        'font-src': ("'self'", "https://cdnjs.cloudflare.com"),
        'img-src': ("'self'", "data:", "blob:", "https://*.r2.dev"),
        'connect-src': ("'self'",),
        'frame-ancestors': ("'none'",),
        'object-src': ("'none'",),
        'base-uri': ("'self'",),
        'form-action': ("'self'",),
    }
}

# ─── REST Framework ──────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '120/minute',
        'vote_cast': '30/minute',
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}

# ─── CORS ─────────────────────────────────────────────────────────
# Always explicit — never CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# ─── ElectON Application Settings ────────────────────────────────
# NOTE: Limit values below (MAX_*) are FALLBACK ONLY.
# Runtime limit checks go through PlanLimitService which reads from
# SubscriptionPlan models.  These are used only if the subscriptions
# app has not yet been migrated or no Free plan exists.
SITE_URL = config('SITE_URL', default='http://localhost:8000')

ELECTON_SETTINGS = {
    'APP_NAME': 'ElectON',
    'SITE_URL': SITE_URL,
    # Limits (fallback — real limits come from SubscriptionPlan)
    'MAX_ELECTIONS_PER_USER': 50,
    'MAX_POSTS_PER_ELECTION': 20,
    'MAX_CANDIDATES_PER_POST': 50,
    'MAX_VOTERS_PER_ELECTION': 10000,
    'MAX_VOTERS_PER_IMPORT': 500,
    # Non-limit settings (remain authoritative)
    'MAX_UPLOAD_SIZE': 5 * 1024 * 1024,  # 5MB — single source of truth
    'ALLOWED_IMAGE_TYPES': ['image/jpeg', 'image/png', 'image/webp'],
    'ALLOWED_IMAGE_EXTENSIONS': ['.jpg', '.jpeg', '.png', '.webp'],
    'MAX_IMAGE_DIMENSION': 400,
    'CANDIDATE_IMAGE_QUALITY': 78,
}

# Match Django's DATA_UPLOAD_MAX_MEMORY_SIZE to our MAX_UPLOAD_SIZE (5 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SECURITY_SETTINGS = {
    'VERIFICATION_CODE_LENGTH': 6,
    'VERIFICATION_CODE_EXPIRY': 900,  # 15 minutes
    'PASSWORD_RESET_EXPIRY': 3600,  # 1 hour
    'ADMIN_VERIFICATION_TRIGGER': 10,  # Failed attempts before 2FA
    'ADMIN_VERIFICATION_WINDOW': 3600,  # 1 hour window for failures
    'SESSION_CLEANUP_INTERVAL': 3600,  # 1 hour
}

# ─── Token Hashing Salt (stable across SECRET_KEY rotations) ────
TOKEN_HASH_SALT = config('TOKEN_HASH_SALT', default='')
if not TOKEN_HASH_SALT and config('DJANGO_ENV', default='development') == 'production':
    raise ImproperlyConfigured('TOKEN_HASH_SALT must be set in production.')

# ─── Vote Anonymization ──────────────────────────────────────────
VOTE_ANONYMIZATION_SALT = config('VOTE_ANONYMIZATION_SALT', default='change-this-in-production')

# ─── Solana Blockchain ───────────────────────────────────────────
SOLANA_NETWORK = config('SOLANA_NETWORK', default='devnet')  # devnet | mainnet-beta
SOLANA_RPC_URL = config('SOLANA_RPC_URL', default='https://api.devnet.solana.com')
SOLANA_PRIVATE_KEY = config('SOLANA_PRIVATE_KEY', default='')  # hex-encoded keypair
SOLANA_PROGRAM_ID = config('SOLANA_PROGRAM_ID', default='')
SOLANA_EXPLORER_URL = config(
    'SOLANA_EXPLORER_URL',
    default='https://explorer.solana.com',
)
SOLANA_TX_CONFIRM_BATCH_SIZE = config('SOLANA_TX_CONFIRM_BATCH_SIZE', default=500, cast=int)  # B-03 fix: was 50
# Commitment level: "confirmed" (fast, fine for devnet) or "finalized" (slower, safer for mainnet).
# Auto-resolved from SOLANA_NETWORK when not explicitly set.
_SOLANA_COMMITMENT_DEFAULT = 'finalized' if SOLANA_NETWORK == 'mainnet-beta' else 'confirmed'
SOLANA_COMMITMENT = config('SOLANA_COMMITMENT', default=_SOLANA_COMMITMENT_DEFAULT)

# ─── Email (SMTP — credentials come from .env) ───────────────────
EMAIL_SUBJECT_PREFIX = '[ElectON] '
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@electon.app')
EMAIL_HOST          = config('EMAIL_HOST',          default='smtp.gmail.com')
EMAIL_PORT          = config('EMAIL_PORT',          default=587, cast=int)
EMAIL_HOST_USER     = config('EMAIL_HOST_USER',     default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS       = config('EMAIL_USE_TLS',       default=True,  cast=bool)
EMAIL_USE_SSL       = config('EMAIL_USE_SSL',       default=False, cast=bool)

# ─── Email Provider: Brevo (optional) ─────────────────────────────
# First 300 emails/day go through Brevo (free transactional tier).
# If BREVO_API_KEY is not set, ALL emails go through Azure.
BREVO_API_KEY     = config('BREVO_API_KEY',     default='')
BREVO_SENDER_NAME = config('BREVO_SENDER_NAME', default='ElectON')
BREVO_DAILY_LIMIT = config('BREVO_DAILY_LIMIT', default=300, cast=int)

# ─── Email Provider: Azure Communication Services (fallback/primary) ─
# Required when BREVO_API_KEY is not set OR Brevo daily limit is reached.
# pip install azure-communication-email>=1.0,<2.0 to activate.
AZURE_COMM_CONNECTION_STRING = config('AZURE_COMM_CONNECTION_STRING', default='')
AZURE_COMM_SENDER_ADDRESS    = config('AZURE_COMM_SENDER_ADDRESS',    default='')

# ─── Logging ─────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / 'logs'
try:
    LOG_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # Skip in read-only containers (e.g., collectstatic)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'electon.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'security_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'security.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'electon': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'electon.security': {
            'handlers': ['console', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ─── Celery Configuration ────────────────────────────────────────
# Broker and result backend — Redis in production; overridable via env.
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# ─── Celery Beat Periodic Tasks ──────────────────────────────────
# Run `celery -A electon beat -l info` to activate these schedules.
try:
    from celery.schedules import crontab  # noqa: E402

    CELERY_BEAT_SCHEDULE = {
        # Confirm pending Solana transactions every 30 seconds
        "confirm-pending-solana-txs": {
            "task": "apps.blockchain.tasks.confirm_pending_transactions",
            "schedule": 30.0,
        },
        # Check for ended elections and archive + close their Solana accounts
        "trigger-archive-closed-elections": {
            "task": "apps.blockchain.tasks.trigger_archive_ended_elections",
            "schedule": crontab(minute="*/5"),
        },
        # Clean up orphaned candidate images uploaded via pre-signed URLs but never confirmed
        "cleanup-orphaned-candidate-images": {
            "task": "apps.candidates.tasks.cleanup_orphaned_candidate_images",
            "schedule": crontab(hour=3, minute=0),  # daily at 3 AM (saves ~23 LIST ops/day)
        },
    }
except ImportError:
    pass  # Celery not installed (e.g., CI or minimal dev setup)

# ─── SSE (Server-Sent Events) Configuration ─────────────────────
SSE_HEARTBEAT_INTERVAL = 25   # seconds between keepalive comments
SSE_MAX_CONNECTION_TIME = 3600  # max stream duration (1 hour); client auto-reconnects
