"""
Seed default subscription plans: Free, Starter, Pro, Enterprise.
"""
from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'SubscriptionPlan')

    Plan.objects.create(
        name='Free', slug='free',
        description='Get started with basic elections.',
        max_elections=5, max_active_elections=2,
        max_posts_per_election=5, max_candidates_per_post=10,
        max_voters_per_election=100, max_voters_per_import=50,
        can_export_pdf=True, can_use_offline_credentials=False,
        can_view_blockchain_audit=True, can_use_custom_branding=False,
        priority_email_delivery=False,
        price_monthly=0, price_yearly=0,
        display_order=0, badge_color='apple-blue',
    )
    Plan.objects.create(
        name='Starter', slug='starter',
        description='For small organizations.',
        max_elections=20, max_active_elections=5,
        max_posts_per_election=15, max_candidates_per_post=30,
        max_voters_per_election=1000, max_voters_per_import=200,
        can_export_pdf=True, can_use_offline_credentials=True,
        can_view_blockchain_audit=True, can_use_custom_branding=False,
        priority_email_delivery=False,
        price_monthly=9.99, price_yearly=99.99,
        display_order=1, badge_color='apple-green',
    )
    Plan.objects.create(
        name='Pro', slug='pro',
        description='For larger organizations and institutions.',
        max_elections=50, max_active_elections=10,
        max_posts_per_election=20, max_candidates_per_post=50,
        max_voters_per_election=10000, max_voters_per_import=500,
        can_export_pdf=True, can_use_offline_credentials=True,
        can_view_blockchain_audit=True, can_use_custom_branding=True,
        priority_email_delivery=False,
        price_monthly=29.99, price_yearly=299.99,
        display_order=2, badge_color='apple-purple',
    )
    Plan.objects.create(
        name='Enterprise', slug='enterprise',
        description='Unlimited. Custom support.',
        max_elections=999, max_active_elections=50,
        max_posts_per_election=100, max_candidates_per_post=200,
        max_voters_per_election=100000, max_voters_per_import=5000,
        can_export_pdf=True, can_use_offline_credentials=True,
        can_view_blockchain_audit=True, can_use_custom_branding=True,
        priority_email_delivery=True,
        price_monthly=99.99, price_yearly=999.99,
        display_order=3, badge_color='apple-orange',
    )


def reverse_seed(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'SubscriptionPlan')
    Plan.objects.filter(slug__in=['free', 'starter', 'pro', 'enterprise']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_seed),
    ]
