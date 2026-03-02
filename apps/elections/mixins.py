"""
ElectON v2 — Shared election mixins.

Single source of truth for the ``ElectionOwnerMixin`` previously
duplicated across elections, candidates, results, and notifications views.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from apps.accounts.services.rate_limit_service import RateLimitService
from electon.utils import get_client_ip
from apps.elections.models import Election


class ElectionOwnerMixin(LoginRequiredMixin):
    """
    Ensure the logged-in user owns the election.

    Provides ``get_election(election_uuid)`` which returns the ``Election``
    instance or raises ``PermissionDenied`` if the user is not the owner.
    """

    def get_election(self, election_uuid=None):
        uuid = election_uuid or self.kwargs.get('election_uuid')
        election = get_object_or_404(Election, election_uuid=uuid)
        if election.created_by != self.request.user:
            raise PermissionDenied("You don't have permission to manage this election.")
        return election


class PasswordVerifiedMixin:
    """
    Require the user's account password for destructive actions.

    Views mixing this in should call ``self.verify_password(request)``
    before executing the irreversible operation.  Returns ``(ok, error_msg)``.
    """
    _password_rate_limit_max = 5
    _password_rate_limit_window = 300  # 5 minutes

    def verify_password(self, request):
        # MED-08: Rate limit password verification attempts
        limiter = RateLimitService(
            'password_verify',
            max_attempts=self._password_rate_limit_max,
            window_seconds=self._password_rate_limit_window,
        )
        identifier = f"{request.user.pk}:{get_client_ip(request)}"
        if not limiter.is_allowed(identifier):
            return False, 'Too many attempts. Please wait and try again.'

        password = request.POST.get('password', '') or ''
        if not password:
            return False, 'Password is required for this action.'
        if not request.user.check_password(password):
            limiter.record_attempt(identifier)
            return False, 'Incorrect password.'
        limiter.reset(identifier)
        return True, None


class AjaxRateLimitMixin:
    """
    SEC-01: Rate-limit AJAX write endpoints to prevent abuse.

    Defaults to 30 requests per 60-second window per user+IP.
    Override ``rate_limit_max`` and ``rate_limit_window`` on the view class
    to customise.
    """
    rate_limit_max = 30       # max attempts in window
    rate_limit_window = 60    # seconds

    def dispatch(self, request, *args, **kwargs):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            identifier = f"{request.user.pk}:{get_client_ip(request)}"
            limiter = RateLimitService(
                f'ajax_{self.__class__.__name__}',
                max_attempts=self.rate_limit_max,
                window_seconds=self.rate_limit_window,
            )
            if not limiter.is_allowed(identifier):
                return JsonResponse(
                    {'success': False, 'error': 'Too many requests. Please wait and try again.'},
                    status=429,
                )
            limiter.record_attempt(identifier)
        return super().dispatch(request, *args, **kwargs)
