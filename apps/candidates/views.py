"""
ElectON v2 — Candidates views.

Candidate CRUD lives here alongside voter import/export (because they
share the election-owner permission check and the election dashboard
is the hub for both).
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View

from apps.elections.mixins import AjaxRateLimitMixin, ElectionOwnerMixin
from .forms import BulkVoterUploadForm
from .models import Candidate
from .services.file_service import FileProcessor


# ------------------------------------------------------------------
# Candidate CRUD
# ------------------------------------------------------------------

class DeleteCandidateView(ElectionOwnerMixin, View):
    """POST-only: remove a candidate (with image cleanup)."""

    def _is_ajax(self, request):
        """Check if request is an AJAX/fetch call expecting JSON."""
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    def post(self, request, election_uuid, candidate_id):
        election = self.get_election(election_uuid)
        is_ajax = self._is_ajax(request)

        if not election.can_edit:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Cannot modify a launched or ended election.'}, status=400)
            messages.error(request, "Cannot modify a launched or ended election.")
            return redirect('elections:dashboard', election_uuid=election_uuid)

        candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)
        name = candidate.name
        candidate.delete()  # triggers image + directory cleanup

        # SSE: push stats update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        if is_ajax:
            return JsonResponse({'success': True, 'message': f"Candidate '{name}' deleted."})

        messages.success(request, f"Candidate '{name}' deleted.")
        return redirect('elections:dashboard', election_uuid=election_uuid)


class UpdateCandidateView(ElectionOwnerMixin, View):
    """FEAT-02: POST-only — update a candidate's name and/or bio inline."""

    def post(self, request, election_uuid, candidate_id):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse({'success': False, 'error': 'Cannot modify a launched election.'}, status=400)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

        name = (body.get('name') or '').strip()
        bio  = (body.get('bio')  or '').strip()

        # Sanitise user input to prevent stored XSS
        from django.utils.html import strip_tags
        name = strip_tags(name)
        bio = strip_tags(bio)

        if not name:
            return JsonResponse({'success': False, 'error': 'Candidate name cannot be empty.'}, status=400)
        if len(name) > 255:
            return JsonResponse({'success': False, 'error': 'Name too long (max 255 chars).'}, status=400)
        if len(bio) > 500:
            return JsonResponse({'success': False, 'error': 'Bio too long (max 500 chars).'}, status=400)

        candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)
        candidate.name = name
        candidate.bio  = bio
        candidate.save(update_fields=['name', 'bio'])
        return JsonResponse({'success': True, 'name': candidate.name, 'bio': candidate.bio})


class UpdateCandidateImageView(ElectionOwnerMixin, View):
    """POST-only: update a candidate's photo (click-to-upload).

    R2 ops: 1 Class-A (PUT of final WebP) + optionally 1 Class-A (DELETE old).
    The image is resized/converted to WebP **in-memory** before touching R2.
    """

    def post(self, request, election_uuid, candidate_id):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot modify a launched or ended election.'},
                status=400,
            )

        candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)

        image_file = request.FILES.get('image')
        if not image_file:
            return JsonResponse({'success': False, 'error': 'No image provided.'}, status=400)

        # Validate file size
        max_size = settings.ELECTON_SETTINGS.get('MAX_UPLOAD_SIZE', 5 * 1024 * 1024)
        if image_file.size > max_size:
            return JsonResponse(
                {'success': False, 'error': f'Image too large. Maximum is {max_size // (1024 * 1024)} MB.'},
                status=400,
            )

        # Validate content type
        allowed_types = settings.ELECTON_SETTINGS.get(
            'ALLOWED_IMAGE_TYPES', ['image/jpeg', 'image/png', 'image/webp']
        )
        if image_file.content_type not in allowed_types:
            return JsonResponse(
                {'success': False, 'error': f'Invalid image type. Allowed: {", ".join(allowed_types)}'},
                status=400,
            )

        # Validate + resize/convert to WebP entirely in-memory (0 R2 ops)
        from PIL import Image as PILImage
        from .models import prepare_candidate_image
        try:
            # Quick bomb check before full processing
            image_file.seek(0)
            probe = PILImage.open(image_file)
            if probe.size[0] * probe.size[1] > 25_000_000:
                return JsonResponse({'success': False, 'error': 'Image too large (max 25 megapixels).'}, status=400)
            image_file.seek(0)

            webp_content, ext = prepare_candidate_image(image_file)
        except Exception:
            return JsonResponse({'success': False, 'error': 'File is not a valid image.'}, status=400)

        # Fixed filename — PUT always overwrites same R2 key (1A total, no DELETE)
        # upload_to prepends candidates/{user_id}/{election_uuid}/ automatically.
        webp_name = f'candidate-{candidate_id}.webp'

        try:
            # 1 Class-A PUT — overwrites the existing object in place
            candidate.image.save(webp_name, webp_content, save=False)
            candidate.save(update_fields=['image', 'updated_at'])
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Failed to save candidate image for candidate %s", candidate_id
            )
            return JsonResponse(
                {'success': False, 'error': 'Failed to save image. Please try again.'},
                status=500,
            )

        return JsonResponse({
            'success': True,
            'image_url': candidate.image_url,
            'message': 'Photo updated.',
        })


