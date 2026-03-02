"""
ElectON v2 — Subscription admin configuration.
"""
from django.contrib import admin

from .models import SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'slug', 'max_elections', 'max_voters_per_election',
        'price_monthly', 'is_active', 'subscriber_count',
    ]
    list_filter = ['is_active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        # LOW-36: Annotate subscriber_count to avoid N+1 queries
        from django.db.models import Count, Q
        qs = super().get_queryset(request)
        return qs.annotate(
            _subscriber_count=Count('subscribers', filter=Q(subscribers__is_active=True))
        )

    def subscriber_count(self, obj):
        return getattr(obj, '_subscriber_count', 0)

    subscriber_count.short_description = 'Subscribers'


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'started_at', 'expires_at', 'is_active']
    list_filter = ['plan', 'is_active']
    list_select_related = ['user', 'plan']  # LOW-35: Prevent N+1 in admin list
    search_fields = ['user__username', 'user__email']
    raw_id_fields = ['user']
