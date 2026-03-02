"""
ElectON v2 — Password reset views (4-step flow).

Step 1: Enter email → validate account exists → create session → redirect Step 2
Step 2: Answer security questions → if correct, send reset code → redirect Step 3
Step 3: Enter code from email → verify → redirect Step 4
Step 4: Set new password → clear session → redirect to login
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.constants import RATE_LIMITS, get_resend_cooldown
from apps.accounts.forms import (
    EmailVerificationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    SecurityQuestionsVerifyForm,
)
from apps.accounts.models import PasswordResetSession
from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.accounts.services.token_service import TokenService
from apps.audit.services.audit_service import AuditService

logger = logging.getLogger('electon.security')
User = get_user_model()

# ─── Helpers ─────────────────────────────────────────────────────

def _get_reset_session(request):
    """Return the PasswordResetSession for the current flow, or None."""
    sid = request.session.get('reset_session_id')
    if not sid:
        return None
    return PasswordResetSession.objects.filter(session_id=sid).first()


def _abort_reset(request, msg='Session expired. Please start again.'):
    """Clear reset session data and redirect to Step 1."""
    request.session.pop('reset_session_id', None)
    request.session.pop('reset_email', None)
    messages.error(request, msg)
    return redirect('accounts:forgot_password')


# ─── Step 1 — Enter Email ────────────────────────────────────────

class ForgotPasswordView(View):
    """Step 1: Enter email to begin password reset."""
    template_name = 'auth/admin/forgot/forgot_password.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')
        return render(request, self.template_name, {'form': ForgotPasswordForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')

        client_ip = get_client_ip(request)
        rl_config = RATE_LIMITS['password_reset']
        limiter = RateLimitService('password_reset', **rl_config)

        if not limiter.is_allowed(client_ip):
            messages.error(request, 'Too many reset requests. Please try again later.')
            return render(request, self.template_name, {'form': ForgotPasswordForm()})

        form = ForgotPasswordForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        email = form.cleaned_data['email']
        limiter.record_attempt(client_ip)

        user = User.objects.filter(email__iexact=email, email_verified=True).first()

        if user and user.security_questions.exists():
            # Clean up any old reset sessions for this email
            PasswordResetSession.objects.filter(email__iexact=email).delete()

            # Create new reset session
            session_id = TokenService.generate_session_id()
            PasswordResetSession.objects.create(
                email=email,
                session_id=session_id,
                ip_address=client_ip,
            )

            request.session['reset_session_id'] = session_id
            request.session['reset_email'] = email

        # Uniform response regardless of whether user exists (prevents enumeration)
        messages.info(request, 'If an account exists with that email, you will receive reset instructions.')
        return redirect('accounts:reset_verify_questions')


# ─── Step 2 — Security Questions ─────────────────────────────────

class ResetVerifyQuestionsView(View):
    """Step 2: Verify security questions, then send reset code."""
    template_name = 'auth/admin/forgot/forgot_verify_questions.html'

    def get(self, request):
        session = _get_reset_session(request)
        if not session:
            return _abort_reset(request)

        user = User.objects.filter(email__iexact=session.email, email_verified=True).first()
        if not user:
            return _abort_reset(request)

        sq_keys = list(user.security_questions.values_list('question_key', flat=True))
        return render(request, self.template_name, {
            'form': SecurityQuestionsVerifyForm(question_keys=sq_keys),
            'email': session.email,
        })

    def post(self, request):
        session = _get_reset_session(request)
        if not session:
            return _abort_reset(request)

        user = User.objects.filter(email__iexact=session.email, email_verified=True).first()
        if not user:
            return _abort_reset(request)

        sq_list = list(user.security_questions.all())
        sq_keys = [sq.question_key for sq in sq_list]

        form = SecurityQuestionsVerifyForm(request.POST, question_keys=sq_keys)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
            })

        # Verify each answer
        for i, sq in enumerate(sq_list, start=1):
            answer = form.cleaned_data[f'answer_{i}']
            if not sq.verify_answer(answer):
                messages.error(request, 'One or more answers are incorrect.')
                return render(request, self.template_name, {
                    'form': SecurityQuestionsVerifyForm(question_keys=sq_keys),
                    'email': session.email,
                })

        # All correct — generate and send reset code
        code, code_hash = TokenService.generate_verification_code()
        expiry = TokenService.get_expiry(
            settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        )

        session.security_questions_verified = True
        session.verification_code_hash = code_hash
        session.code_expires_at = expiry
        session.save()

        # Send code email
        from apps.notifications.services.email_service import EmailService
        expiry_seconds = settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        EmailService.send_email(
            recipient=session.email,
            subject='ElectON — Password Reset Code',
            template='password_reset.html',
            context={
                'reset_code': code,
                'user_name': user.username,
                'expiry_minutes': expiry_seconds // 60,
                'site_name': 'ElectON',
            },
        )
        logger.info("Password reset code sent for user=%s", user.username)

        return redirect('accounts:reset_verify_code')


# ─── Step 3 — Enter Code ─────────────────────────────────────────

class ResetVerifyCodeView(View):
    """Step 3: Enter the 6-digit code sent to email."""
    template_name = 'auth/admin/forgot/forgot_verify_code.html'

    def get(self, request):
        session = _get_reset_session(request)
        if not session or not session.security_questions_verified:
            return _abort_reset(request)

        return render(request, self.template_name, {
            'form': EmailVerificationForm(),
            'email': session.email,
            'can_resend': session.can_resend(),
        })

    def post(self, request):
        session = _get_reset_session(request)
        if not session or not session.security_questions_verified:
            return _abort_reset(request)

        # Handle resend
        if 'resend' in request.POST:
            return self._handle_resend(request, session)

        form = EmailVerificationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
                'can_resend': session.can_resend(),
            })

        code = form.cleaned_data['code']

        # Rate limit code verification attempts (BE-04)
        client_ip = get_client_ip(request)
        code_limiter = RateLimitService(
            'email_verification', **RATE_LIMITS['email_verification']
        )
        if not code_limiter.is_allowed(f'{client_ip}:{session.session_id}'):
            messages.error(request, 'Too many verification attempts. Please request a new code.')
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
                'can_resend': session.can_resend(),
            })

        # Check expiry
        if session.is_code_expired():
            messages.error(request, 'Code has expired. Please request a new one.')
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
                'can_resend': True,
            })

        # Check code already used
        if session.code_verified:
            messages.error(request, 'This code has already been used.')
            return _abort_reset(request)

        # Verify code
        if not session.verification_code_hash or \
           not TokenService.verify_code(code, session.verification_code_hash):
            code_limiter.record_attempt(f'{client_ip}:{session.session_id}')
            messages.error(request, 'Invalid code. Please try again.')
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
                'can_resend': session.can_resend(),
            })

        # Mark code as used — cannot be reused
        session.code_verified = True
        session.verification_code_hash = None  # Clear hash so code cant be replayed
        session.save()

        return redirect('accounts:reset_password')

    def _handle_resend(self, request, session):
        """Resend reset code with progressive cooldown."""
        if not session.can_resend():
            messages.warning(request, 'Please wait before requesting a new code.')
            return redirect('accounts:reset_verify_code')

        user = User.objects.filter(email__iexact=session.email, email_verified=True).first()
        if not user:
            return _abort_reset(request)

        code, code_hash = TokenService.generate_verification_code()
        expiry = TokenService.get_expiry(
            settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        )
        cooldown = get_resend_cooldown(session.resend_attempts)

        session.verification_code_hash = code_hash
        session.code_expires_at = expiry
        session.code_verified = False  # Reset the used flag for the new code
        session.resend_attempts += 1
        session.next_resend_available_at = TokenService.get_expiry(cooldown)
        session.save()

        from apps.notifications.services.email_service import EmailService
        expiry_seconds = settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        EmailService.send_email(
            recipient=session.email,
            subject='ElectON — New Password Reset Code',
            template='password_reset.html',
            context={
                'reset_code': code,
                'user_name': user.username,
                'expiry_minutes': expiry_seconds // 60,
                'site_name': 'ElectON',
            },
        )

        messages.success(request, 'A new reset code has been sent.')
        return redirect('accounts:reset_verify_code')


# ─── Step 4 — Set New Password ───────────────────────────────────

class ResetPasswordView(View):
    """Step 4: Enter new password."""
    template_name = 'auth/admin/forgot/forgot_new_password.html'

    def get(self, request):
        session = _get_reset_session(request)
        if not session or not session.code_verified:
            return _abort_reset(request)

        user = User.objects.filter(email__iexact=session.email, email_verified=True).first()
        if not user:
            return _abort_reset(request)

        return render(request, self.template_name, {
            'form': ResetPasswordForm(user=user),
            'email': session.email,
        })

    def post(self, request):
        session = _get_reset_session(request)
        if not session or not session.code_verified:
            return _abort_reset(request)

        user = User.objects.filter(email__iexact=session.email, email_verified=True).first()
        if not user:
            return _abort_reset(request)

        form = ResetPasswordForm(request.POST, user=user)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'email': session.email,
            })

        # Set new password
        user.set_password(form.cleaned_data['password'])
        user.password_last_changed = timezone.now()
        user.save(update_fields=['password', 'password_last_changed', 'updated_at'])

        # Clean up
        session.delete()
        request.session.pop('reset_session_id', None)
        request.session.pop('reset_email', None)

        AuditService.log('password_reset', request=request, user=user)
        messages.success(request, 'Password reset successful! Please log in with your new password.')
        return redirect('accounts:login')