class GenerateUploadUrlView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    """Generate a pre-signed PUT URL for direct-to-R2 candidate image upload.

    Returns ``presign: true`` with ``upload_url`` + ``object_key`` when R2 is
    the configured default backend (both dev and production).
    Returns ``presign: false`` when file-system storage is active.

    R2 ops: **0** — ``generate_presigned_url`` is a local boto3 computation.
    """
    rate_limit_max = 20
    rate_limit_window = 60

    def post(self, request, election_uuid, candidate_id):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot modify a launched or ended election.'},
                status=400,
            )

        # Ensure candidate belongs to this election
        get_object_or_404(Candidate, pk=candidate_id, election=election)

        # Check that S3Boto3Storage is the configured default backend.
        default_backend = getattr(settings, 'STORAGES', {}).get('default', {}).get('BACKEND', '')
        if 's3boto3' not in default_backend.lower():
            # Non-R2 storage — tell JS to use the server-mediated route
            return JsonResponse({'success': True, 'presign': False})

        if settings.DEBUG:
            # In development, skip presigned URLs — the browser PUT would go
            # directly to R2's endpoint which requires CORS rules on the bucket.
            # The server-mediated path (UpdateCandidateImageView) is equally
            # efficient: 1 Class-A PUT, fixed filename, no DELETE needed.
            return JsonResponse({'success': True, 'presign': False})

        import uuid as uuid_lib  # noqa: F401 (kept for potential future use)
        object_key = (
            f"candidates/{request.user.id}/{election.election_uuid}/"
            f"candidate-{candidate_id}.webp"
        )

        # Generate pre-signed PUT URL via boto3 — use storages['default'] to get the
        # actual S3Boto3Storage instance (not the DefaultStorage proxy).
        from django.core.files.storage import storages as _storages
        _s3 = _storages['default']
        presigned_url = _s3.connection.meta.client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': _s3.bucket_name,
                'Key': object_key,
                'ContentType': 'image/webp',
            },
            ExpiresIn=300,  # 5 minutes
        )

        return JsonResponse({
            'success': True,
            'presign': True,
            'upload_url': presigned_url,
            'object_key': object_key,
        })


