"""
ElectON v2 — Real-time event emitter via Redis pub/sub.

Publishes JSON events to SSE channels so connected dashboard clients
receive instant updates without polling.

Usage::

    from apps.elections.event_emitter import emit_event
    emit_event(election_uuid, 'stats_update', {'posts': 5, 'candidates': 12})

Channels
--------
- ``sse:election:<uuid>``  — per-election (dashboard viewers)
- ``sse:user:<user_id>``   — per-user (admin home viewers)

Security: only backend code can publish.  Clients subscribe indirectly
through the authenticated ``ElectionSSEView`` / ``UserSSEView`` Django views.
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger('electon.sse')

_redis_client = None


def _get_redis():
    """Lazy-initialise a Redis client from the Celery broker URL."""
    global _redis_client  # noqa: PLW0603
    if _redis_client is None:
        import redis as redis_lib

        url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
        _redis_client = redis_lib.from_url(url)
    return _redis_client


def emit_event(election_uuid, event_type, data=None, *, user_id=None):
    """Publish a real-time event.

    Args:
        election_uuid: UUID of the election (str or UUID).
        event_type: SSE event name (e.g. ``'stats_update'``, ``'vote_cast'``).
        data: Optional dict merged into the event payload.
        user_id: If provided, also publish to the user-scoped channel
                 so the admin-home page receives cross-election updates.
    """
    payload = {'type': event_type, 'election_uuid': str(election_uuid)}
    if data:
        payload.update(data)

    message = json.dumps(payload)
    election_channel = f'sse:election:{election_uuid}'

    try:
        r = _get_redis()
        r.publish(election_channel, message)
        if user_id:
            r.publish(f'sse:user:{user_id}', message)
    except Exception:
        logger.warning(
            'Failed to publish SSE event %s for election %s',
            event_type, election_uuid, exc_info=True,
        )


def build_stats_payload(election):
    """Build the same stats dict that ``ElectionStatsView`` returns.

    Reused by event emitters so SSE payloads are consistent with the
    polling fallback endpoint.
    """
    from django.db.models import Count, Q

    from apps.elections.models import Election
    from apps.voting.models import OFFLINE_VOTER_DOMAIN

    stats = (
        Election.objects
        .filter(pk=election.pk)
        .annotate(
            _total_posts=Count('posts', distinct=True),
            _total_candidates=Count('posts__candidates', distinct=True),
            _posts_with_candidates=Count(
                'posts',
                filter=Q(posts__candidates__isnull=False),
                distinct=True,
            ),
            _total_voters=Count(
                'voter_credentials',
                filter=Q(voter_credentials__is_revoked=False),
                distinct=True,
            ),
            _votes_cast=Count(
                'voter_credentials',
                filter=Q(
                    voter_credentials__has_voted=True,
                    voter_credentials__is_revoked=False,
                ),
                distinct=True,
            ),
            _email_invited=Count(
                'voter_credentials',
                filter=(
                    Q(voter_credentials__batch_number='')
                    & ~Q(voter_credentials__voter_email__endswith=OFFLINE_VOTER_DOMAIN)
                    & Q(voter_credentials__is_revoked=False)
                ),
                distinct=True,
            ),
            _pdf_generated=Count(
                'voter_credentials',
                filter=(
                    ~Q(voter_credentials__batch_number='')
                    & Q(voter_credentials__is_revoked=False)
                ),
                distinct=True,
            ),
        )
        .values(
            '_total_posts', '_total_candidates', '_posts_with_candidates',
            '_total_voters', '_votes_cast', '_email_invited', '_pdf_generated',
        )
        .first()
    )

    if not stats:
        return {}

    total_posts = stats['_total_posts']
    all_have_cands = (
        total_posts > 0
        and stats['_posts_with_candidates'] == total_posts
    )
    total_voters = stats['_total_voters']
    total_votes = stats['_votes_cast']
    steps_done = sum([total_posts > 0, all_have_cands, total_voters > 0])

    # Refresh the election object to get can_launch (avoids stale cache)
    election.refresh_from_db()
    setup_pct = 100 if election.can_launch else round(steps_done / 3 * 100)

    return {
        'posts': total_posts,
        'candidates': stats['_total_candidates'],
        'voters': total_voters,
        'votes': total_votes,
        'setup_pct': setup_pct,
        'all_posts_have_candidates': all_have_cands,
        'voter_email_invited': stats['_email_invited'],
        'voter_pdf_generated': stats['_pdf_generated'],
        'status': election.current_status.lower(),
    }
