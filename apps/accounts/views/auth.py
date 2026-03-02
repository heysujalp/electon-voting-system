"""
ElectON v2 — Authentication views (login, logout, admin login verification).
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.accounts.constants import RATE_LIMITS
from apps.accounts.forms import AdminLoginForm, AdminLoginVerificationForm
from apps.accounts.models import AdminLoginVerification
from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.accounts.services.token_service import TokenService
from apps.audit.services.audit_service import AuditService

logger = logging.getLogger('electon.security')
User = get_user_model()


class AdminLoginView(View):
    """Admin login with rate limiting + optional 2FA trigger."""
    template_name = 'auth/admin/login/admin_login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')
        return render(request, self.template_name, {'form': AdminLoginForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('elections:manage')

        form = AdminLoginForm(request.POST)
        client_ip = get_client_ip(request)
        rl_config = RATE_LIMITS['admin_login']
        limiter = RateLimitService('admin_login', **rl_config)

        if not limiter.is_allowed(client_ip):
            AuditService.log('login_failure', request=request, reason='rate_limited')
            messages.error(request, 'Too many login attempts. Please try again later.')
            return render(request, self.template_name, {'form': form})

        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        username = form.cleaned_data['username']
        password = form.cleaned_data['password']

        user = authenticate(request, username=username, password=password)

        if user is None:
            limiter.record_attempt(client_ip)
            # Also track for 2FA trigger (separate 1-hour window)
            trigger_config = RATE_LIMITS['admin_verification_trigger']
            trigger_limiter = RateLimitService('admin_verification_trigger', **trigger_config)
            trigger_limiter.record_attempt(client_ip)
            AuditService.log('login_failure', request=request, username=username)
            # Generic error — no user enumeration
            messages.error(request, 'Invalid username or password.')
            return render(request, self.template_name, {'form': form})

        if not user.email_verified:
            messages.error(request, 'Please verify your email address first.')
            return render(request, self.template_name, {'form': form})

        # Check if 2FA is required (10+ failed attempts in last hour)
        if self._needs_admin_verification(user, client_ip):
            return self._initiate_admin_verification(request, user, client_ip)

        # Successful login
        login(request, user)
        limiter.reset(client_ip)
        AuditService.log('login_success', request=request, user=user)
        return redirect('elections:manage')

    def _needs_admin_verification(self, user, client_ip) -> bool:
        """Check if admin 2FA should be triggered (10+ failures in 1 hour)."""
        trigger_config = RATE_LIMITS['admin_verification_trigger']
        limiter = RateLimitService('admin_verification_trigger', **trigger_config)
        return not limiter.is_allowed(client_ip)

    def _initiate_admin_verification(self, request, user, client_ip):
        """Create 2FA verification and send code via email."""
        code, code_hash = TokenService.generate_verification_code()
        expiry = TokenService.get_expiry(settings.SECURITY_SETTINGS['VERIFICATION_CODE_EXPIRY'])

        AdminLoginVerification.objects.create(
            user=user,
            verification_code_hash=code_hash,
            code_expires_at=expiry,
            ip_address=client_ip,
        )

        # Store user PK in session for verification step
        request.session['admin_verification_user_id'] = user.pk
        request.session['admin_verification_ip'] = client_ip

        # Send email (import locally to avoid circular imports)
        from apps.notifications.services.email_service import EmailService
        expiry_seconds = settings.SECURITY_SETTINGS.get('VERIFICATION_CODE_EXPIRY', 900)
        EmailService.send_email(
            recipient=user.email,
            subject='ElectON — Login Verification Code',
            template='admin_2fa.html',
            context={
                'verification_code': code,
                'user_name': user.full_name or user.username,
                'expiry_minutes': expiry_seconds // 60,
            },
        )

        logger.info("Admin 2FA triggered for user=%s ip=%s", user.username, client_ip)
        return redirect('accounts:admin_login_verification')


class AdminLoginVerificationView(View):
    """Handle 2FA code entry for admin login."""
    template_name = 'auth/admin/login/login_verify.html'

    def get(self, request):
        if 'admin_verification_user_id' not in request.session:
            return redirect('accounts:login')
        return render(request, self.template_name, {'form': AdminLoginVerificationForm()})

    def post(self, request):
        user_id = request.session.get('admin_verification_user_id')
        if not user_id:
            return redirect('accounts:login')

        form = AdminLoginVerificationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        code = form.cleaned_data['code']

        # Find the latest active verification for this user
        verification = (
            AdminLoginVerification.objects
            .filter(user_id=user_id, is_verified=False)
            .order_by('-created_at')
            .first()
        )

        if not verification or verification.is_expired():
            messages.error(request, 'Verification expired. Please log in again.')
            request.session.pop('admin_verification_user_id', None)
            return redirect('accounts:login')

        if not verification.has_attempts_remaining():
            messages.error(request, 'Too many failed attempts. Please log in again.')
            request.session.pop('admin_verification_user_id', None)
            return redirect('accounts:login')

        if not TokenService.verify_code(code, verification.verification_code_hash):
            verification.attempts += 1
            verification.save(update_fields=['attempts'])
            messages.error(request, 'Invalid code. Please try again.')
            return render(request, self.template_name, {'form': form})

        # Verification successful
        verification.is_verified = True
        verification.save(update_fields=['is_verified'])

        # Validate that 2FA is completed from the same IP that initiated login
        original_ip = request.session.get('admin_verification_ip')
        current_ip = get_client_ip(request)
        if original_ip and original_ip != current_ip:
            logger.warning(
                '2FA IP mismatch: started from %s, completed from %s (user_id=%s)',
                original_ip, current_ip, user_id,
            )
            messages.error(request, 'Security check failed — IP address changed. Please log in again.')
            request.session.pop('admin_verification_user_id', None)
            request.session.pop('admin_verification_ip', None)
            return redirect('accounts:login')

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, 'User not found. Please log in again.')
            request.session.pop('admin_verification_user_id', None)
            return redirect('accounts:login')
        login(request, user)

        # Reset login rate limiter after successful 2FA
        client_ip = request.session.get('admin_verification_ip') or get_client_ip(request)
        rl_config = RATE_LIMITS['admin_login']
        RateLimitService('admin_login', **rl_config).reset(client_ip)
        # Also reset the 2FA trigger limiter
        trigger_config = RATE_LIMITS['admin_verification_trigger']
        RateLimitService('admin_verification_trigger', **trigger_config).reset(client_ip)

        # Clean up session
        request.session.pop('admin_verification_user_id', None)
        request.session.pop('admin_verification_ip', None)

        AuditService.log('login_success', request=request, user=user, method='2fa')
        return redirect('elections:manage')


class LogoutView(View):
    """Logout and destroy session completely."""

    def post(self, request):
        if request.user.is_authenticated:
            AuditService.log('logout', request=request, user=request.user)
        logout(request)  # logout() already flushes the session
        response = redirect('public_home')
        # Prevent browser back-button from showing authenticated pages
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        # Clear session cookie explicitly
        response.delete_cookie(settings.SESSION_COOKIE_NAME)
        return response

    def get(self, request):
        """GET logout redirects to home — actual logout requires POST (CSRF protection)."""
        return redirect('public_home')