class ConfirmUploadView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    """Confirm that a direct-to-R2 upload completed. Updates candidate image.

    Validates that the ``object_key`` matches the expected path pattern for the
    requesting user + election + candidate, verifies the object exists in R2,
    then updates the Candidate model (skipping ``_resize_image`` since the image
    was already cropped client-side).
    """
    rate_limit_max = 20
    rate_limit_window = 60

    def post(self, request, election_uuid, candidate_id):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot modify a launched or ended election.'},
                status=400,
            )

        candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

        object_key = (body.get('object_key') or '').strip()
        if not object_key:
            return JsonResponse({'success': False, 'error': 'Missing object_key.'}, status=400)

        # Validate the key belongs to this user / election / candidate — exact match
        # (fixed filename strategy: no UUID suffix, always candidate-{id}.webp)
        expected_key = f"candidates/{request.user.id}/{election.election_uuid}/candidate-{candidate_id}.webp"
        if object_key != expected_key:
            return JsonResponse({'success': False, 'error': 'Invalid object key.'}, status=403)

        # NOTE: We intentionally skip ``default_storage.exists(object_key)``.
        # The object_key is a fixed deterministic path and was just PUT by the
        # browser via a pre-signed URL — JS already verified ``putRes.ok``.
        # No DELETE needed — the fixed key overwrites the old file in place.

        # Update candidate image field directly (skip _resize_image — pre-cropped)
        # Use .update() to bypass save() signal overhead, but explicitly set
        # updated_at so the ?v= cache-buster in image_url reflects the new image.
        from django.utils import timezone
        now = timezone.now()
        candidate.image.name = object_key
        candidate.updated_at = now  # sync in-memory so image_url ?v= is correct
        Candidate.objects.filter(pk=candidate.pk).update(
            image=object_key,
            updated_at=now,
        )

        return JsonResponse({
            'success': True,
            'image_url': candidate.image_url,
            'message': 'Photo updated.',
        })


class AddCandidatesBulkView(ElectionOwnerMixin, View):
    """POST-only: add one or more candidates to a post (JSON body)."""

    def post(self, request, election_uuid, post_id):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot modify a launched or ended election.'},
                status=400,
            )

        post_obj = get_object_or_404(election.posts, pk=post_id)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid request body.'}, status=400)

        entries = data.get('candidates', [])
        if not entries or not isinstance(entries, list):
            return JsonResponse({'success': False, 'error': 'No candidates provided.'}, status=400)

        # Filter to non-empty names
        clean = []
        for entry in entries:
            name = str(entry.get('name', '')).strip()
            if name:
                bio = str(entry.get('bio', '')).strip()
                clean.append({'name': name, 'bio': bio})

        if not clean:
            return JsonResponse(
                {'success': False, 'error': 'At least one candidate name is required.'},
                status=400,
            )

        # Plan-based limit check
        from apps.subscriptions.services import PlanLimitService
        _, info = PlanLimitService.check_candidate_limit(post_obj)
        current = info['current']
        limit = info['limit']
        if current + len(clean) > limit:
            return JsonResponse({
                'success': False,
                'error': (
                    f'Adding {len(clean)} candidate(s) would exceed the limit '
                    f'of {limit} per position on your {info["plan_name"]} plan. '
                    f'Currently {current} candidate(s).'
                ),
            }, status=400)

        created = []
        with transaction.atomic():
            # Re-check limit inside the transaction to eliminate TOCTOU race
            from apps.subscriptions.services import PlanLimitService as _PLS
            _, recheck = _PLS.check_candidate_limit(post_obj)
            if recheck['current'] + len(clean) > recheck['limit']:
                return JsonResponse({
                    'success': False,
                    'error': (
                        f'Adding {len(clean)} candidate(s) would exceed the limit '
                        f'of {recheck["limit"]} on your {recheck["plan_name"]} plan. '
                        f'Currently {recheck["current"]} candidate(s).'
                    ),
                }, status=400)

            # Prefetch existing names to avoid per-candidate N+1 query
            existing_names = set(
                Candidate.objects.filter(post=post_obj)
                .values_list('name', flat=True)
            )
            existing_lower = {n.lower() for n in existing_names}
            for item in clean:
                # Skip duplicates (case-insensitive)
                if item['name'].lower() in existing_lower:
                    continue
                cand = Candidate(
                    election=election,
                    post=post_obj,
                    name=item['name'],
                    bio=item['bio'],
                )
                cand.save()
                created.append({
                    'candidate_id': cand.pk,
                    'name': cand.name,
                    'bio': cand.bio,
                    'image_url': cand.image_url,
                })

        count = len(created)

        # SSE: push stats update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'{count} candidate{"s" if count != 1 else ""} added.',
            'candidates': created,
            'post_id': post_obj.pk,
            'new_count': post_obj.candidates.count(),
        })


