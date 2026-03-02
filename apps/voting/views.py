"""
ElectON v2 — Voting views.

Key improvements over V1:
- Rate limiting on voter login (was missing)
- Uses ``VoteService`` for atomic, anonymized vote casting
- No ``json.loads(request.body)`` scattered everywhere — uses DRF-style
  ``request.POST`` or lightweight JSON parsing with proper error handling
"""
import hashlib
import json
import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.generic import TemplateView

from apps.accounts.constants import RATE_LIMITS
from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.elections.models import Election
from apps.elections.views import _solana_cluster_param
from .models import VoterCredential, VoterAccessRequest
from .services.vote_service import VoteService

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Voter login page
# ------------------------------------------------------------------

class VoterLoginPageView(TemplateView):
    """Serves the voter login HTML page."""
    template_name = 'auth/voter/voter_login.html'


# ------------------------------------------------------------------
# Voter login API
# ------------------------------------------------------------------

class VoterLoginView(View):
    """Authenticate a voter with one-time credentials (JSON API)."""

    @method_decorator(csrf_protect)
    def post(self, request):
        # --- Rate limiting (was missing in V1) ---
        rl_config = RATE_LIMITS['voter_login']
        rate_limiter = RateLimitService('voter_login', **rl_config)
        client_ip = get_client_ip(request)

        if not rate_limiter.is_allowed(client_ip):
            return JsonResponse({
                'success': False,
                'message': 'Too many login attempts. Please try again later.',
                'retry_after': rate_limiter.get_retry_after(client_ip),
            }, status=429)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()

        if not username or not password:
            rate_limiter.record_attempt(client_ip)
            return JsonResponse({
                'success': False,
                'message': 'Username and password are required.',
            }, status=400)

        try:
            credential = VoterCredential.objects.select_related('election').get(
                one_time_username=username,
            )
        except VoterCredential.DoesNotExist:
            rate_limiter.record_attempt(client_ip)
            return JsonResponse({'success': False, 'message': 'Invalid credentials.'}, status=401)

        if not credential.check_password(password):
            rate_limiter.record_attempt(client_ip)
            return JsonResponse({'success': False, 'message': 'Invalid credentials.'}, status=401)

        if credential.is_revoked:
            return JsonResponse({
                'success': False,
                'message': 'Your voting access has been revoked by the election administrator.',
                'error_code': 'revoked',
                'redirect_url': reverse(
                    'voting:voter_access_denied',
                    kwargs={'election_uuid': credential.election.election_uuid},
                ),
            }, status=403)

        election = credential.election

        if credential.has_voted:
            return JsonResponse({
                'success': False,
                'message': 'You have already submitted your vote.',
                'error_code': 'already_voted',
                'redirect_url': reverse(
                    'voting:voter_election_results',
                    kwargs={'election_uuid': election.election_uuid},
                ),
            }, status=403)

        if not election.is_active:
            status = election.current_status
            if status == Election.STATUS_PRE_LAUNCH:
                msg = 'This election has not started yet.'
                error_code = 'election_pre_launch'
            elif status == Election.STATUS_CONCLUDED:
                msg = 'This election has ended. Voting is no longer available.'
                error_code = 'election_concluded'
            elif status == Election.STATUS_INACTIVE:
                msg = 'This election has been launched but voting has not started yet. Please check back later.'
                error_code = 'election_inactive'
            else:
                msg = 'This election is not currently accepting votes.'
                error_code = 'election_not_active'
            return JsonResponse({
                'success': False,
                'message': msg,
                'error_code': error_code,
                'redirect_url': reverse(
                    'voting:voter_access_denied',
                    kwargs={'election_uuid': election.election_uuid},
                ),
            }, status=403)

        # Cycle session key to prevent session fixation (SEC-07)
        request.session.cycle_key()

        # Store voter session (bound to IP for security)
        request.session['voter_credential_id'] = credential.pk
        request.session['voter_name'] = credential.voter_name
        request.session['election_uuid'] = str(election.election_uuid)
        request.session['voter_ip'] = client_ip
        request.session['voter_ua_hash'] = hashlib.sha256(
            request.META.get('HTTP_USER_AGENT', '').encode()
        ).hexdigest()[:16]

        return JsonResponse({
            'success': True,
            'message': 'Login successful.',
            'redirect_url': reverse('voting:vote'),
        })


