"""
ElectON v2 — Subscription tests.
Tests for PlanLimitService, UserSubscription model, and effective_plan logic.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.subscriptions.models import SubscriptionPlan, UserSubscription
from apps.subscriptions.services import PlanLimitService

User = get_user_model()


class SubscriptionPlanModelTest(TestCase):
    """Test SubscriptionPlan model."""

    def setUp(self):
        self.free = SubscriptionPlan.objects.create(
            name='Free', slug='free',
            max_elections=5, max_active_elections=2,
            max_posts_per_election=5, max_candidates_per_post=10,
            max_voters_per_election=100, max_voters_per_import=50,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Pro', slug='pro',
            max_elections=50, max_active_elections=10,
            max_posts_per_election=20, max_candidates_per_post=50,
            max_voters_per_election=10000, max_voters_per_import=500,
            can_use_offline_credentials=True,
            can_use_custom_branding=True,
            priority_email_delivery=True,
        )

    def test_str_representation(self):
        self.assertEqual(str(self.free), 'Free')
        self.assertEqual(str(self.pro), 'Pro')

    def test_ordering(self):
        plans = list(SubscriptionPlan.objects.all())
        self.assertEqual(plans[0].slug, 'free')


class UserSubscriptionModelTest(TestCase):
    """Test UserSubscription model and effective_plan property."""

    def setUp(self):
        self.free = SubscriptionPlan.objects.create(
            name='Free', slug='free',
            max_elections=5, max_active_elections=2,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Pro', slug='pro',
            max_elections=50, max_active_elections=10,
        )
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='TestPass123!',
        )

    def test_active_subscription_returns_plan(self):
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
        )
        self.assertEqual(sub.effective_plan, self.pro)

    def test_unexpired_subscription(self):
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertFalse(sub.is_expired)
        self.assertEqual(sub.effective_plan, self.pro)

    def test_expired_subscription_falls_back_to_free(self):
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(sub.is_expired)
        self.assertEqual(sub.effective_plan, self.free)

    def test_no_expiry_never_expires(self):
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=None,
        )
        self.assertFalse(sub.is_expired)

    def test_str_representation(self):
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.free,
        )
        self.assertIn('testuser', str(sub))
        self.assertIn('Free', str(sub))


class PlanLimitServiceTest(TestCase):
    """Test PlanLimitService centralized limit checking."""

    def setUp(self):
        self.free = SubscriptionPlan.objects.create(
            name='Free', slug='free',
            max_elections=5, max_active_elections=2,
            max_posts_per_election=5, max_candidates_per_post=10,
            max_voters_per_election=100, max_voters_per_import=50,
            can_export_pdf=True,
            can_use_offline_credentials=False,
            can_view_blockchain_audit=True,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Pro', slug='pro',
            max_elections=50, max_active_elections=10,
            max_posts_per_election=20, max_candidates_per_post=50,
            max_voters_per_election=10000, max_voters_per_import=500,
            can_use_offline_credentials=True,
        )
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='TestPass123!',
        )

    def test_get_plan_auto_assigns_free(self):
        """User without subscription gets Free plan auto-assigned."""
        plan = PlanLimitService.get_plan(self.user)
        self.assertEqual(plan, self.free)
        self.assertTrue(UserSubscription.objects.filter(user=self.user).exists())

    def test_get_plan_returns_active_plan(self):
        UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
        )
        plan = PlanLimitService.get_plan(self.user)
        self.assertEqual(plan, self.pro)

    def test_get_plan_inactive_subscription_returns_free(self):
        """Inactive subscription falls back to Free plan."""
        UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=False,
        )
        plan = PlanLimitService.get_plan(self.user)
        self.assertEqual(plan, self.free)

    def test_check_election_limit_within(self):
        allowed, info = PlanLimitService.check_election_limit(self.user)
        self.assertTrue(allowed)
        self.assertEqual(info['current'], 0)
        self.assertEqual(info['limit'], 5)

    def test_check_feature_enabled(self):
        UserSubscription.objects.create(user=self.user, plan=self.free)
        self.assertTrue(PlanLimitService.check_feature(self.user, 'can_export_pdf'))
        self.assertFalse(PlanLimitService.check_feature(self.user, 'can_use_offline_credentials'))

    def test_check_feature_pro_plan(self):
        UserSubscription.objects.create(user=self.user, plan=self.pro)
        self.assertTrue(PlanLimitService.check_feature(self.user, 'can_use_offline_credentials'))

    def test_check_import_limit(self):
        allowed, info = PlanLimitService.check_import_limit(self.user, 50)
        self.assertTrue(allowed)
        not_allowed, info2 = PlanLimitService.check_import_limit(self.user, 51)
        self.assertFalse(not_allowed)

    def test_usage_summary_structure(self):
        UserSubscription.objects.create(user=self.user, plan=self.free)
        summary = PlanLimitService.get_usage_summary(self.user)
        self.assertIn('plan_name', summary)
        self.assertIn('elections_used', summary)
        self.assertIn('features', summary)
        self.assertEqual(summary['plan_name'], 'Free')

    def test_usage_summary_no_plan(self):
        """When Free plan doesn't exist, fallback dict is returned."""
        SubscriptionPlan.objects.filter(slug='free').delete()
        UserSubscription.objects.filter(user=self.user).delete()

        summary = PlanLimitService.get_usage_summary(self.user)
        self.assertEqual(summary['plan_name'], 'Default')
        self.assertIsNone(summary['plan'])


class EffectivePlanEdgeCasesTest(TestCase):
    """Edge cases for effective_plan and expiry logic."""

    def setUp(self):
        self.free = SubscriptionPlan.objects.create(
            name='Free', slug='free',
            max_elections=5, max_active_elections=2,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Pro', slug='pro',
            max_elections=50, max_active_elections=10,
        )
        self.user = User.objects.create_user(
            username='edgeuser', email='edge@example.com', password='TestPass123!',
        )

    def test_expired_pro_limits_fall_to_free(self):
        """Expired Pro subscription should enforce Free plan limits."""
        UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        plan = PlanLimitService.get_plan(self.user)
        self.assertEqual(plan.slug, 'free')
        self.assertEqual(plan.max_elections, 5)

    def test_just_expired_boundary(self):
        """Subscription that expired exactly now should be treated as expired."""
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=timezone.now(),
        )
        self.assertTrue(sub.is_expired)

    def test_not_yet_expired(self):
        """Subscription expiring 1 second from now is still active."""
        sub = UserSubscription.objects.create(
            user=self.user, plan=self.pro, is_active=True,
            expires_at=timezone.now() + timedelta(seconds=1),
        )
        self.assertFalse(sub.is_expired)
        self.assertEqual(sub.effective_plan, self.pro)
