"""
ElectON v2 — Election analytics service.

Key fixes over V1:
- ``election.election_uuid`` not ``election.uuid``
- ``election.current_status`` not ``election.status``
- ``vote.timestamp`` not ``vote.vote_time``
- Cached results (5 min TTL)
- Uses annotated queries instead of N+1 loops

Phase 6: Added get_pie_data(), get_turnout_data(), get_timeline_data()
that return raw dicts for client-side Chart.js rendering.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Min
from django.utils import timezone

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.voting.models import Vote, VoterCredential

logger = logging.getLogger(__name__)

CHART_CACHE_TTL = 300  # 5 minutes

# ── Apple HIG-inspired chart palette ──
CHART_COLORS = [
    '#007AFF',  # Blue
    '#34C759',  # Green
    '#FF9500',  # Orange
    '#FF3B30',  # Red
    '#AF52DE',  # Purple
    '#5856D6',  # Indigo
    '#FF2D55',  # Pink
    '#00C7BE',  # Teal
    '#FFD60A',  # Yellow
    '#8E8E93',  # Gray
]


class AnalyticsService:
    """Aggregated statistics and chart data for a single election."""

    def __init__(self, election: Election):
        self.election = election

    # ------------------------------------------------------------------
    # Statistics (cached)
    # ------------------------------------------------------------------

    def get_statistics(self) -> dict:
        """
        Return cached aggregate statistics.

        Uses annotated queries (no N+1).
        """
        cache_key = f'election_stats:{self.election.pk}'
        stats = cache.get(cache_key)
        if stats:
            return stats

        total_voters = VoterCredential.objects.filter(election=self.election).count()
        voted_count = VoterCredential.objects.filter(
            election=self.election, has_voted=True,
        ).count()

        posts = (
            self.election.posts
            .annotate(total_votes=Count('votes'))
            .order_by('created_at')
        )

        candidates = (
            Candidate.objects.filter(election=self.election)
            .annotate(vote_count=Count('votes'))
            .select_related('post')
            .order_by('-vote_count')
        )

        # Compute per-post abstain counts when abstain is enabled
        abstain_by_post = {}
        if self.election.allow_abstain and voted_count > 0:
            for p in posts:
                voters_for_post = Vote.objects.filter(post=p).values('voter_hash').distinct().count()
                abstain_count = voted_count - voters_for_post
                if abstain_count > 0:
                    abstain_by_post[p.pk] = abstain_count

        stats = {
            'total_voters': total_voters,
            'voted_count': voted_count,
            'turnout_pct': round(voted_count / total_voters * 100, 1) if total_voters else 0,
            'election_status': self.election.current_status,
            'posts': [
                {
                    'id': p.pk,
                    'name': p.name,
                    'total_votes': p.total_votes,
                    'abstain_count': abstain_by_post.get(p.pk, 0),
                }
                for p in posts
            ],
            'candidates': [
                {
                    'id': c.pk,
                    'name': c.name,
                    'post_name': c.post.name,
                    'vote_count': c.vote_count,
                }
                for c in candidates
            ],
            'last_updated': timezone.now().isoformat(),
        }

        cache.set(cache_key, stats, CHART_CACHE_TTL)
        return stats

    # ------------------------------------------------------------------
    # Chart.js data generators (Phase 6)
    # ------------------------------------------------------------------

    def get_pie_data(self) -> list[dict]:
        """
        Per-post donut chart data for Chart.js.

        Returns:
            [
                {
                    "post_name": "President",
                    "labels": ["Alice", "Bob"],
                    "values": [12, 8],
                    "colors": ["#007AFF", "#34C759"],
                    "total": 20,
                },
                ...
            ]
        """
        cache_key = f'chartjs_pie:{self.election.pk}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            posts = self.election.posts.order_by('created_at')
            voted_count = VoterCredential.objects.filter(
                election=self.election, has_voted=True,
            ).count()
            result = []

            for post in posts:
                candidates_qs = list(
                    post.candidates
                    .annotate(vote_count=Count('votes'))
                    .order_by('-vote_count', 'created_at')
                )
                labels = [c.name for c in candidates_qs]
                values = [c.vote_count for c in candidates_qs]
                colors = list(CHART_COLORS[:len(labels)])
                cand_ids = [c.pk for c in candidates_qs]
                cand_images = [
                    (c.image.url if c.image else '') for c in candidates_qs
                ]

                # Determine winner / tie
                max_votes = max(values, default=0)
                is_tied = max_votes > 0 and sum(1 for v in values if v == max_votes) > 1
                winner_cand = candidates_qs[0] if candidates_qs else None
                winner_votes = winner_cand.vote_count if winner_cand else 0
                candidate_total = sum(values)
                winner_pct = (
                    round(winner_votes / candidate_total * 100, 1)
                    if candidate_total > 0 and winner_votes > 0 else 0
                )
                winner_name = winner_cand.name if (winner_cand and winner_votes > 0) else None
                winner_image = (winner_cand.image.url if (winner_cand and winner_cand.image) else '') if winner_cand else ''

                # Assign ranks (ties share same rank)
                ranks = []
                current_rank = 1
                prev_votes = None
                for i, v in enumerate(values):
                    if v != prev_votes:
                        current_rank = i + 1
                    ranks.append(current_rank)
                    prev_votes = v

                # Add NOTA slice when enabled
                if self.election.allow_abstain and voted_count > 0:
                    voters_for_post = Vote.objects.filter(post=post).values('voter_hash').distinct().count()
                    abstain_count = voted_count - voters_for_post
                    if abstain_count > 0:
                        labels.append('NOTA')
                        values.append(abstain_count)
                        colors.append('#8E8E93')  # Gray for NOTA
                        cand_ids.append(None)
                        cand_images.append('')
                        ranks.append(len(ranks) + 1)

                result.append({
                    'post_id': post.pk,
                    'post_name': post.name,
                    'labels': labels,
                    'values': values,
                    'colors': colors,
                    'candidate_ids': cand_ids,
                    'candidate_images': cand_images,
                    'total': sum(values),
                    'winner_name': winner_name,
                    'winner_votes': winner_votes,
                    'winner_pct': winner_pct,
                    'winner_image': winner_image,
                    'is_tied': is_tied,
                    'ranks': ranks,
                })

            cache.set(cache_key, result, CHART_CACHE_TTL)
            return result
        except Exception:
            logger.exception("Pie data generation failed for %s", self.election.election_uuid)
            return []

    def get_turnout_data(self) -> dict:
        """
        Turnout data for Chart.js gauge / doughnut.

        Returns:
            {
                "total": 100,
                "voted": 45,
                "not_voted": 55,
                "turnout_pct": 45.0,
            }
        """
        cache_key = f'chartjs_turnout:{self.election.pk}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            total = VoterCredential.objects.filter(election=self.election).count()
            voted = VoterCredential.objects.filter(
                election=self.election, has_voted=True,
            ).count()

            data = {
                'total': total,
                'voted': voted,
                'not_voted': total - voted,
                'turnout_pct': round(voted / total * 100, 1) if total else 0,
            }
            cache.set(cache_key, data, CHART_CACHE_TTL)
            return data
        except Exception:
            logger.exception("Turnout data failed for %s", self.election.election_uuid)
            return {'total': 0, 'voted': 0, 'not_voted': 0, 'turnout_pct': 0}

    def get_timeline_data(self) -> dict:
        """
        Voting timeline data for Chart.js line chart (hourly buckets).

        Returns:
            {
                "labels": ["2026-02-20 10:00", ...],
                "hourly": [5, 12, 3, ...],
                "cumulative": [5, 17, 20, ...],
            }
        """
        cache_key = f'chartjs_timeline:{self.election.pk}'
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            # Count unique voters (by voter_hash) per hour, not raw Vote records.
            # Each voter casts one Vote per position, so raw count inflates
            # the timeline when there are multiple positions.
            voter_timestamps = (
                Vote.objects
                .filter(election=self.election)
                .values('voter_hash')
                .annotate(first_ts=Min('timestamp'))
                .order_by('first_ts')
                .values_list('first_ts', flat=True)
            )
            voter_timestamps = list(voter_timestamps)
            if not voter_timestamps:
                return {'labels': [], 'hourly': [], 'cumulative': []}

            # Bucket unique voters into hours
            hourly_map = defaultdict(int)
            for ts in voter_timestamps:
                bucket = ts.replace(minute=0, second=0, microsecond=0)
                hourly_map[bucket] += 1

            sorted_hours = sorted(hourly_map.keys())
            labels = [h.strftime('%Y-%m-%d %H:%M') for h in sorted_hours]
            hourly = [hourly_map[h] for h in sorted_hours]
            cumulative = []
            running = 0
            for v in hourly:
                running += v
                cumulative.append(running)

            # Compute first/last vote and peak hour
            first_ts = voter_timestamps[0] if voter_timestamps else None
            last_ts = voter_timestamps[-1] if voter_timestamps else None

            peak_bucket = max(hourly_map, key=hourly_map.get) if hourly_map else None
            peak_label = None
            peak_count = 0
            if peak_bucket:
                try:
                    from django.utils.timezone import localtime
                    peak_dt = localtime(peak_bucket)
                    peak_label = peak_dt.strftime('%b %-d, %H:%M')
                except Exception:
                    peak_label = peak_bucket.strftime('%b %-d, %H:%M')
                peak_count = hourly_map[peak_bucket]

            data = {
                'labels': labels,
                'hourly': hourly,
                'cumulative': cumulative,
                'first_vote': first_ts.isoformat() if first_ts else None,
                'last_vote': last_ts.isoformat() if last_ts else None,
                'peak_hour': peak_label,
                'peak_count': peak_count,
            }
            cache.set(cache_key, data, CHART_CACHE_TTL)
            return data
        except Exception:
            logger.exception("Timeline data failed for %s", self.election.election_uuid)
            return {'labels': [], 'hourly': [], 'cumulative': [],
                    'first_vote': None, 'last_vote': None,
                    'peak_hour': None, 'peak_count': 0}