# ------------------------------------------------------------------
# Voting interface
# ------------------------------------------------------------------

class VoteView(View):
    """Main voting page — GET shows ballot, POST submits votes."""

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        credential = self._get_credential(request)
        if credential is None:
            messages.error(request, 'Please log in to vote.')
            return redirect('public_home')

        if credential.has_voted:
            return redirect('voting:voter_election_results', election_uuid=credential.election.election_uuid)

        if credential.is_revoked:
            messages.error(request, 'Your access has been revoked.')
            return redirect('public_home')

        election = credential.election
        if not election.is_active:
            return redirect('voting:voter_access_denied', election_uuid=election.election_uuid)

        # Optimised query: posts with prefetched candidates
        posts = (
            election.posts
            .prefetch_related('candidates')
            .order_by('order', 'created_at')
        )

        return render(request, 'voting/ballot.html', {
            'election': election,
            'voter_name': credential.voter_name,
            'posts': posts,
            'admin_message': election.admin_message,
            'csrf_token': get_token(request),
        })

    @method_decorator(csrf_protect)
    def post(self, request):
        credential = self._get_credential(request)
        if credential is None:
            return JsonResponse({'success': False, 'message': 'Please log in to vote.'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

        votes_data = data.get('votes', {})
        if not votes_data:
            return JsonResponse({'success': False, 'message': 'No votes submitted.'}, status=400)

        try:
            result = VoteService.cast_votes(credential, votes_data)
        except ValidationError as exc:
            # Return the specific validation message to the user
            msg = exc.message if hasattr(exc, 'message') else str(exc)
            return JsonResponse({'success': False, 'message': msg}, status=400)
        except Exception as exc:
            logger.exception("Vote casting failed for credential %s", credential.pk)
            return JsonResponse({'success': False, 'message': 'An error occurred while processing your vote. Please try again.'}, status=400)

        election_uuid = str(credential.election.election_uuid)

        # Flush voter session after successful vote but keep minimal info for results access
        request.session.flush()
        request.session['voted_election_uuid'] = election_uuid
        request.session['voter_hash'] = result.get('voter_hash', '')

        return JsonResponse({
            'success': True,
            'message': 'Vote submitted successfully.',
            'voter_hash': result.get('voter_hash', ''),
            'redirect_url': reverse(
                'voting:voter_election_results',
                kwargs={'election_uuid': election_uuid},
            ),
        })

    @staticmethod
    def _get_credential(request):
        cred_id = request.session.get('voter_credential_id')
        if not cred_id:
            return None

        # Verify session is bound to same client (SEC-06)
        # Only enforce user-agent match; log IP changes instead of blocking
        # (IP can change legitimately on mobile/WiFi switching)
        stored_ip = request.session.get('voter_ip')
        stored_ua = request.session.get('voter_ua_hash')
        current_ip = get_client_ip(request)
        current_ua = hashlib.sha256(
            request.META.get('HTTP_USER_AGENT', '').encode()
        ).hexdigest()[:16]
        if stored_ua and stored_ua != current_ua:
            return None
        if stored_ip and stored_ip != current_ip:
            logger.info(
                "Voter session IP changed from %s to %s (credential=%s)",
                stored_ip, current_ip, cred_id,
            )

        try:
            return VoterCredential.objects.select_related('election').get(pk=cred_id)
        except VoterCredential.DoesNotExist:
            return None


# ------------------------------------------------------------------
# Static pages
# ------------------------------------------------------------------

class VoterAccessDeniedView(TemplateView):
    template_name = 'auth/voter/access_denied.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            ctx['election'] = Election.objects.get(election_uuid=kwargs['election_uuid'])
        except Election.DoesNotExist:
            pass
        return ctx


class VoterAccessRequestView(View):
    """Public page: voter enters access code + name + email in one step.

    GET  — render the access request form (optionally pre-fills code from ?code= param)
    POST — JSON API: validates access_code ➜ checks election ➜ checks voter status ➜ creates request
    """
    template_name = 'auth/voter/access_request.html'

    def get(self, request):
        response = render(request, self.template_name)
        # Prevent bfcache so the page always reloads fresh on back-navigation.
        # Without this, the browser may restore a cached DOM where the success
        # state is visible and the form is hidden.
        response['Cache-Control'] = 'no-store'
        return response

    @method_decorator(csrf_protect)
    def post(self, request):
        # Rate-limit per IP: 10 requests per hour to prevent code enumeration / spam
        _rl_cfg = RATE_LIMITS['voter_access_request']
        _rate_limiter = RateLimitService('voter_access_request', **_rl_cfg)
        _client_ip = get_client_ip(request)
        if not _rate_limiter.is_allowed(_client_ip):
            retry_after = _rate_limiter.get_retry_after(_client_ip)
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Too many requests. Please wait a while before trying again.',
                    'retry_after': retry_after,
                },
                status=429,
            )
        _rate_limiter.record_attempt(_client_ip)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Invalid request.'}, status=400)

        return self._submit_request(data)

    def _submit_request(self, data):
        """Single-step: validate all fields, look up election, check statuses, create request."""
        from django.core.validators import validate_email as _validate_email

        code = (data.get('access_code') or '').strip().upper()
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()

        # ── Field validation ──────────────────────────────────────────
        errors = {}
        if not code:
            errors['access_code'] = 'Access code is required.'
        if not name:
            errors['name'] = 'Full name is required.'
        if not email:
            errors['email'] = 'Email address is required.'
        else:
            try:
                _validate_email(email)
            except ValidationError:
                errors['email'] = 'Please enter a valid email address.'

        if errors:
            msg = ' '.join(errors.values())
            return JsonResponse({'success': False, 'message': msg, 'errors': errors}, status=400)

        # ── Election lookup ───────────────────────────────────────────
        try:
            election = Election.objects.get(access_code=code)
        except Election.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'No election found with this access code. Please check and try again.',
            }, status=404)

        if election.is_launched:
            return JsonResponse({
                'success': False,
                'message': 'This election has already been launched. Access requests are closed.',
            }, status=403)

        # ── Already a registered voter? ───────────────────────────────
        if VoterCredential.objects.filter(election=election, voter_email=email).exists():
            return JsonResponse({
                'success': False,
                'message': (
                    'You are already registered as a voter for this election. '
                    'Please check your email for the voter credentials and login as a voter to vote.'
                ),
            }, status=409)

        # ── Existing access request? ──────────────────────────────────
        existing = VoterAccessRequest.objects.filter(election=election, email=email).first()
        if existing:
            if existing.status == VoterAccessRequest.Status.PENDING:
                return JsonResponse({
                    'success': False,
                    'message': (
                        'Your access request has already been submitted. '
                        'Please wait for the election administrator to approve it.'
                    ),
                }, status=409)
            elif existing.status == VoterAccessRequest.Status.APPROVED:
                return JsonResponse({
                    'success': False,
                    'message': (
                        'Your access request has already been approved. '
                        'Please check your email for the voter credentials and login as a voter to vote.'
                    ),
                }, status=409)
            elif existing.status == VoterAccessRequest.Status.REJECTED:
                # NOTE: In normal operation this branch is never reached.
                # RejectAccessRequestView *deletes* the record rather than setting
                # status=REJECTED, so no rejected rows exist in the database.
                # This block is kept as a defensive fallback for any records that
                # may have been created outside the normal flow (e.g. imports,
                # shell commands, or a future admin action that marks as rejected
                # instead of deleting).  It automatically re-queues the request.

                # Re-request: reset the rejected request back to pending
                existing.status = VoterAccessRequest.Status.PENDING
                existing.name = name  # update name in case it changed
                existing.reviewed_at = None
                existing.save(update_fields=['status', 'name', 'reviewed_at', 'updated_at'])
                return JsonResponse({
                    'success': True,
                    'message': (
                        f'Your access request to "{election.name}" has been re-submitted. '
                        f'You\'ll receive the voter credentials in your email once the election admin approves your request.'
                    ),
                    'election_name': election.name,
                })

        # ── Create new request ────────────────────────────────────────
        VoterAccessRequest.objects.create(
            election=election,
            name=name,
            email=email,
        )

        # SSE: notify admin of new access request
        from apps.elections.event_emitter import emit_event
        emit_event(election.election_uuid, 'access_request',
                   {'action': 'new', 'name': name, 'email': email},
                   user_id=election.created_by_id)

        return JsonResponse({
            'success': True,
            'message': (
                f'Access request to "{election.name}" successfully submitted. '
                f'You\'ll receive the voter credentials in your email once the election admin approves your request.'
            ),
            'election_name': election.name,
        })


