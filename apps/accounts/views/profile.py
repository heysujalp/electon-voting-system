"""
ElectON v2 — Profile management views (account settings, update, delete).
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.accounts.constants import SECURITY_QUESTIONS, SECURITY_QUESTIONS_REQUIRED, MIN_ANSWER_LENGTH, MAX_ANSWER_LENGTH, RATE_LIMITS
from apps.accounts.forms import UpdateFullNameForm, UpdatePasswordForm, UpdateUsernameForm, SecurityQuestionsSetupForm
from apps.accounts.models import SecurityQuestion
from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.audit.services.audit_service import AuditService

logger = logging.getLogger('electon')
User = get_user_model()


def _check_password_rate_limit(request):
    """Shared rate limiter for all profile endpoints that verify a password.

    Returns ``(allowed: bool, error_response: JsonResponse | None)``.
    """
    ip = get_client_ip(request)
    rl_id = f'{request.user.pk}_{ip}'
    limits = RATE_LIMITS.get('settings_password_verify', {'max_attempts': 5, 'window_seconds': 300})
    limiter = RateLimitService('settings_pw_verify', limits['max_attempts'], limits['window_seconds'])
    if not limiter.is_allowed(rl_id):
        retry = limiter.get_retry_after(rl_id)
        return False, JsonResponse({'success': False, 'error': f'Too many attempts. Try again in {retry} seconds.'}, status=429)
    return True, None


def _record_password_failure(request):
    """Record a failed password attempt for rate limiting."""
    ip = get_client_ip(request)
    rl_id = f'{request.user.pk}_{ip}'
    limits = RATE_LIMITS.get('settings_password_verify', {'max_attempts': 5, 'window_seconds': 300})
    limiter = RateLimitService('settings_pw_verify', limits['max_attempts'], limits['window_seconds'])
    limiter.record_attempt(rl_id)


class AccountSettingsView(LoginRequiredMixin, View):
    """Display account settings page with sidebar navigation."""
    template_name = 'accounts/settings.html'

    def get(self, request):
        user = request.user
        security_questions = list(user.security_questions.all())

        # Build security questions form for update
        sq_form = SecurityQuestionsSetupForm()

        # Subscription / limits from plan service
        from apps.subscriptions.services import PlanLimitService
        usage = PlanLimitService.get_usage_summary(user)

        context = {
            'user': user,
            'full_name_form': UpdateFullNameForm(initial={'full_name': user.full_name}),
            'username_form': UpdateUsernameForm(initial={'username': user.username}),
            'password_form': UpdatePasswordForm(user=user),
            'security_questions': security_questions,
            'sq_form': sq_form,
            'all_security_questions': SECURITY_QUESTIONS,
            'sq_required': SECURITY_QUESTIONS_REQUIRED,
            'sq_range': range(1, SECURITY_QUESTIONS_REQUIRED + 1),
            # Plan-based usage data
            'usage': usage,
            'election_count': usage['elections_used'],
            'max_elections': usage['elections_limit'],
            'max_posts': usage['max_posts'],
            'max_candidates': usage['max_candidates'],
            'max_voters': usage['max_voters'],
            # Cooldown info
            'can_change_email': user.can_change_email(),
            'can_change_username': user.can_change_username(),
            'next_email_change': user.next_email_change_date(),
            'next_username_change': user.next_username_change_date(),
        }
        return render(request, self.template_name, context)


class UpdateFullNameView(LoginRequiredMixin, View):
    """Update the user's full name (requires password)."""

    def post(self, request):
        allowed, err_resp = _check_password_rate_limit(request)
        if not allowed:
            return err_resp

        password = request.POST.get('password', '')
        if not request.user.check_password(password):
            _record_password_failure(request)
            return JsonResponse({'success': False, 'error': 'Incorrect password.'}, status=400)

        form = UpdateFullNameForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

        request.user.full_name = form.cleaned_data['full_name']
        request.user.save(update_fields=['full_name', 'updated_at'])

        AuditService.log('account_update', request=request, user=request.user, field='full_name')
        return JsonResponse({'success': True, 'message': 'Full name updated.', 'value': request.user.full_name})