class ReorderCandidatesView(ElectionOwnerMixin, View):
    """Reorder candidates within a position via drag-and-drop."""

    def post(self, request, election_uuid, post_id):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse({'success': False, 'error': 'Cannot reorder after launch.'}, status=400)

        post_obj = get_object_or_404(election.posts, pk=post_id)

        try:
            data = json.loads(request.body)
            candidate_ids = data.get('candidate_ids', [])
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

        if not candidate_ids:
            return JsonResponse({'success': False, 'error': 'No candidate IDs provided.'}, status=400)

        with transaction.atomic():
            # Batch update all candidate orders in one query (was N+1)
            from django.db.models import Case, When, Value, IntegerField
            try:
                candidate_ids = [int(cid) for cid in candidate_ids]
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid candidate ID format.'}, status=400)
            cases = [When(pk=cid, then=Value(idx)) for idx, cid in enumerate(candidate_ids)]
            Candidate.objects.filter(post=post_obj).update(
                order=Case(*cases, default=Value(9999), output_field=IntegerField())
            )

        return JsonResponse({'success': True, 'message': 'Candidates reordered.'})


# ------------------------------------------------------------------
# Voter import / export
# ------------------------------------------------------------------

class ImportVotersView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    rate_limit_max = 10
    rate_limit_window = 60
    """Process voter CSV/Excel upload."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot import voters after election is launched.'},
                status=400,
            )

        form = BulkVoterUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return JsonResponse({
                'success': False,
                'error': '; '.join(
                    err for errs in form.errors.values() for err in errs
                ),
            }, status=400)

        processor = FileProcessor()
        result = processor.import_voters_from_file(form.cleaned_data['voter_file'], election)
        # Ensure 'error' key is present so the JS post() helper can show the real message
        if not result.get('success') and not result.get('error'):
            result['error'] = result.get('message', 'Import failed.')
        status = 200 if result['success'] else 400
        return JsonResponse(result, status=status)


class ParseVoterFileView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    """Parse a voter CSV/Excel file and return the voter list as JSON.

    Does NOT create any credentials or send emails. The frontend uses
    the returned list to populate the manual entry boxes; the user then
    clicks "Send Invitations" to go through the normal flow.
    """
    rate_limit_max = 10
    rate_limit_window = 60

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot import voters after election is launched.'},
                status=400,
            )

        form = BulkVoterUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return JsonResponse({
                'success': False,
                'error': '; '.join(err for errs in form.errors.values() for err in errs),
            }, status=400)

        processor = FileProcessor()
        result = processor.parse_voters_file(form.cleaned_data['voter_file'])
        if not result.get('success') and not result.get('error'):
            result['error'] = result.get('message', 'Parse failed.')
        status = 200 if result['success'] else 400
        return JsonResponse(result, status=status)


class ExportVotersCSVView(ElectionOwnerMixin, View):
    """Download voters as CSV."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        return FileProcessor().export_voters_to_csv(election)