# ------------------------------------------------------------------
# Voter results (if admin enabled)
# ------------------------------------------------------------------

class VoterElectionResultsView(TemplateView):
    """Public results page for voters who have cast their votes.

    Shows live results during active elections (with "not final" warning)
    and final results after election concludes. Includes blockchain
    verification info and restricted exports (none for voters).
    """
    template_name = 'voting/results.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        try:
            election = Election.objects.get(election_uuid=kwargs['election_uuid'])
        except Election.DoesNotExist:
            ctx['election_not_found'] = True
            return ctx

        if not election.allow_voter_results_view:
            ctx['access_denied'] = True
            return ctx

        # A voter can only view results if the election is at least active
        status = election.current_status
        if status in (Election.STATUS_PRE_LAUNCH, Election.STATUS_INACTIVE):
            ctx['election_not_started'] = True
            ctx['election'] = election
            return ctx

        # Determine if election is ongoing or ended
        is_active = status == Election.STATUS_ACTIVE
        is_concluded = status == Election.STATUS_CONCLUDED

        # Efficient: one annotated query per post instead of N+1
        posts = election.posts.order_by('order', 'created_at')
        results = {}
        for post in posts:
            candidates_qs = (
                post.candidates
                .annotate(vote_count=Count('votes'))
                .order_by('-vote_count', 'name')
            )
            total = sum(c.vote_count for c in candidates_qs)
            results[post.pk] = {
                'post': post,
                'candidates': [
                    {
                        'candidate': c,
                        'votes': c.vote_count,
                        'percentage': round(c.vote_count / total * 100, 1) if total else 0,
                    }
                    for c in candidates_qs
                ],
                'total_votes': total,
            }

        # Turnout stats
        from apps.voting.models import VoterCredential as VC
        total_voters = VC.objects.filter(election=election, is_revoked=False).count()
        total_votes = VC.objects.filter(election=election, has_voted=True, is_revoked=False).count()
        turnout_pct = round(total_votes / total_voters * 100, 1) if total_voters else 0

        # Blockchain info
        from apps.voting.models import Vote
        voter_hash = self.request.session.get('voter_hash', '')
        voter_tx = None
        if voter_hash:
            # Find voter's blockchain TX via double-hashed voter_hash
            import hashlib
            original_hashes = Vote.objects.filter(
                election=election,
            ).values_list('voter_hash', flat=True).distinct()
            for vh in original_hashes:
                if hashlib.sha256(vh.encode()).hexdigest()[:16] == voter_hash:
                    tx = Vote.objects.filter(
                        election=election, voter_hash=vh, blockchain_tx_hash__isnull=False
                    ).exclude(blockchain_tx_hash='').values_list('blockchain_tx_hash', flat=True).first()
                    if tx:
                        voter_tx = tx
                    break

        # Blockchain explorer params
        from django.conf import settings
        solana_explorer_url = getattr(settings, 'SOLANA_EXPLORER_URL', '')
        solana_network = getattr(settings, 'SOLANA_NETWORK', 'devnet')
        solana_cluster_param = _solana_cluster_param()

        ctx.update({
            'election': election,
            'results': results,
            'posts': posts,
            'is_active': is_active,
            'is_concluded': is_concluded,
            'total_voters': total_voters,
            'total_votes': total_votes,
            'turnout_pct': turnout_pct,
            'total_posts': posts.count(),
            'voter_hash': voter_hash,
            'voter_tx': voter_tx,
            'SOLANA_EXPLORER_URL': solana_explorer_url,
            'SOLANA_NETWORK': solana_network,
            'SOLANA_CLUSTER_PARAM': solana_cluster_param,
        })
        return ctx
