"""
ElectON v2 — PDF generation service.

Key fixes over V1:
- Uses ``election.election_uuid`` not ``election.uuid``
- Uses ``vote.timestamp`` not ``vote.vote_time``
- Results PDF shows **aggregate counts only** (anonymized — no per-voter choices)
- Audit trail PDF does **not** claim bcrypt or DB encryption
- Voter list PDF uses ``invitation_sent`` not ``invitation_successful``
"""
import io
import logging
import secrets

from django.conf import settings as django_settings
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from apps.voting.models import Vote, VoterCredential

logger = logging.getLogger(__name__)


class PDFService:
    """Generate election-related PDF documents."""

    def __init__(self):
        styles = getSampleStyleSheet()
        self.title = ParagraphStyle(
            'PDFTitle', parent=styles['Heading1'],
            fontSize=18, alignment=TA_CENTER, spaceAfter=30,
        )
        self.heading = ParagraphStyle(
            'PDFHeading', parent=styles['Heading2'],
            fontSize=14, alignment=TA_LEFT, spaceAfter=12,
        )
        self.normal = styles['Normal']

    # ------------------------------------------------------------------
    # Voter list
    # ------------------------------------------------------------------

    def generate_voter_list_pdf(self, election) -> HttpResponse:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        story = self._election_header(election, 'Voter List')

        credentials = election.voter_credentials.all().order_by('voter_name')
        if not credentials.exists():
            story.append(Paragraph("No voters registered.", self.normal))
        else:
            story.append(Paragraph(f"Total Voters: {credentials.count()}", self.heading))
            rows = [['#', 'Name', 'Email', 'Username', 'Invitation']]
            for idx, vc in enumerate(credentials, 1):
                inv = 'Sent' if vc.invitation_sent else ('Error' if vc.invitation_error else 'Pending')
                rows.append([str(idx), vc.voter_name or '—', vc.voter_email,
                             vc.one_time_username, inv])

            table = Table(rows, colWidths=[0.4 * inch, 1.8 * inch, 2.6 * inch, 1.5 * inch, 1.2 * inch])
            table.setStyle(self._table_style())
            story.append(table)

        doc.build(story)
        return self._response(buf, election, 'voter_list')

    # ------------------------------------------------------------------
    # Election results (ANONYMIZED — aggregate only)
    # ------------------------------------------------------------------

    def generate_results_pdf(self, election) -> HttpResponse:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        story = self._election_header(election, 'Election Results')

        total_voters = VoterCredential.objects.filter(election=election).count()
        voted = VoterCredential.objects.filter(election=election, has_voted=True).count()
        turnout = round(voted / total_voters * 100, 1) if total_voters else 0

        story.append(Paragraph(
            f"<b>Registered Voters:</b> {total_voters} &nbsp; | &nbsp; "
            f"<b>Votes Cast:</b> {voted} &nbsp; | &nbsp; "
            f"<b>Turnout:</b> {turnout}%",
            self.normal,
        ))
        story.append(Spacer(1, 20))

        for post in election.posts.order_by('created_at'):
            story.append(Paragraph(f"Post: {post.name}", self.heading))

            candidates = (
                post.candidates
                .annotate(vote_count=Count('votes'))
                .order_by('-vote_count', 'name')
            )
            total = sum(c.vote_count for c in candidates)

            rows = [['Rank', 'Candidate', 'Votes', '%']]
            for rank, c in enumerate(candidates, 1):
                pct = f"{c.vote_count / total * 100:.1f}%" if total else "0%"
                rows.append([str(rank), c.name, str(c.vote_count), pct])

            # Abstain count when enabled
            if election.allow_abstain and voted > 0:
                voters_for_post = Vote.objects.filter(post=post).values('voter_hash').distinct().count()
                abstain_count = voted - voters_for_post
                if abstain_count > 0:
                    pct = f"{abstain_count / voted * 100:.1f}%"
                    rows.append(['—', 'NOTA', str(abstain_count), pct])

            table = Table(rows, colWidths=[0.6 * inch, 3 * inch, 1 * inch, 1 * inch])
            table.setStyle(self._table_style(header_bg=colors.darkblue))
            story.append(table)
            story.append(Spacer(1, 16))

        doc.build(story)
        return self._response(buf, election, 'results')

    # ------------------------------------------------------------------
    # Audit trail (comprehensive election record)
    # ------------------------------------------------------------------

    # Standard usable width for A4 with default margins (≈6.6″)
    FULL_W = 6.6 * inch

    def generate_audit_trail_pdf(self, election) -> HttpResponse:
        from apps.audit.models import AuditLog

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        story = self._election_header(election, 'Audit Trail')
        W = self.FULL_W

        sub_heading = ParagraphStyle(
            'AuditSub', parent=self.heading,
            fontSize=11, spaceBefore=14, spaceAfter=6,
            textColor=colors.HexColor('#444444'),
        )
        small = ParagraphStyle(
            'AuditSmall', parent=self.normal,
            fontSize=8, textColor=colors.HexColor('#666666'),
        )

        section = 0

        # ─── 1. Election Profile ──────────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Election Profile", self.heading))
        profile_data = [
            ['Field', 'Value'],
            ['Name', election.name],
            ['UUID', str(election.election_uuid)],
            ['Access Code', election.access_code or '—'],
            ['Created By', election.created_by.username if election.created_by else '—'],
            ['Status', election.current_status],
            ['NOTA Enabled', 'Yes' if election.allow_abstain else 'No'],
            ['Admin Message', election.admin_message or '—'],
        ]
        if election.blockchain_contract_address:
            _net = getattr(django_settings, 'SOLANA_NETWORK', 'devnet').replace('-', ' ').title()
            profile_data.append(['Blockchain', f'Solana {_net} \u2014 Enabled'])
        else:
            profile_data.append(['Blockchain', 'Disabled'])
        t = Table(profile_data, colWidths=[1.6 * inch, W - 1.6 * inch])
        t.setStyle(self._table_style(header_bg=colors.HexColor('#2c3e50')))
        story.append(t)
        story.append(Spacer(1, 14))

        # ─── 2. Election Timeline ─────────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Election Timeline", self.heading))
        fmt = '%Y-%m-%d %H:%M:%S'
        timeline_data = [
            ['Event', 'Date & Time'],
            ['Created', election.created_at.strftime(fmt)],
        ]
        if election.launch_time:
            timeline_data.append(['Launched', election.launch_time.strftime(fmt)])
        timeline_data.append(['Voting Start', election.start_time.strftime(fmt)])
        timeline_data.append(['Voting End', election.end_time.strftime(fmt)])

        # First / last vote timestamps
        first_vote = Vote.objects.filter(election=election).order_by('timestamp').first()
        last_vote = Vote.objects.filter(election=election).order_by('-timestamp').first()
        if first_vote:
            timeline_data.append(['First Vote Cast', first_vote.timestamp.strftime(fmt)])
        if last_vote and last_vote != first_vote:
            timeline_data.append(['Last Vote Cast', last_vote.timestamp.strftime(fmt)])
        timeline_data.append(['Report Generated', timezone.now().strftime(fmt)])

        t = Table(timeline_data, colWidths=[1.6 * inch, W - 1.6 * inch])
        t.setStyle(self._table_style(header_bg=colors.HexColor('#2c3e50')))
        story.append(t)
        story.append(Spacer(1, 14))

        # ─── 3. Positions & Candidates ────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Positions & Candidates", self.heading))
        posts = election.posts.order_by('order', 'created_at')
        pc_rows = [['#', 'Position', 'Candidates']]
        for idx, post in enumerate(posts, 1):
            names = ', '.join(
                post.candidates.order_by('name').values_list('name', flat=True),
            )
            pc_rows.append([str(idx), post.name, names or '—'])
        t = Table(pc_rows, colWidths=[0.4 * inch, 2.0 * inch, W - 2.4 * inch])
        t.setStyle(self._table_style(header_bg=colors.HexColor('#34495e')))
        story.append(t)
        story.append(Spacer(1, 14))

        # ─── 4. Participation Summary ─────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Participation Summary", self.heading))
        total_invited = VoterCredential.objects.filter(election=election).count()
        active_voters = VoterCredential.objects.filter(
            election=election, is_revoked=False,
        ).count()
        voted = VoterCredential.objects.filter(
            election=election, has_voted=True, is_revoked=False,
        ).count()
        turnout = round(voted / active_voters * 100, 1) if active_voters else 0
        revoked = VoterCredential.objects.filter(
            election=election, is_revoked=True,
        ).count()
        inv_sent = VoterCredential.objects.filter(
            election=election, invitation_sent=True,
        ).count()

        col2 = (W - 2.4 * inch) / 2
        part_data = [
            ['Metric', 'Count', '%'],
            ['Total Invited', str(total_invited), '—'],
            ['Invitations Sent', str(inv_sent),
             f'{round(inv_sent / total_invited * 100, 1)}%' if total_invited else '0%'],
            ['Active Voters', str(active_voters), '100%'],
            ['Voted', str(voted), f'{turnout}%'],
            ['Not Voted', str(active_voters - voted),
             f'{round(100 - turnout, 1)}%' if active_voters else '0%'],
            ['Revoked', str(revoked), '—'],
        ]
        t = Table(part_data, colWidths=[2.4 * inch, col2, col2])
        t.setStyle(self._table_style(header_bg=colors.HexColor('#2980b9')))
        story.append(t)
        story.append(Spacer(1, 14))

        # ─── 5. Position Results ──────────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Position Results", self.heading))
        for post in posts:
            story.append(Paragraph(f"<b>{post.name}</b>", sub_heading))
            candidates = (
                post.candidates
                .annotate(vote_count=Count('votes'))
                .order_by('-vote_count', 'name')
            )
            total = sum(c.vote_count for c in candidates)
            rows = [['Rank', 'Candidate', 'Votes', '%', 'Status']]
            for rank, c in enumerate(candidates, 1):
                pct = f"{c.vote_count / total * 100:.1f}%" if total else "0%"
                status = ''
                if rank == 1 and c.vote_count > 0:
                    top_votes = candidates[0].vote_count if candidates else 0
                    tied = sum(1 for cx in candidates if cx.vote_count == top_votes) > 1
                    status = 'TIED' if tied else 'WINNER'
                rows.append([str(rank), c.name, str(c.vote_count), pct, status])

            # NOTA row
            if election.allow_abstain and voted > 0:
                voters_for_post = Vote.objects.filter(
                    post=post,
                ).values('voter_hash').distinct().count()
                abstain_count = voted - voters_for_post
                if abstain_count > 0:
                    pct = f"{abstain_count / voted * 100:.1f}%"
                    rows.append(['—', 'NOTA', str(abstain_count), pct, ''])

            t = Table(rows, colWidths=[0.5 * inch, W - 3.3 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch])
            t.setStyle(self._table_style(header_bg=colors.HexColor('#27ae60')))
            story.append(t)
            story.append(Spacer(1, 10))

        # ─── 6. Blockchain Record ─────────────────────────────────────
        if election.blockchain_contract_address:
            section += 1
            story.append(Paragraph(f"{section}. Blockchain Record", self.heading))
            bc_data = [
                ['Field', 'Value'],
                ['Network', f'Solana {getattr(django_settings, "SOLANA_NETWORK", "devnet").replace("-", " ").title()}'],
                ['Program Account', str(election.blockchain_contract_address)],
            ]
            if election.blockchain_deploy_tx:
                bc_data.append(['Deploy TX', str(election.blockchain_deploy_tx)])
            if election.config_hash:
                bc_data.append(['Config Hash', str(election.config_hash)])
            t = Table(bc_data, colWidths=[1.6 * inch, W - 1.6 * inch])
            t.setStyle(self._table_style(header_bg=colors.HexColor('#8e44ad')))
            story.append(t)
            story.append(Spacer(1, 14))

        # ─── N-1. Security Note ───────────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Security & Anonymization", self.heading))
        story.append(Paragraph(
            "<b>Security note:</b> Passwords are stored using Django's "
            "PBKDF2-SHA256 hasher. Voter-vote linkage is anonymized via "
            "SHA-256 hashing with a per-deployment salt. This audit trail "
            "contains aggregate data only — no individual vote choices are "
            "recorded or recoverable.",
            self.normal,
        ))
        story.append(Spacer(1, 16))

        # ─── N. Audit Event Log ───────────────────────────────────────
        section += 1
        story.append(Paragraph(f"{section}. Audit Event Log", self.heading))
        logs = AuditLog.objects.filter(election=election).order_by('-timestamp')[:500]
        if not logs:
            story.append(Paragraph("No audit entries found.", self.normal))
        else:
            rows = [['Time', 'Action', 'User', 'IP', 'Details']]
            for log in logs:
                detail_str = ''
                if log.details:
                    import json
                    try:
                        detail_str = json.dumps(log.details, default=str)
                        if len(detail_str) > 80:
                            detail_str = detail_str[:77] + '…'
                    except Exception:
                        detail_str = str(log.details)[:80]

                rows.append([
                    log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    log.get_action_display(),
                    log.user.username if log.user else '—',
                    log.ip_address or '—',
                    Paragraph(detail_str, small) if detail_str else '—',
                ])
            table = Table(
                rows,
                colWidths=[1.1 * inch, 1.4 * inch, 1.1 * inch, 1.0 * inch, W - 4.6 * inch],
            )
            table.setStyle(self._table_style(header_bg=colors.grey))
            story.append(table)

        doc.build(story)
        return self._response(buf, election, 'audit_trail')

    # ------------------------------------------------------------------
    # Offline voter credentials (Phase 3)
    # ------------------------------------------------------------------

    def generate_credentials_pdf(self, credentials: list[dict], election, pdf_password: str | None = None, batch_number: str = '') -> 'HttpResponse':
        """Generate a PDF with offline voter credentials.

        ``credentials`` is a list of dicts: ``[{name, username, password}, ...]``
        ``pdf_password`` when supplied, 128-bit AES encryption is applied.
        If None, a random 12-char password is generated and set as both user
        and owner password. The password is returned in the response header
        ``X-PDF-Password`` so the caller can display it to the admin.
        ``batch_number`` is displayed in the PDF header when provided.
        """
        password = pdf_password or secrets.token_urlsafe(12)
        owner_pwd = secrets.token_urlsafe(24)
        enc = StandardEncryption(
            userPassword=password,
            ownerPassword=owner_pwd,
            strength=128,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
            encrypt=enc,
        )

        # ── NEW credentials-specific header ──────────────────────────
        story = [
            Paragraph(f"Voter Credentials: {election.name}", self.title),
            Spacer(1, 6),
            Paragraph("<b>Type:</b> In-person Distribution", self.normal),
            Spacer(1, 4),
            Paragraph(
                f"<b>Start:</b> {election.start_time:%Y-%m-%d %H:%M} &nbsp;&nbsp; "
                f"<b>End:</b> {election.end_time:%Y-%m-%d %H:%M}",
                self.normal,
            ),
            Spacer(1, 4),
            Paragraph(
                f"<b>Generated at:</b> {timezone.now():%Y-%m-%d %H:%M:%S}"
                f" &nbsp;&nbsp; <b>Total Credentials:</b> {len(credentials)}"
                + (f" &nbsp;&nbsp; <b>Batch No:</b> {batch_number}" if batch_number else ""),
                self.normal,
            ),
            Spacer(1, 10),
            Paragraph(
                "<i>Distribute one credential per voter. Each credential can only be used once. "
                "Keep this document secure — anyone with a username + password can cast a vote.</i>",
                self.normal,
            ),
            Spacer(1, 16),
        ]
        # ─────────────────────────────────────────────────────────────

        rows = [['#', 'Voter Name', 'Username', 'Password']]
        for idx, cred in enumerate(credentials, 1):
            rows.append([
                str(idx),
                cred.get('name', '—'),
                cred['username'],
                cred['password'],
            ])

        col_widths = [0.4 * inch, 2 * inch, 2 * inch, 2.2 * inch]
        table = Table(rows, colWidths=col_widths)
        table.setStyle(self._table_style(header_bg=colors.darkgreen))
        story.append(table)

        doc.build(story)

        # Filename: {ElectionName}_{BatchNumber}.pdf  (sanitise for safety)
        import re as _re
        safe_name = _re.sub(r'[^\w\s-]', '', election.name).strip().replace(' ', '_')
        safe_batch = batch_number.replace(' ', '_') if batch_number else 'batch'
        filename = f"{safe_name}_{safe_batch}.pdf"

        buf.seek(0)
        response = HttpResponse(buf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['X-PDF-Password'] = password
        response['X-Batch-Number'] = batch_number or ''
        return response

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _election_header(self, election, report_title: str) -> list:
        story = [
            Paragraph(f"{report_title} — {election.name}", self.title),
            Spacer(1, 8),
            Paragraph(
                f"<b>Start:</b> {election.start_time:%Y-%m-%d %H:%M} &nbsp; | &nbsp; "
                f"<b>End:</b> {election.end_time:%Y-%m-%d %H:%M} &nbsp; | &nbsp; "
                f"<b>Status:</b> {election.current_status}<br/>"
                f"<b>Generated:</b> {timezone.now():%Y-%m-%d %H:%M:%S}",
                self.normal,
            ),
            Spacer(1, 20),
        ]
        return story

    @staticmethod
    def _table_style(header_bg=colors.grey):
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_bg),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ])

    @staticmethod
    def _response(buf: io.BytesIO, election, prefix: str) -> HttpResponse:
        buf.seek(0)
        ts = timezone.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(buf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="{prefix}_{election.election_uuid}_{ts}.pdf"'
        )
        return response
