"""
ElectON v2 — Subscription models.

Defines tiered subscription plans and per-user subscription tracking.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """Defines a subscription tier with its limits and feature flags."""

    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True, default='')

    # ── Limits ──
    max_elections = models.PositiveIntegerField(default=5)
    max_active_elections = models.PositiveIntegerField(default=2)
    max_posts_per_election = models.PositiveIntegerField(default=5)
    max_candidates_per_post = models.PositiveIntegerField(default=10)
    max_voters_per_election = models.PositiveIntegerField(default=100)
    max_voters_per_import = models.PositiveIntegerField(default=50)

    # ── Feature flags ──
    can_export_pdf = models.BooleanField(default=True)
    can_use_offline_credentials = models.BooleanField(default=False)
    can_view_blockchain_audit = models.BooleanField(default=True)
    can_use_custom_branding = models.BooleanField(default=False)
    priority_email_delivery = models.BooleanField(default=False)

    # ── Display / pricing ──
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    badge_color = models.CharField(max_length=20, default='apple-blue')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return self.name


class UserSubscription(models.Model):
    """Links a user to their active subscription plan."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription',
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='subscribers',
    )

    # ── Billing period ──
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)

    # ── Payment tracking (future integration — LOW-33: currently unused) ──
    # TODO: Remove these fields via migration when payment integration is
    # confirmed to be out of scope.
    payment_provider = models.CharField(max_length=30, blank=True, default='')
    payment_customer_id = models.CharField(max_length=100, blank=True, default='')
    payment_subscription_id = models.CharField(max_length=100, blank=True, default='')

    # ── Upgrade / downgrade tracking ──
    previous_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    plan_changed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        # LOW-35: Use cached user_id/plan_id to avoid extra queries
        return f"Subscription #{self.pk} (user={self.user_id}, plan={self.plan_id})"

    @property
    def is_expired(self):
        """True if the subscription period has ended or subscription is inactive."""
        if not self.is_active:
            return True  # MED-29: Inactive subscriptions are treated as expired
        if not self.expires_at:
            return False  # Free plan never expires
        return timezone.now() >= self.expires_at

    @property
    def effective_plan(self):
        """Returns the active plan, or falls back to Free if expired."""
        if self.is_expired:
            # MED-30: Use cached free plan to avoid repeated DB queries
            if not hasattr(SubscriptionPlan, '_free_plan_cache'):
                try:
                    SubscriptionPlan._free_plan_cache = SubscriptionPlan.objects.get(slug='free')
                except SubscriptionPlan.DoesNotExist:
                    SubscriptionPlan._free_plan_cache = None
            return SubscriptionPlan._free_plan_cache or self.plan
        return self.plan
