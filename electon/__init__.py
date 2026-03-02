"""ElectON v2 — Django project package."""

# Ensure the Celery app is always imported when Django starts, so that
# @shared_task decorators use this app instance.
from .celery import app as celery_app  # noqa: F401

__all__ = ("celery_app",)