class UpdateUsernameView(LoginRequiredMixin, View):
    """Update the user's username (requires password, 6-month cooldown)."""

    def post(self, request):
        user = request.user

        allowed, err_resp = _check_password_rate_limit(request)
        if not allowed:
            return err_resp

        # Cooldown check
        if not user.can_change_username():
            next_date = user.next_username_change_date()
            return JsonResponse({
                'success': False,
                'error': f'Username can only be changed once every 6 months. Next change available on {next_date.strftime("%B %d, %Y")}.',
            }, status=400)

        # Password verification
        password = request.POST.get('password', '')
        if not user.check_password(password):
            _record_password_failure(request)
            return JsonResponse({'success': False, 'error': 'Incorrect password.'}, status=400)

        form = UpdateUsernameForm(request.POST, current_user=user)
        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

        old_username = user.username
        user.username = form.cleaned_data['username']
        user.username_last_changed = timezone.now()
        user.save(update_fields=['username', 'username_last_changed', 'updated_at'])

        AuditService.log(
            'account_update', request=request, user=user,
            field='username', old_value=old_username,
        )
        return JsonResponse({'success': True, 'message': 'Username updated.', 'value': user.username})


class CheckUsernameView(LoginRequiredMixin, View):
    """AJAX endpoint to check username availability."""

    def get(self, request):
        username = request.GET.get('username', '').strip()
        if not username:
            return JsonResponse({'available': False, 'error': 'Username is required.'})
        if username.lower() == request.user.username.lower():
            return JsonResponse({'available': True, 'current': True})
        exists = User.objects.filter(username__iexact=username).exists()
        return JsonResponse({'available': not exists})


class UpdateEmailView(LoginRequiredMixin, View):
    """Step 1: Validate new email & send verification code (no password yet)."""

    def post(self, request):
        user = request.user

        # Rate limit email code sending
        ip = get_client_ip(request)
        rl_id = f'{user.pk}_{ip}'
        limits = RATE_LIMITS.get('settings_email_code', {'max_attempts': 3, 'window_seconds': 600})
        limiter = RateLimitService('settings_email_code', limits['max_attempts'], limits['window_seconds'])
        if not limiter.is_allowed(rl_id):
            retry = limiter.get_retry_after(rl_id)
            return JsonResponse({'success': False, 'error': f'Too many requests. Try again in {retry} seconds.'}, status=429)

        # Cooldown check
        if not user.can_change_email():
            next_date = user.next_email_change_date()
            return JsonResponse({
                'success': False,
                'error': f'Email can only be changed once every 6 months. Next change available on {next_date.strftime("%B %d, %Y")}.',
            }, status=400)

        new_email = request.POST.get('email', '').strip().lower()
        if not new_email:
            return JsonResponse({'success': False, 'error': 'Email is required.'}, status=400)

        # Validate email format
        try:
            validate_email(new_email)
        except DjangoValidationError:
            return JsonResponse({'success': False, 'error': 'Please enter a valid email address.'}, status=400)

        if new_email == user.email:
            return JsonResponse({'success': False, 'error': 'This is already your current email.'}, status=400)

        # Check uniqueness
        if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
            return JsonResponse({'success': False, 'error': 'This email is already in use.'}, status=400)

        # Generate 6-digit verification code via TokenService (avoid private API)
        from apps.accounts.services.token_service import TokenService
        code, code_hash = TokenService.generate_verification_code()

        # Store pending email change
        user.pending_email = new_email
        user.pending_email_code_hash = code_hash
        from datetime import timedelta
        user.pending_email_code_expires = timezone.now() + timedelta(minutes=15)
        user.save(update_fields=['pending_email', 'pending_email_code_hash', 'pending_email_code_expires', 'updated_at'])

        # Send verification code to new email
        from apps.notifications.services.email_service import EmailService
        EmailService.send_email(
            recipient=new_email,
            subject='ElectON — Verify Your New Email',
            template='verification.html',
            context={
                'verification_code': code,
                'user_name': user.username,
                'expiry_minutes': 15,
                'site_name': 'ElectON',
            },
        )

        logger.info("Email change verification sent: user=%s new_email=%s", user.username, new_email)
        limiter.record_attempt(rl_id)
        return JsonResponse({
            'success': True,
            'message': f'Verification code sent to {new_email}. Please check your inbox.',
        })