class ExportVotersExcelView(ElectionOwnerMixin, View):
    """Download voters as Excel. Supports ?type=access_requests for pending access requests."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        export_type = request.GET.get('type', 'voters')
        fp = FileProcessor()
        if export_type == 'access_requests':
            return fp.export_access_requests_to_excel(election)
        return fp.export_voters_to_excel(election)


class ExportVotersPDFView(ElectionOwnerMixin, View):
    """Download all voters (email + in-person) as a styled PDF.

    Supports ?type=access_requests to export pending access requests instead.
    """

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        export_type = request.GET.get('type', 'voters')
        fp = FileProcessor()
        if export_type == 'access_requests':
            return fp.export_access_requests_to_pdf(election)
        return fp.export_voters_to_pdf(election)


class DownloadTemplateView(LoginRequiredMixin, View):
    """Download a sample CSV/Excel template for voter import."""

    def get(self, request, fmt):
        # Accept both 'excel' and 'xlsx' as format identifiers
        if fmt == 'xlsx':
            fmt = 'excel'
        if fmt not in ('csv', 'excel'):
            return HttpResponse("Invalid format.", status=400)
        return FileProcessor().generate_sample_template(fmt)

class RegenerateCredentialView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    rate_limit_max = 20
    rate_limit_window = 60
    """FEAT-04: Regenerate (resend) credentials for a single voter.

    Also un-revokes the voter if they were previously revoked, so the admin
    can reinstate access by clicking the resend button.
    """

    def post(self, request, election_uuid, credential_id):
        election = self.get_election(election_uuid)

        from apps.voting.models import VoterCredential
        from django.contrib.auth.hashers import make_password

        try:
            credential = VoterCredential.objects.get(pk=credential_id, election=election)
        except VoterCredential.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Voter not found.'}, status=404)

        if credential.has_voted:
            return JsonResponse(
                {'success': False, 'error': 'Cannot regenerate credentials for a voter who has already voted.'},
                status=400,
            )

        # Track whether the voter was revoked so the frontend can update the badge
        was_revoked = credential.is_revoked

        # Generate new password, keep same username
        new_password = VoterCredential._generate_password()
        credential.one_time_password_hash = make_password(new_password)
        credential.invitation_sent = False
        credential.invitation_error = ''
        credential.invitation_error_code = ''
        credential.credentials_resent_at = timezone.now()

        save_fields = [
            'one_time_password_hash', 'invitation_sent',
            'invitation_error', 'invitation_error_code',
            'credentials_resent_at', 'updated_at',
        ]

        # Un-revoke so resending reinstates the voter's access
        if was_revoked:
            credential.is_revoked = False
            save_fields.append('is_revoked')

        credential.save(update_fields=save_fields)

        # SEC-05: Trigger email with new credentials instead of returning plaintext
        from apps.notifications.services.email_service import EmailService
        result = EmailService.send_bulk_voter_invitations(
            [(credential, new_password)], election,
        )

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'regenerated', 'credential_id': credential.pk},
                   user_id=request.user.pk)

        if result.get('sent', 0) > 0:
            return JsonResponse({
                'success': True,
                'message': f'New credentials sent to {credential.display_name}.',
                'was_revoked': was_revoked,
            })
        else:
            return JsonResponse({
                'success': True,
                'message': f'Credentials regenerated for {credential.display_name}, but email delivery failed. The voter can still use the new credentials.',
                'was_revoked': was_revoked,
            })


# ------------------------------------------------------------------
# FEAT-08: Bulk candidate import
# ------------------------------------------------------------------

class ImportCandidatesView(ElectionOwnerMixin, View):
    """Process candidate CSV/Excel upload."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot import candidates after election is launched.'},
                status=400,
            )

        uploaded_file = request.FILES.get('candidate_file')
        if not uploaded_file:
            return JsonResponse({'success': False, 'error': 'No file provided.'}, status=400)

        processor = FileProcessor()
        result = processor.import_candidates_from_file(uploaded_file, election)
        status = 200 if result['success'] else 400
        return JsonResponse(result, status=status)


class DownloadCandidateTemplateView(ElectionOwnerMixin, View):
    """Download a sample CSV/Excel template for candidate import."""

    def get(self, request, election_uuid, fmt):
        election = self.get_election(election_uuid)
        if fmt not in ('csv', 'excel'):
            return HttpResponse("Invalid format.", status=400)
        return FileProcessor().generate_candidate_template(election, fmt)


# ------------------------------------------------------------------
# PHASE 3: Offline credential generation
# ------------------------------------------------------------------

