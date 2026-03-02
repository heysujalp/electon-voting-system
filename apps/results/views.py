"""
ElectON v2 — Results views.

PDF downloads and analytics charts for election owners.

Phase 6: ElectionChartsView now returns raw JSON data for Chart.js
(client-side rendering), replacing the old matplotlib base64 approach.
"""
import csv
import io
import logging
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views import View

from apps.elections.mixins import ElectionOwnerMixin
from apps.candidates.models import Candidate
from apps.voting.models import Vote, VoterCredential
from django.db import models
from django.db.models import Count
from .services.analytics_service import AnalyticsService
from .services.pdf_service import PDFService

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _get_results_data(election):
    """
    Return annotated posts with per-candidate vote counts and result metadata.

    Yields tuples of (post_name, candidate_name, vote_count, percentage_str, winner_flag)
    for every candidate in the election. When abstain is enabled, a "NOTA" row
    is appended after each post's candidates.
    """
    voted_count = VoterCredential.objects.filter(
        election=election, has_voted=True,
    ).count()

    posts = election.posts.prefetch_related(
        models.Prefetch(
            'candidates',
            queryset=Candidate.objects.annotate(_vote_count=Count('votes')),
        )
    ).all()

    for post in posts:
        candidates = list(post.candidates.all())
        total = sum(c._vote_count for c in candidates)
        # LOW-28: Detect ties — mark all candidates sharing the max vote count
        max_votes = max((c._vote_count for c in candidates), default=0) if total else 0
        for cand in candidates:
            pct = round(cand._vote_count / total * 100, 2) if total else 0
            if max_votes > 0 and cand._vote_count == max_votes:
                # Check how many share the top count
                tie_count = sum(1 for c in candidates if c._vote_count == max_votes)
                is_winner = 'Tied' if tie_count > 1 else 'Yes'
            else:
                is_winner = ''
            yield (post.name, cand.name, cand._vote_count, f'{pct}%', is_winner)

        # Abstain count: voters who voted but didn't pick a candidate for this post
        if election.allow_abstain and voted_count > 0:
            voters_for_post = Vote.objects.filter(post=post).values('voter_hash').distinct().count()
            abstain_count = voted_count - voters_for_post
            if abstain_count > 0:
                pct = round(abstain_count / voted_count * 100, 2)
                yield (post.name, 'NOTA', abstain_count, f'{pct}%', '')


# ------------------------------------------------------------------
# PDF downloads
# ------------------------------------------------------------------

class VoterListPDFView(ElectionOwnerMixin, View):
    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        return PDFService().generate_voter_list_pdf(election)


class ElectionResultsPDFView(ElectionOwnerMixin, View):
    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        return PDFService().generate_results_pdf(election)


class AuditTrailPDFView(ElectionOwnerMixin, View):
    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        return PDFService().generate_audit_trail_pdf(election)


# ------------------------------------------------------------------
# Chart data endpoints (Phase 6 — Chart.js JSON)
# ------------------------------------------------------------------

class ElectionChartsView(ElectionOwnerMixin, View):
    """
    Return raw chart data as JSON for Chart.js rendering.

    GET /results/charts/<uuid>/?type=<type>

    Supported types:
        pie      — per-post donut chart data (labels + vote counts)
        turnout  — voted vs not-voted numbers
        timeline — hourly vote counts + cumulative totals
        all      — combined payload (pie + turnout + timeline)
    """

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)

        chart_type = request.GET.get('type', 'all')
        analytics = AnalyticsService(election)

        if chart_type == 'all':
            return JsonResponse({
                'success': True,
                'pie': analytics.get_pie_data(),
                'turnout': analytics.get_turnout_data(),
                'timeline': analytics.get_timeline_data(),
            })

        generators = {
            'pie': analytics.get_pie_data,
            'turnout': analytics.get_turnout_data,
            'timeline': analytics.get_timeline_data,
        }

        gen = generators.get(chart_type)
        if gen is None:
            return JsonResponse({'error': 'Invalid chart type.'}, status=400)

        data = gen()
        return JsonResponse({'success': True, 'chart_type': chart_type, 'data': data})


class RealTimeDataAPIView(ElectionOwnerMixin, View):
    """JSON endpoint for live election statistics."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        return JsonResponse(AnalyticsService(election).get_statistics())


# ------------------------------------------------------------------
# Results CSV / Excel exports
# ------------------------------------------------------------------

class ExportResultsCSVView(ElectionOwnerMixin, View):
    """Export election results as CSV."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        # LOW-29: Only allow export for concluded elections
        if election.current_status != 'Concluded':
            return HttpResponse('Results export is only available after the election has concluded.', status=403)

        response = HttpResponse(content_type='text/csv')
        safe_name = quote(election.name, safe='')
        response['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_name}_results.csv"

        writer = csv.writer(response)
        writer.writerow(['Position', 'Candidate', 'Votes', 'Percentage', 'Winner'])

        for row in _get_results_data(election):
            writer.writerow(row)

        return response


class ExportResultsExcelView(ElectionOwnerMixin, View):
    """Export election results as Excel (.xlsx)."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)
        # LOW-29: Only allow export for concluded elections
        if election.current_status != 'Concluded':
            return HttpResponse('Results export is only available after the election has concluded.', status=403)

        try:
            import openpyxl
        except ImportError:
            return HttpResponse('openpyxl is not installed.', status=500)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Results'
        ws.append(['Position', 'Candidate', 'Votes', 'Percentage', 'Winner'])

        for row in _get_results_data(election):
            ws.append(list(row))

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        safe_name = quote(election.name, safe='')
        response = HttpResponse(
            buffer.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_name}_results.xlsx"
        return response
