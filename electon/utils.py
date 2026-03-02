"""
ElectON v2 — Shared Utilities.

Cross-app helpers that don't belong in any single app's service layer.
"""
from django.conf import settings


def get_client_ip(request) -> str:
    """Extract client IP from request, handling proxies.

    Only trusts X-Forwarded-For when NUM_PROXIES is configured.
    """
    num_proxies = getattr(settings, 'NUM_PROXIES', 0)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for and num_proxies > 0:
        # Take the IP that is `num_proxies` hops from the right
        addrs = [addr.strip() for addr in x_forwarded_for.split(',')]
        try:
            return addrs[-num_proxies]
        except IndexError:
            return addrs[0]
    return request.META.get('REMOTE_ADDR', '0.0.0.0')