class GenerateOfflineCredentialsView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    rate_limit_max = 5
    rate_limit_window = 60
    """Generate PDF credentials for in-person/offline voters."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot add voters after election is launched.'},
                status=400,
            )

        try:
            num_voters = int(request.POST.get('num_voters', 0))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid number.'}, status=400)

        if num_voters < 1 or num_voters > 500:
            return JsonResponse(
                {'success': False, 'error': 'Number must be between 1 and 500.'},
                status=400,
            )

        # Check voter limit (plan-based) — verify combined count including new batch
        from apps.subscriptions.services import PlanLimitService
        allowed, info = PlanLimitService.check_voter_limit(election)
        if not allowed:
            return JsonResponse({
                'success': False,
                'error': f'Voter limit reached ({info["limit"]}) for your {info["plan_name"]} plan.',
            }, status=400)
        if info['current'] + num_voters > info['limit']:
            remaining = info['limit'] - info['current']
            return JsonResponse({
                'success': False,
                'error': (
                    f'Adding {num_voters} voter(s) would exceed the limit of '
                    f'{info["limit"]} on your {info["plan_name"]} plan. '
                    f'{remaining} slot(s) remaining.'
                ),
            }, status=400)

        from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential
        from django.contrib.auth.hashers import make_password

        # Generate sequential batch number for this election
        last_batch = (
            VoterCredential.objects
            .filter(election=election, batch_number__startswith='BATCH-')
            .order_by('-batch_number')
            .values_list('batch_number', flat=True)
            .first()
        )
        if last_batch:
            batch_num = int(last_batch.split('-')[1]) + 1
        else:
            batch_num = 1
        batch_number = f'BATCH-{batch_num:03d}'

        credentials = []
        base_count = election.voter_credentials.count()

        with transaction.atomic():
            for i in range(num_voters):
                # Pre-generate username so we can use it in the email
                username = VoterCredential._generate_unique_username()
                password = VoterCredential._generate_password()
                email = f"{username.lower()}{OFFLINE_VOTER_DOMAIN}"

                cred = VoterCredential.objects.create(
                    election=election,
                    voter_email=email,
                    voter_name=f'Voter {base_count + i + 1}',
                    one_time_username=username,
                    one_time_password_hash=make_password(password),
                    batch_number=batch_number,
                )
                credentials.append({
                    'name': cred.voter_name,
                    'username': cred.one_time_username,
                    'password': password,
                })

        # SSE: push stats update (new offline voters)
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        # Generate the PDF
        from apps.results.services.pdf_service import PDFService
        pdf_response = PDFService().generate_credentials_pdf(credentials, election, batch_number=batch_number)
        return pdf_response


# ------------------------------------------------------------------
# PHASE 3: Individual voter revoke (draft only)
# ------------------------------------------------------------------

class RevokeVoterView(ElectionOwnerMixin, View):
    """Revoke a single voter's access. Only allowed before launch."""

    def post(self, request, election_uuid, credential_id):
        election = self.get_election(election_uuid)

        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot revoke after election is launched.'},
                status=400,
            )

        from apps.voting.models import VoterCredential

        try:
            credential = VoterCredential.objects.get(pk=credential_id, election=election)
        except VoterCredential.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Voter not found.'}, status=404)

        if credential.is_revoked:
            return JsonResponse(
                {'success': False, 'error': 'This voter is already revoked.'},
                status=400,
            )

        credential.is_revoked = True
        credential.revoked_at = timezone.now()
        credential.save(update_fields=['is_revoked', 'revoked_at', 'updated_at'])

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'revoked', 'credential_id': credential.pk},
                   user_id=request.user.pk)
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'Access revoked for {credential.display_name}.',
        })


# ------------------------------------------------------------------
# Bulk voter actions
# ------------------------------------------------------------------

