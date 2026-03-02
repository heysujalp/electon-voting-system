"""
ElectON v2 — Celery application configuration.

This module creates and configures the Celery app instance used by
``celery -A electon worker`` and ``celery -A electon beat``.

It MUST be imported early — ``electon/__init__.py`` does this via:
    from .celery import app as celery_app
"""
import os

from celery import Celery

# Default to development settings; production Docker overrides via env var.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "electon.settings.development")

app = Celery("electon")

# Read Celery config from Django settings, using the ``CELERY_`` namespace.
# e.g. CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_BEAT_SCHEDULE, etc.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all INSTALLED_APPS (looks for ``tasks.py`` modules).
app.autodiscover_tasks()
