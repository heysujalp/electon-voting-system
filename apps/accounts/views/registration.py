"""
ElectON v2 — Registration & email verification views.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.hashers import make_password
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.accounts.constants import (
    RATE_LIMITS,
    SECURITY_QUESTIONS_REQUIRED,
    get_resend_cooldown,
)
from apps.accounts.forms import (
    EmailVerificationForm,
    RegistrationForm,
    SecurityQuestionsSetupForm,
)
from apps.accounts.models import EmailVerificationSession, SecurityQuestion
from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.accounts.services.token_service import TokenService
from apps.audit.services.audit_service import AuditService

logger = logging.getLogger('electon')
User = get_user_model()


class RegisterView(View):
    """Handle admin account registration → initiates email verification."""
    template_name = 'auth/admin/registration/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')
        return render(request, self.template_name, {'form': RegistrationForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')

        client_ip = get_client_ip(request)
        rl_config = RATE_LIMITS['registration']
        limiter = RateLimitService('registration', **rl_config)

        if not limiter.is_allowed(client_ip):
            messages.error(request, 'Too many registration attempts. Please try again later.')
            return render(request, self.template_name, {'form': RegistrationForm()})

        form = RegistrationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        limiter.record_attempt(client_ip)

        # Generate verification session (don't create the user yet)
        code, code_hash = TokenService.generate_verification_code()
        session_id = TokenService.generate_session_id()
        expiry = TokenService.get_expiry(settings.SECURITY_SETTINGS['VERIFICATION_CODE_EXPIRY'])

        # Clean up any existing sessions for this email
        EmailVerificationSession.objects.filter(email=form.cleaned_data['email']).delete()

        # Create verification session with pending data
        verification_session = EmailVerificationSession.objects.create(
            email=form.cleaned_data['email'],
            session_id=session_id,
            verification_code_hash=code_hash,
            code_expires_at=expiry,
            pending_username=form.cleaned_data['username'],
            pending_full_name=form.cleaned_data['full_name'],
            pending_password_hash=make_password(form.cleaned_data['password']),
            ip_address=client_ip,
        )

        # Store session ID for verification page
        request.session['verification_session_id'] = session_id
        request.session['verification_email'] = form.cleaned_data['email']

        # Send verification email
        from apps.notifications.services.email_service import EmailService
        expiry_seconds = settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        EmailService.send_email(
            recipient=form.cleaned_data['email'],
            subject='ElectON — Verify Your Email',
            template='verification.html',
            context={
                'verification_code': code,
                'user_name': form.cleaned_data['username'],
                'expiry_minutes': expiry_seconds // 60,
                'site_name': 'ElectON',
            },
        )

        logger.info("Registration verification sent to %s", form.cleaned_data['email'])
        return redirect('accounts:email_verification')


class EmailVerificationView(View):
    """Handle OTP code entry for email verification."""
    template_name = 'auth/admin/registration/register_verify_email.html'

    def get(self, request):
        session_id = request.session.get('verification_session_id')
        if not session_id:
            messages.error(request, 'No verification session found. Please register again.')
            return redirect('accounts:register')

        verification = EmailVerificationSession.objects.filter(session_id=session_id).first()
        if not verification:
            messages.error(request, 'Verification session expired. Please register again.')
            return redirect('accounts:register')

        context = {
            'form': EmailVerificationForm(),
            'email': verification.email,
            'can_resend': verification.can_resend(),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        session_id = request.session.get('verification_session_id')
        if not session_id:
            return redirect('accounts:register')

        verification = EmailVerificationSession.objects.filter(session_id=session_id).first()
        if not verification:
            messages.error(request, 'Verification session expired. Please register again.')
            return redirect('accounts:register')

        # Handle resend button
        if 'resend' in request.POST:
            return self._handle_resend(request, verification)

        form = EmailVerificationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'email': verification.email,
                'can_resend': verification.can_resend(),
            })

        code = form.cleaned_data['code']

        # Rate limit OTP verification attempts (BE-03)
        client_ip = get_client_ip(request)
        otp_limiter = RateLimitService(
            'email_verification', **RATE_LIMITS['email_verification']
        )
        if not otp_limiter.is_allowed(f'{client_ip}:{verification.session_id}'):
            messages.error(request, 'Too many verification attempts. Please request a new code.')
            return render(request, self.template_name, {
                'form': form,
                'email': verification.email,
                'can_resend': verification.can_resend(),
            })

        # Check expiry
        if verification.is_code_expired():
            messages.error(request, 'Verification code has expired. Please request a new one.')
            return render(request, self.template_name, {
                'form': form,
                'email': verification.email,
                'can_resend': True,
            })

        # Verify the code
        if not TokenService.verify_code(code, verification.verification_code_hash):
            otp_limiter.record_attempt(f'{client_ip}:{verification.session_id}')
            messages.error(request, 'Invalid verification code.')
            return render(request, self.template_name, {
                'form': form,
                'email': verification.email,
                'can_resend': verification.can_resend(),
            })

        # Code verified — mark session as email-verified, proceed to Step 3
        request.session['email_verified_for_registration'] = True
        return redirect('accounts:security_questions')

    def _handle_resend(self, request, verification):
        """Resend verification code with progressive cooldown."""
        if not verification.can_resend():
            messages.warning(request, 'Please wait before requesting a new code.')
            return redirect('accounts:email_verification')

        # Generate new code
        code, code_hash = TokenService.generate_verification_code()
        expiry = TokenService.get_expiry(settings.SECURITY_SETTINGS['VERIFICATION_CODE_EXPIRY'])
        cooldown = get_resend_cooldown(verification.resend_attempts)

        verification.verification_code_hash = code_hash
        verification.code_expires_at = expiry
        verification.resend_attempts += 1
        verification.next_resend_available_at = TokenService.get_expiry(cooldown)
        verification.save()

        # Send new code
        from apps.notifications.services.email_service import EmailService
        expiry_seconds = settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        EmailService.send_email(
            recipient=verification.email,
            subject='ElectON — New Verification Code',
            template='verification.html',
            context={
                'verification_code': code,
                'user_name': verification.pending_username,
                'expiry_minutes': expiry_seconds // 60,
                'site_name': 'ElectON',
            },
        )

        messages.success(request, 'A new verification code has been sent.')
        return redirect('accounts:email_verification')


class SecurityQuestionsView(View):
    """Step 3 — Set up security questions before account creation."""
    template_name = 'auth/admin/registration/register_security_questions.html'

    def get(self, request):
        session_id = request.session.get('verification_session_id')
        email_verified = request.session.get('email_verified_for_registration')

        if not session_id or not email_verified:
            messages.error(request, 'Please complete email verification first.')
            return redirect('accounts:register')

        verification = EmailVerificationSession.objects.filter(session_id=session_id).first()
        if not verification:
            messages.error(request, 'Registration session expired. Please register again.')
            return redirect('accounts:register')

        return render(request, self.template_name, {
            'form': SecurityQuestionsSetupForm(),
            'email': verification.email,
        })

    def post(self, request):
        session_id = request.session.get('verification_session_id')
        email_verified = request.session.get('email_verified_for_registration')

        if not session_id or not email_verified:
            messages.error(request, 'Please complete email verification first.')
            return redirect('accounts:register')

        verification = EmailVerificationSession.objects.filter(session_id=session_id).first()
        if not verification:
            messages.error(request, 'Registration session expired. Please register again.')
            return redirect('accounts:register')

        form = SecurityQuestionsSetupForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'email': verification.email,
            })

        # Create the user account
        from django.db import IntegrityError
        try:
            user = self._create_user(verification)
        except IntegrityError:
            logger.warning("Duplicate account race condition for %s", verification.email)
            messages.error(
                request,
                'An account with this email or username already exists. '
                'Please try logging in instead.',
            )
            return redirect('accounts:register')

        # Save security questions with hashed answers
        for i in range(1, SECURITY_QUESTIONS_REQUIRED + 1):
            question_key = form.cleaned_data[f'question_{i}']
            answer = form.cleaned_data[f'answer_{i}']
            SecurityQuestion.objects.create(
                user=user,
                question_key=question_key,
                answer_hash=SecurityQuestion.hash_answer(answer),
            )

        login(request, user)

        # Clean up session
        verification.delete()
        request.session.pop('verification_session_id', None)
        request.session.pop('verification_email', None)
        request.session.pop('email_verified_for_registration', None)

        AuditService.log('register', request=request, user=user)
        messages.success(request, 'Account created! Welcome to ElectON.')
        return redirect('elections:manage')

    @staticmethod
    def _create_user(verification: EmailVerificationSession):
        """Create user account from verified session data."""
        from django.db import IntegrityError
        try:
            user = User(
                username=verification.pending_username,
                email=verification.email,
                full_name=verification.pending_full_name,
                password=verification.pending_password_hash,  # Already hashed
                is_active=True,
                email_verified=True,
            )
            user.save()
            return user
        except IntegrityError:
            # Race condition — another request already created this account.
            # Re-raise so the caller can handle it safely instead of
            # returning a potentially different user (account takeover risk).
            raise IntegrityError(
                "An account with this email or username already exists. "
                "Please try logging in instead."
            )