class RevokeAllVotersView(ElectionOwnerMixin, View):
    """Revoke all non-voted, non-revoked email voters."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot revoke after election is launched.'},
                status=400,
            )

        from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential

        now = timezone.now()
        updated = (
            VoterCredential.objects
            .filter(election=election, is_revoked=False, has_voted=False)
            .exclude(voter_email__endswith=OFFLINE_VOTER_DOMAIN)
            .update(is_revoked=True, revoked_at=now, updated_at=now)
        )

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'bulk_revoked', 'count': updated},
                   user_id=request.user.pk)
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'{updated} voter{"s" if updated != 1 else ""} revoked.',
            'count': updated,
        })


class ResendAllInvitationsView(ElectionOwnerMixin, AjaxRateLimitMixin, View):
    """Resend / send invitations to ALL non-voted, non-revoked email voters.

    Includes voters who have never been invited yet (invitation_sent=False)
    as well as those who were previously invited (invitation_sent=True).
    Each voter gets fresh credentials and a new email.
    """
    rate_limit_max = 3
    rate_limit_window = 60

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot resend after election is launched.'},
                status=400,
            )

        from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential
        from django.contrib.auth.hashers import make_password

        # Include ALL active email voters — both previously invited AND newly registered
        credentials = (
            VoterCredential.objects
            .filter(
                election=election,
                has_voted=False,
                is_revoked=False,
            )
            .exclude(voter_email__endswith=OFFLINE_VOTER_DOMAIN)
        )

        pairs = []
        for cred in credentials:
            new_password = VoterCredential._generate_password()
            cred.one_time_password_hash = make_password(new_password)
            cred.invitation_sent = False
            cred.invitation_error = ''
            cred.invitation_error_code = ''
            cred.credentials_resent_at = timezone.now()
            cred.save(update_fields=[
                'one_time_password_hash', 'invitation_sent',
                'invitation_error', 'invitation_error_code',
                'credentials_resent_at', 'updated_at',
            ])
            pairs.append((cred, new_password))

        if not pairs:
            return JsonResponse({'success': True, 'message': 'No eligible voters to send to.', 'sent': 0, 'failed': 0})

        from apps.notifications.services.email_service import EmailService
        result = EmailService.send_bulk_voter_invitations(pairs, election)

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'bulk_invited', 'sent': result['sent'], 'failed': result['failed']},
                   user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'Sent: {result["sent"]}, Failed: {result["failed"]}',
            'sent': result['sent'],
            'failed': result['failed'],
        })


class RevokeBatchView(ElectionOwnerMixin, View):
    """Revoke all credentials in a specific batch."""

    def post(self, request, election_uuid, batch):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot revoke after election is launched.'},
                status=400,
            )

        from apps.voting.models import VoterCredential

        now = timezone.now()
        updated = (
            VoterCredential.objects
            .filter(election=election, batch_number=batch, is_revoked=False)
            .update(is_revoked=True, revoked_at=now, updated_at=now)
        )

        if updated == 0:
            return JsonResponse(
                {'success': False, 'error': f'No active voters found in batch {batch}.'},
                status=404,
            )

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'batch_revoked', 'batch': batch, 'count': updated},
                   user_id=request.user.pk)
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'{updated} credential{"s" if updated != 1 else ""} in {batch} revoked.',
            'count': updated,
        })


class RevokeAllBatchesView(ElectionOwnerMixin, View):
    """Revoke all non-voted, non-revoked batch (offline/PDF) credentials for an election."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)
        if not election.can_edit:
            return JsonResponse(
                {'success': False, 'error': 'Cannot revoke after election is launched.'},
                status=400,
            )

        from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential

        now = timezone.now()
        updated = (
            VoterCredential.objects
            .filter(election=election, is_revoked=False)
            .filter(voter_email__endswith=OFFLINE_VOTER_DOMAIN)
            .update(is_revoked=True, revoked_at=now, updated_at=now)
        )

        # SSE: push voter update
        from apps.elections.event_emitter import emit_event, build_stats_payload
        emit_event(election.election_uuid, 'voter_update',
                   {'action': 'all_batches_revoked', 'count': updated},
                   user_id=request.user.pk)
        emit_event(election.election_uuid, 'stats_update',
                   build_stats_payload(election), user_id=request.user.pk)

        return JsonResponse({
            'success': True,
            'message': f'{updated} batch credential{"s" if updated != 1 else ""} revoked.',
            'count': updated,
        })