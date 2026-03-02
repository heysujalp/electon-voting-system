"""
ElectON v2 — Settings package.
Loads base settings + environment-specific overlay.
"""
import os
import warnings

VALID_ENVS = {'production', 'testing', 'development'}
environment = os.environ.get('DJANGO_ENV', 'development')

# CF-10: Warn on unrecognized DJANGO_ENV instead of silently falling through
if environment not in VALID_ENVS:
    warnings.warn(
        f"Unknown DJANGO_ENV={environment!r} — falling back to 'development'. "
        f"Valid values: {', '.join(sorted(VALID_ENVS))}",
        stacklevel=1,
    )
    environment = 'development'

if environment == 'production':
    from .production import *  # noqa: F401, F403
elif environment == 'testing':
    from .testing import *  # noqa: F401, F403
else:
    from .development import *  # noqa: F401, F403