class VerifyEmailChangeView(LoginRequiredMixin, View):
    """Step 2: Verify the code + password, then apply email change."""

    def post(self, request):
        user = request.user

        if not user.pending_email or not user.pending_email_code_hash:
            return JsonResponse({'success': False, 'error': 'No pending email change.'}, status=400)

        if user.pending_email_code_expires and timezone.now() >= user.pending_email_code_expires:
            user.pending_email = None
            user.pending_email_code_hash = None
            user.pending_email_code_expires = None
            user.save(update_fields=['pending_email', 'pending_email_code_hash', 'pending_email_code_expires', 'updated_at'])
            return JsonResponse({'success': False, 'error': 'Verification code has expired. Please request a new one.'}, status=400)

        code = request.POST.get('code', '').strip()
        if not code:
            return JsonResponse({'success': False, 'error': 'Verification code is required.'}, status=400)

        # Password verification (required at this step)
        password = request.POST.get('password', '')
        if not password or not user.check_password(password):
            return JsonResponse({'success': False, 'error': 'Incorrect password.'}, status=400)

        import hmac as _hmac
        from apps.accounts.services.token_service import TokenService
        if not _hmac.compare_digest(TokenService._hash_value(code), user.pending_email_code_hash):
            # Invalidate pending change after wrong code to prevent brute-force
            user.pending_email = None
            user.pending_email_code_hash = None
            user.pending_email_code_expires = None
            user.save(update_fields=['pending_email', 'pending_email_code_hash', 'pending_email_code_expires', 'updated_at'])
            return JsonResponse({'success': False, 'error': 'Invalid verification code. Please request a new one.'}, status=400)

        # Apply the email change
        old_email = user.email
        user.email = user.pending_email
        user.email_verified = True
        user.email_last_changed = timezone.now()
        user.pending_email = None
        user.pending_email_code_hash = None
        user.pending_email_code_expires = None
        user.save(update_fields=[
            'email', 'email_verified', 'email_last_changed',
            'pending_email', 'pending_email_code_hash', 'pending_email_code_expires',
            'updated_at',
        ])

        AuditService.log('account_update', request=request, user=user, field='email', old_value=old_email)
        logger.info("Email changed: user=%s old=%s new=%s", user.username, old_email, user.email)
        return JsonResponse({'success': True, 'message': 'Email updated successfully.', 'value': user.email})


class UpdatePasswordView(LoginRequiredMixin, View):
    """Update the user's password (requires current password)."""

    def post(self, request):
        allowed, err_resp = _check_password_rate_limit(request)
        if not allowed:
            return err_resp

        form = UpdatePasswordForm(request.POST, user=request.user)
        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

        if not request.user.check_password(form.cleaned_data['current_password']):
            _record_password_failure(request)
            return JsonResponse({
                'success': False,
                'errors': {'current_password': ['Current password is incorrect.']},
            }, status=400)

        request.user.set_password(form.cleaned_data['new_password'])
        request.user.password_last_changed = timezone.now()
        request.user.save(update_fields=['password', 'password_last_changed', 'updated_at'])
        update_session_auth_hash(request, request.user)

        AuditService.log('password_change', request=request, user=request.user)
        return JsonResponse({'success': True, 'message': 'Password updated successfully.'})


