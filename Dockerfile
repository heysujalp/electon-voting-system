# ─── ElectON v2 — Docker Build ──────────────────────────────────
# Multi-stage build: builder → runtime (slim)
# Usage:
#   docker build -t electon .
#   docker compose up -d

# ─── Stage 1: Builder ───────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# System deps for psycopg2, Pillow, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libjpeg62-turbo-dev zlib1g-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ─── Stage 2: Runtime ───────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=electon.settings.production

# Runtime-only system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libjpeg62-turbo curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r electon && useradd -r -g electon -d /app -s /sbin/nologin electon

WORKDIR /app

# Install Python deps from pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY . .

# Collect static files (uses whitenoise) — dummy SECRET_KEY for build
RUN SECRET_KEY=build-placeholder DJANGO_ENV=production python manage.py collectstatic --noinput

# Create directories for logs and media
RUN mkdir -p /app/logs /app/media && chown -R electon:electon /app

USER electon

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

# Gunicorn with recommended production settings
CMD ["gunicorn", "electon.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--worker-class", "gthread", \
     "--threads", "4", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
