"""
ElectON v2 — Plan limit enforcement service.

Centralised helper that replaces all direct ``ELECTON_SETTINGS`` reads
for limit checking.  Every limit-gated action flows through here.
"""
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('electon')


class PlanLimitService:
    """Centralized limit checking against a user's active subscription plan."""

    # ──────────────────────────────────────────────────────────────
    # Plan resolution
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_plan(user):
        """
        Return the user's effective plan.

        Falls back to the Free plan if no subscription exists,
        subscription is inactive, or subscription is expired.
        (auto-creates the link so subsequent calls are fast).
        """
        from .models import SubscriptionPlan, UserSubscription

        try:
            sub = user.subscription
            # Check both is_active flag and expiry
            if not sub.is_active:
                return PlanLimitService._get_free_plan()
            return sub.effective_plan
        except (UserSubscription.DoesNotExist, AttributeError):
            # Auto-assign Free plan if missing
            free = PlanLimitService._get_free_plan()
            if free is not None:
                # MED-31: Handle IntegrityError from concurrent get_or_create on OneToOneField
                from django.db import IntegrityError
                try:
                    UserSubscription.objects.get_or_create(user=user, defaults={'plan': free})
                except IntegrityError:
                    pass  # Another thread just created it — that's fine
            return free

    @staticmethod
    def _get_free_plan():
        """Return the Free SubscriptionPlan or None if it doesn't exist."""
        from .models import SubscriptionPlan
        try:
            return SubscriptionPlan.objects.get(slug='free')
        except SubscriptionPlan.DoesNotExist:
            logger.warning('Free plan not found – using ELECTON_SETTINGS fallback')
            return None

    # ──────────────────────────────────────────────────────────────
    # Individual limit checks
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fallback(key, default):
        """Read a limit from ELECTON_SETTINGS as fallback."""
        return getattr(settings, 'ELECTON_SETTINGS', {}).get(key, default)

    # BE-65: Common helper to eliminate repetitive check pattern
    @staticmethod
    def _check_limit(plan, current, plan_attr, fallback_key=None,
                     fallback_default=0, *, use_lte=False, count_key='current'):
        """
        Common limit check returning ``(within_limit, info_dict)``.

        *use_lte* switches to ``<=`` comparison (for import batch checks).
        *count_key* overrides the dict key for the count value.
        """
        if plan:
            limit = getattr(plan, plan_attr)
        elif fallback_key:
            limit = PlanLimitService._fallback(fallback_key, fallback_default)
        else:
            limit = fallback_default
        ok = current <= limit if use_lte else current < limit
        return ok, {
            count_key: current,
            'limit': limit,
            'plan_name': plan.name if plan else 'Default',
        }

    @staticmethod
    def check_election_limit(user):
        """Can this user create another election?"""
        plan = PlanLimitService.get_plan(user)
        from apps.elections.models import Election
        current = Election.objects.filter(created_by=user).count()
        return PlanLimitService._check_limit(
            plan, current, 'max_elections', 'MAX_ELECTIONS_PER_USER', 50,
        )

    @staticmethod
    def check_active_election_limit(user):
        """Can this user launch another election?"""
        plan = PlanLimitService.get_plan(user)
        from apps.elections.models import Election
        active = Election.objects.filter(
            created_by=user, is_launched=True, end_time__gt=timezone.now(),
        ).count()
        return PlanLimitService._check_limit(
            plan, active, 'max_active_elections', fallback_default=2,
        )

    @staticmethod
    def check_post_limit(election):
        """Can this election have another post?"""
        plan = PlanLimitService.get_plan(election.created_by)
        current = election.posts.count()
        return PlanLimitService._check_limit(
            plan, current, 'max_posts_per_election', 'MAX_POSTS_PER_ELECTION', 20,
        )

    @staticmethod
    def check_candidate_limit(post):
        """Can this post have another candidate?"""
        plan = PlanLimitService.get_plan(post.election.created_by)
        current = post.candidates.count()
        return PlanLimitService._check_limit(
            plan, current, 'max_candidates_per_post', 'MAX_CANDIDATES_PER_POST', 50,
        )

    @staticmethod
    def check_voter_limit(election):
        """Can this election have more voters?"""
        plan = PlanLimitService.get_plan(election.created_by)
        current = election.voter_credentials.filter(is_revoked=False).count()
        return PlanLimitService._check_limit(
            plan, current, 'max_voters_per_election', 'MAX_VOTERS_PER_ELECTION', 10000,
        )

    @staticmethod
    def check_import_limit(user, import_count):
        """Is this import batch within the plan's import limit?"""
        plan = PlanLimitService.get_plan(user)
        return PlanLimitService._check_limit(
            plan, import_count, 'max_voters_per_import', 'MAX_VOTERS_PER_IMPORT', 500,
            use_lte=True, count_key='requested',
        )

    # Allowed feature flag names (must match BooleanField names on SubscriptionPlan)
    _FEATURE_ALLOWLIST = frozenset({
        'can_export_pdf',
        'can_use_offline_credentials',
        'can_view_blockchain_audit',
        'can_use_custom_branding',
        'priority_email_delivery',
    })

    @staticmethod
    def check_feature(user, feature_name):
        """Check if a feature flag is enabled for this user's plan."""
        if feature_name not in PlanLimitService._FEATURE_ALLOWLIST:
            logger.warning('check_feature called with unknown feature: %s', feature_name)
            return False
        plan = PlanLimitService.get_plan(user)
        if plan is None:
            return False  # No plan = no premium features
        return getattr(plan, feature_name, False)

    # ──────────────────────────────────────────────────────────────
    # Full usage summary (for account settings panel)
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_usage_summary(user):
        """
        Full usage summary for the account settings Subscription panel.

        Returns a dict with plan details, current usage, and feature flags.
        """
        plan = PlanLimitService.get_plan(user)

        from apps.elections.models import Election
        elections = Election.objects.filter(created_by=user)
        elections_used = elections.count()
        active_elections = elections.filter(
            is_launched=True, end_time__gt=timezone.now(),
        ).count()

        if plan is None:
            # Full fallback to ELECTON_SETTINGS
            es = getattr(settings, 'ELECTON_SETTINGS', {})
            return {
                'plan': None,
                'plan_name': 'Default',
                'plan_description': '',
                'plan_badge_color': 'apple-blue',
                'elections_used': elections_used,
                'elections_limit': es.get('MAX_ELECTIONS_PER_USER', 50),
                'active_elections': active_elections,
                'active_elections_limit': 2,
                'max_posts': es.get('MAX_POSTS_PER_ELECTION', 20),
                'max_candidates': es.get('MAX_CANDIDATES_PER_POST', 50),
                'max_voters': es.get('MAX_VOTERS_PER_ELECTION', 10000),
                'max_import': es.get('MAX_VOTERS_PER_IMPORT', 500),
                'features': {
                    'pdf_export': True,
                    'offline_credentials': True,
                    'blockchain_audit': True,
                    'custom_branding': False,
                    'priority_email': False,
                },
                'expires_at': None,
            }

        # Determine subscription expiry
        expires_at = None
        try:
            sub = user.subscription
            expires_at = sub.expires_at
        except Exception:
            pass

        return {
            'plan': plan,
            'plan_name': plan.name,
            'plan_description': plan.description,
            'plan_badge_color': plan.badge_color,
            'elections_used': elections_used,
            'elections_limit': plan.max_elections,
            'active_elections': active_elections,
            'active_elections_limit': plan.max_active_elections,
            'max_posts': plan.max_posts_per_election,
            'max_candidates': plan.max_candidates_per_post,
            'max_voters': plan.max_voters_per_election,
            'max_import': plan.max_voters_per_import,
            'features': {
                'pdf_export': plan.can_export_pdf,
                'offline_credentials': plan.can_use_offline_credentials,
                'blockchain_audit': plan.can_view_blockchain_audit,
                'custom_branding': plan.can_use_custom_branding,
                'priority_email': plan.priority_email_delivery,
            },
            'expires_at': expires_at,
        }
