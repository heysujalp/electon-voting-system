"""
ElectON v2 — Management command to clean up expired sessions.

FEAT-10: Use this via cron instead of the middleware-based approach.

Usage:
    python manage.py cleanup_sessions

Can be scheduled with cron:
    0 * * * * cd /path/to/project && python manage.py cleanup_sessions
"""
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Remove expired sessions from the database.'

    def handle(self, *args, **options):
        deleted, _ = Session.objects.filter(
            expire_date__lt=timezone.now()
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted} expired session(s).')
        )
