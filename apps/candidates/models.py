"""
ElectON v2 — Candidate model.

Represents candidates running for election posts. Includes image upload
with auto-resize, vote-count helpers, and image cleanup on delete.
"""
import io
import logging
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from PIL import Image

logger = logging.getLogger(__name__)

MAX_IMAGE_DIMENSION = 400  # pixels — client sends ≤400×400, server validates


def candidate_image_upload_path(instance, filename):
    """Generate upload path: candidates/<user_id>/<election_uuid>/<filename>."""
    user_id = instance.election.created_by_id
    election_uuid = instance.election.election_uuid
    return f'candidates/{user_id}/{election_uuid}/{filename}'


def prepare_candidate_image(file_or_bytes, *, max_dim=MAX_IMAGE_DIMENSION):
    """Resize + convert an image to WebP **in-memory**.

    Accepts a Django ``UploadedFile``, ``ContentFile``, ``BytesIO``, or any
    file-like object with a ``read()`` method.

    Returns a ``(ContentFile, '.webp')`` tuple ready for
    ``ImageField.save()`` — **no R2 round-trip is performed**.

    R2 cost: **0 operations** (everything happens in RAM).
    """
    raw = file_or_bytes.read() if hasattr(file_or_bytes, 'read') else file_or_bytes
    img = Image.open(io.BytesIO(raw))
    img.load()

    needs_resize = img.width > max_dim or img.height > max_dim
    is_webp = (img.format or '').upper() == 'WEBP'

    if not needs_resize and is_webp:
        # Already optimal — return the raw bytes as-is
        return ContentFile(raw), '.webp'

    if needs_resize:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    # Convert non-RGB modes → RGB for WebP lossy
    if img.mode not in ('RGB',):
        if img.mode in ('RGBA', 'LA', 'PA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel('A'))
            img = bg
        elif img.mode == 'P' and 'transparency' in img.info:
            img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert('RGB')

    quality = settings.ELECTON_SETTINGS.get('CANDIDATE_IMAGE_QUALITY', 85)
    buf = io.BytesIO()
    img.save(buf, format='WEBP', quality=quality, method=4)
    buf.seek(0)

    return ContentFile(buf.read()), '.webp'


class Candidate(models.Model):
    """A candidate running for a particular post within an election."""

    election = models.ForeignKey(
        'elections.Election',
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    post = models.ForeignKey(
        'elections.Post',
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    name = models.CharField(max_length=255)
    bio = models.TextField(blank=True, default='')
    order = models.PositiveIntegerField(default=0)
    image = models.ImageField(
        upload_to=candidate_image_upload_path,
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['post', 'name']
        ordering = ['post', 'order', 'name']

    def __str__(self):
        return f"{self.name} — {self.post.name} ({self.election.name})"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self):
        """Ensure post belongs to the same election."""
        if self.post_id and self.election_id and self.post.election_id != self.election_id:
            raise ValidationError("Candidate's post must belong to the same election.")

    def save(self, *args, **kwargs):
        # ── R2-friendly: no post-save round-trip ──────────────────────
        # Image processing now happens BEFORE save via
        # ``prepare_candidate_image()`` in the calling view/service.
        # This avoids the old pattern of: PUT original → GET → resize →
        # PUT WebP → DELETE original (4 Class-A + 3 Class-B ops).
        # New pattern: single PUT of the final WebP (1 Class-A op).
        #
        # NOTE: clean_fields() / validate_unique() are NOT called here.
        # They are non-standard in Model.save() (Django never calls them
        # by default) and cause unnecessary DB queries on every save.
        # DB constraints (unique_together, max_length, FK) catch all
        # violations at the DB layer.  Explicit validation is done in
        # the views before reaching this point.
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------

    def _resize_image(self):
        """Legacy resize hook — now a no-op.

        All image processing is done in-memory BEFORE saving to storage
        via ``prepare_candidate_image()``.  This method is retained only
        so older codepaths that call it do not crash; it returns
        immediately without touching R2.
        """
        return

    @property
    def image_url(self):
        """Return image URL with a cache-busting ``?v=`` timestamp.

        Because uploads use a fixed filename (``candidate-{id}.webp``) that is
        overwritten in place, the CDN would otherwise serve the old photo for
        up to 30 days.  Appending ``?v=<updated_at unix>`` forces a fresh fetch
        whenever the candidate record is saved — zero extra R2 ops.
        """
        if not self.image:
            return None
        url = self.image.url
        if self.updated_at:
            url = f"{url}?v={int(self.updated_at.timestamp())}"
        return url

    # ------------------------------------------------------------------
    # Vote helpers (lazy imports avoid circular references)
    # ------------------------------------------------------------------

    def get_vote_count(self):
        """Total votes cast for this candidate."""
        from apps.voting.models import Vote  # noqa: E402
        return Vote.objects.filter(candidate=self).count()

    def get_vote_percentage(self, total_votes=None):
        """Percentage of votes relative to *total_votes* for the post."""
        if total_votes is None:
            from apps.voting.models import Vote  # noqa: E402
            total_votes = Vote.objects.filter(post=self.post).count()
        if total_votes == 0:
            return 0
        return round((self.get_vote_count() / total_votes) * 100, 2)

    # ------------------------------------------------------------------
    # Deletion with image + directory cleanup
    # ------------------------------------------------------------------

    def delete(self, *args, **kwargs):
        image_storage = self.image.storage if self.image else None
        image_name = self.image.name if self.image else None
        result = super().delete(*args, **kwargs)

        # Clean up stored image (works with both local and cloud storage)
        if image_name and image_storage:
            try:
                image_storage.delete(image_name)
            except Exception:
                logger.exception("Failed to delete image %s", image_name)

        return result
