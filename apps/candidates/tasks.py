"""ElectON v2 — Candidate background tasks.

Uses Celery @shared_task when available; falls back to synchronous
execution if Celery is not installed.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger("electon.candidates")

# Graceful Celery integration
try:
    from celery import shared_task
except ImportError:
    def shared_task(func=None, **kwargs):  # noqa: ARG001
        if func is not None:
            func.delay = lambda *a, **kw: func(*a, **kw)
            func.apply_async = lambda args=(), kwargs=None, **_: func(*args, **(kwargs or {}))
            return func
        def wrapper(fn):
            fn.delay = lambda *a, **kw: fn(*a, **kw)
            fn.apply_async = lambda args=(), kwargs=None, **_: fn(*args, **(kwargs or {}))
            return fn
        return wrapper


@shared_task(ignore_result=True)
def cleanup_orphaned_candidate_images():
    """Remove candidate images in R2 that are no longer referenced by any
    Candidate row.  Only considers objects older than 1 hour to avoid
    deleting files mid-upload.

    Runs **daily** at 3 AM via Celery Beat (see ``base.py`` CELERY_BEAT_SCHEDULE).
    Each invocation triggers 1 LIST (Class A) + N DELETE (Class A) ops.
    """
    from django.core.files.storage import storages

    storage = storages['default']

    # Check if R2 (S3Boto3Storage) is configured
    backend_name = type(storage).__name__
    if backend_name != 'S3Boto3Storage':
        logger.debug("Skipping orphan cleanup — storage is %s, not R2.", backend_name)
        return

    from .models import Candidate

    # Collect all image paths currently referenced in the DB
    referenced = set(
        Candidate.objects.exclude(image='')
        .exclude(image__isnull=True)
        .values_list('image', flat=True)
    )

    # List all objects under the candidates/ prefix
    client = storage.connection.meta.client
    bucket = storage.bucket_name
    cutoff = timezone.now() - timedelta(hours=1)
    deleted = 0

    paginator = client.get_paginator('list_objects_v2')
    logger.info("R2 LIST [Class-A]: listing prefix=candidates/ in bucket=%s", bucket)
    for page in paginator.paginate(Bucket=bucket, Prefix='candidates/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            last_modified = obj.get('LastModified')

            # Skip recently uploaded objects (might still be in-flight)
            if last_modified and last_modified >= cutoff:
                continue

            if key not in referenced:
                try:
                    logger.info("R2 DELETE [Class-A]: orphan %s", key)
                    client.delete_object(Bucket=bucket, Key=key)
                    deleted += 1
                except Exception:
                    logger.warning("Failed to delete orphan: %s", key, exc_info=True)

    if deleted:
        logger.info("Cleaned up %d orphaned candidate image(s).", deleted)
