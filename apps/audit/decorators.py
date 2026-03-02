"""
ElectON v2 — Audit decorators.
"""
from functools import wraps

from .services.audit_service import AuditService


def audit_action(action: str, get_election=None):
    """
    Decorator to automatically log an action on successful view execution.

    Usage:
        @audit_action('election_create')
        def post(self, request, *args, **kwargs):
            ...

        @audit_action('election_launch', get_election=lambda self: self.election)
        def post(self, request, *args, **kwargs):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            response = view_func(self, request, *args, **kwargs)
            # Only log on successful responses (2xx or redirects 3xx)
            status = getattr(response, 'status_code', 200)
            if 200 <= status < 400:
                # MED-35: Safely resolve election from lambda, handle AttributeError
                election = None
                if get_election:
                    try:
                        election = get_election(self)
                    except (AttributeError, TypeError):
                        pass
                AuditService.log(action, request=request, election=election)
            return response
        return wrapper
    return decorator