class DeleteAccountView(LoginRequiredMixin, View):
    """Delete the user's account permanently. Requires password + username confirmation."""

    def post(self, request):
        allowed, err_resp = _check_password_rate_limit(request)
        if not allowed:
            return err_resp

        # Step 1: Verify password
        password = request.POST.get('password', '')
        if not request.user.check_password(password):
            _record_password_failure(request)
            return JsonResponse({
                'success': False,
                'error': 'Incorrect password.',
            }, status=400)

        # Step 2: Verify username confirmation
        username_confirm = request.POST.get('username_confirm', '').strip()
        if username_confirm != request.user.username:
            return JsonResponse({
                'success': False,
                'error': 'Username does not match. Please type your exact username to confirm.',
            }, status=400)

        user = request.user

        # Block deletion if user has active (launched, not ended) elections
        from apps.elections.models import Election
        from django.utils import timezone as tz_util
        active = Election.objects.filter(
            created_by=user, is_launched=True, end_time__gt=tz_util.now(),
        ).count()
        if active:
            return JsonResponse({
                'success': False,
                'error': (
                    f'You have {active} active election{"s" if active != 1 else ""}. '
                    'Please end or delete all active elections before deleting your account.'
                ),
            }, status=400)

        AuditService.log('account_delete', request=request, user=user)

        # Logout and delete user
        logout(request)
        user.delete()

        logger.info("Account deleted: user=%s email=%s", user.username, user.email)
        return JsonResponse({'success': True, 'redirect': '/'})


class VerifyPasswordView(LoginRequiredMixin, View):
    """Simple endpoint to verify the user's password (used for multi-step flows)."""

    def post(self, request):
        # Rate limit password verification attempts
        ip = get_client_ip(request)
        rl_id = f'{request.user.pk}_{ip}'
        limits = RATE_LIMITS.get('settings_password_verify', {'max_attempts': 5, 'window_seconds': 300})
        limiter = RateLimitService('settings_pw_verify', limits['max_attempts'], limits['window_seconds'])
        if not limiter.is_allowed(rl_id):
            retry = limiter.get_retry_after(rl_id)
            return JsonResponse({'success': False, 'error': f'Too many attempts. Try again in {retry} seconds.'}, status=429)

        password = request.POST.get('password', '')
        if not password:
            return JsonResponse({'success': False, 'error': 'Password is required.'}, status=400)
        if not request.user.check_password(password):
            limiter.record_attempt(rl_id)
            return JsonResponse({'success': False, 'error': 'Incorrect password.'}, status=400)

        limiter.reset(rl_id)
        return JsonResponse({'success': True})


class UpdateSecurityQuestionsView(LoginRequiredMixin, View):
    """Update the user's security questions and answers."""

    def post(self, request):
        allowed, err_resp = _check_password_rate_limit(request)
        if not allowed:
            return err_resp

        form = SecurityQuestionsSetupForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

        # Verify current password before allowing security question change
        password = request.POST.get('current_password', '')
        if not request.user.check_password(password):
            _record_password_failure(request)
            return JsonResponse({
                'success': False,
                'error': 'Current password is incorrect.',
            }, status=400)

        # Delete old questions and create new ones atomically
        with transaction.atomic():
            request.user.security_questions.all().delete()

            for i in range(1, SECURITY_QUESTIONS_REQUIRED + 1):
                question_key = form.cleaned_data[f'question_{i}']
                answer = form.cleaned_data[f'answer_{i}']
                sq = SecurityQuestion(user=request.user, question_key=question_key)
                sq.answer_hash = SecurityQuestion.hash_answer(answer)
                sq.save()

        AuditService.log('account_update', request=request, user=request.user, field='security_questions')
        return JsonResponse({'success': True, 'message': 'Security questions updated successfully.'})