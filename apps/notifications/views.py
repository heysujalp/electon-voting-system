"""
ElectON v2 — Notification views.

Provides API endpoints for election owners to send voter invitations,
check email status, and detect/resolve duplicate voters (Phase 5).
"""
import json
import logging

from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.views import View

from apps.elections.mixins import AjaxRateLimitMixin, ElectionOwnerMixin
from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential
from .models import EmailLog
from .services.email_service import EmailService

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Phase 5 — Duplicate Voter Detection
# ──────────────────────────────────────────────────────────────

class CheckDuplicatesView(AjaxRateLimitMixin, ElectionOwnerMixin, View):
    rate_limit_max = 20
    rate_limit_window = 60
    """
    Check for duplicate voters before sending invitations.

    POST /notifications/<election_uuid>/check-duplicates/
    Body: { "voters": [{"email": "...", "name": "..."}, ...] }

    Returns:
        {
            "has_duplicates": bool,
            "issues": {
                "duplicate_emails": [...],
                "duplicate_names": [...],
                "already_invited": [...]
            }
        }
    """

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

        voters = body.get('voters', [])
        if not voters or not isinstance(voters, list):
            return JsonResponse({'success': False, 'error': 'voters list is required.'}, status=400)

        # Build lookup of existing non-revoked credentials
        existing = election.voter_credentials.filter(is_revoked=False)
        existing_emails = {}
        existing_names = {}
        for c in existing:
            existing_emails[c.voter_email.strip().lower()] = c
            name = c.voter_name.strip().lower()
            if name:
                existing_names.setdefault(name, []).append(c)

        issues = {
            'duplicate_emails': [],
            'duplicate_names': [],
            'already_invited': [],
        }

        # Track all occurrences within the batch
        email_occurrences = {}   # email -> list of {index, email, name}
        name_occurrences = {}    # name_lower -> list of {index, email, name}

        for i, voter in enumerate(voters):
            email = (voter.get('email') or '').strip().lower()
            name = (voter.get('name') or '').strip()
            name_lower = name.lower()

            if not email:
                continue

            entry = {'index': i, 'email': voter.get('email', ''), 'name': name}

            # Collect all occurrences of each email
            email_occurrences.setdefault(email, []).append(entry)

            # Collect all occurrences of each name
            if name_lower:
                name_occurrences.setdefault(name_lower, []).append(entry)
            # --- 2. Already-invited check (email exists in DB) ---
            if email in existing_emails:
                cred = existing_emails[email]
                issues['already_invited'].append({
                    'email': email,
                    'name': name,
                    'existing_name': cred.voter_name,
                })

            # --- 3. Name match with existing DB voters (different email) ---
            if name_lower and name_lower in existing_names and email not in existing_emails:
                for existing_cred in existing_names[name_lower]:
                    issues['duplicate_names'].append({
                        'name': name,
                        'entries': [
                            entry,
                            {
                                'email': existing_cred.voter_email,
                                'name': existing_cred.voter_name,
                                'existing': True,
                            },
                        ],
                    })

        # --- Report ALL duplicate emails within the batch (not just pairs) ---
        for email, entries in email_occurrences.items():
            if len(entries) > 1:
                issues['duplicate_emails'].append({
                    'email': email,
                    'entries': entries,
                })

        # --- Report ALL duplicate names within the batch ---
        for name_lower, entries in name_occurrences.items():
            if len(entries) > 1:
                issues['duplicate_names'].append({
                    'name': entries[0]['name'],
                    'entries': entries,
                })

        has_issues = any(issues[k] for k in issues)

        return JsonResponse({
            'has_duplicates': has_issues,
            'issues': issues,
        })


class ResolveDuplicatesAndSendView(AjaxRateLimitMixin, ElectionOwnerMixin, View):
    rate_limit_max = 10
    rate_limit_window = 60
    """
    Resolve duplicate issues and send invitations.

    POST /notifications/<election_uuid>/resolve-and-send/
    Body: {
        "voters": [{"email": "...", "name": "..."}, ...],
        "reinvite": [credential_id, ...],
        "skip": ["email@example.com", ...]
    }
    """

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

        voters_to_create = data.get('voters', [])
        reinvite_ids = data.get('reinvite', [])
        skip_emails = set(e.strip().lower() for e in data.get('skip', []))

        pairs = []  # (credential, plain_password) tuples

        # Handle new voters inside a transaction
        with transaction.atomic():
            for voter in voters_to_create:
                email = (voter.get('email') or '').strip()
                name = (voter.get('name') or '').strip()
                email_lower = email.lower()

                if not email or email_lower in skip_emails:
                    continue

                # Skip if already exists for this election
                if election.voter_credentials.filter(voter_email__iexact=email).exists():
                    continue

                cred = VoterCredential.generate_credentials(
                    election=election,
                    voter_email=email,
                    voter_name=name,
                )
                pairs.append((cred, cred._plain_password))

            # Handle reinvitations (regenerate credentials for existing voters)
            for cred_id in reinvite_ids:
                try:
                    cred = VoterCredential.objects.select_for_update().get(
                        pk=cred_id, election=election,
                    )
                    if cred.has_voted:
                        continue  # Cannot reinvite someone who already voted

                    new_password = VoterCredential._generate_password()
                    cred.one_time_password_hash = make_password(new_password)
                    cred.invitation_sent = False
                    cred.invitation_error = ''
                    cred.invitation_error_code = ''
                    cred.save(update_fields=[
                        'one_time_password_hash', 'invitation_sent',
                        'invitation_error', 'invitation_error_code', 'updated_at',
                    ])
                    pairs.append((cred, new_password))
                except VoterCredential.DoesNotExist:
                    continue

        if not pairs:
            return JsonResponse({
                'success': True,
                'message': 'No invitations to send.',
                'sent': 0,
                'failed': 0,
            })

        # Send all invitations asynchronously via Celery
        from apps.notifications.tasks import send_bulk_invitations_task
        serializable_pairs = [(cred.pk, pwd) for cred, pwd in pairs]
        send_bulk_invitations_task.delay(serializable_pairs, election.pk)

        return JsonResponse({
            'success': True,
            'message': f'{len(pairs)} invitation(s) queued for delivery.',
            'sent': len(pairs),
            'failed': 0,
        })


# ──────────────────────────────────────────────────────────────
# Invitation sending & email status
# ──────────────────────────────────────────────────────────────

class SendVoterInvitationsView(AjaxRateLimitMixin, ElectionOwnerMixin, View):
    rate_limit_max = 5
    rate_limit_window = 60
    """Trigger bulk email sending for all un-invited, non-offline voters."""

    def post(self, request, election_uuid):
        election = self.get_election(election_uuid)

        # Gather email credentials that haven't been invited yet
        # Exclude offline voters (@electon.local) and revoked voters
        unsent = VoterCredential.objects.filter(
            election=election,
            invitation_sent=False,
            is_revoked=False,
        ).exclude(voter_email__endswith=OFFLINE_VOTER_DOMAIN)

        if not unsent.exists():
            return JsonResponse({'success': True, 'message': 'All voters have already been invited.'})

        pairs = []
        for vc in unsent:
            # Always generate a fresh password for invitation emails
            # (DB-fetched credentials never have transient _plain_password)
            password = VoterCredential._generate_password()
            vc.one_time_password_hash = make_password(password)
            # BUG-16: clear stale error so badge updates immediately on reload
            vc.invitation_error = ''
            vc.invitation_error_code = ''
            vc.save(update_fields=[
                'one_time_password_hash',
                'invitation_error', 'invitation_error_code',
                'updated_at',
            ])
            pairs.append((vc, password))

        # Send invitations asynchronously via Celery
        from apps.notifications.tasks import send_bulk_invitations_task
        serializable_pairs = [(cred.pk, pwd) for cred, pwd in pairs]
        send_bulk_invitations_task.delay(serializable_pairs, election.pk)

        return JsonResponse({
            'success': True,
            'message': f'{len(pairs)} invitation(s) queued for delivery.',
        })


class EmailStatusView(ElectionOwnerMixin, View):
    """Return email log summary for an election."""

    def get(self, request, election_uuid):
        election = self.get_election(election_uuid)

        base_qs = EmailLog.objects.filter(election=election)
        total = base_qs.count()
        logs = base_qs.order_by('-created_at')[:100]
        return JsonResponse({
            'success': True,
            'total': total,
            'logs': [
                {
                    'recipient': log.recipient_email,
                    'subject': log.subject,
                    'status': log.status,
                    'error': log.error_message,
                    'sent_at': log.sent_at.isoformat() if log.sent_at else None,
                    'created_at': log.created_at.isoformat(),
                }
                for log in logs
            ],
        })


class FailedInvitationsView(ElectionOwnerMixin, View):
    """
    GET /notifications/<election_uuid>/failed-invitations/

    Returns the list of email-voter credentials whose invitation currently
    has a delivery failure (invitation_sent=False, invitation_error not empty,
    has_voted=False, is_revoked=False).

    Used by the frontend to show the failure-details popup immediately
    after a bulk-send operation completes.

    Response::

        {
            "total": 2,
            "failures": [
                {
                    "credential_id":  42,
                    "voter_email":    "bad@example.com",
                    "voter_name":     "John Doe",
                    "error_code":     "INVALID_FORMAT",
                    "error_message":  "Invalid email address format: 'bad@example.com'",
                    "error_label":    "Invalid email address format",
                    "failed_at":      "2026-02-28T10:00:00Z"
                },
                ...
            ]
        }
    """

    def get(self, request, election_uuid):
        from apps.notifications.services.email_service import ERROR_CODE_LABELS
        from apps.voting.models import OFFLINE_VOTER_DOMAIN, VoterCredential

        election = self.get_election(election_uuid)

        failures = (
            VoterCredential.objects
            .filter(
                election=election,
                invitation_sent=False,
                has_voted=False,
                is_revoked=False,
            )
            .exclude(invitation_error='')
            .exclude(voter_email__endswith=OFFLINE_VOTER_DOMAIN)
            .order_by('-updated_at')
            .values(
                'id', 'voter_email', 'voter_name',
                'invitation_error_code', 'invitation_error', 'updated_at',
            )
        )

        failure_list = [
            {
                'credential_id':  f['id'],
                'voter_email':    f['voter_email'],
                'voter_name':     f['voter_name'] or '',
                'error_code':     f['invitation_error_code'] or 'UNKNOWN',
                'error_message':  f['invitation_error'],
                'error_label':    ERROR_CODE_LABELS.get(
                    f['invitation_error_code'] or 'UNKNOWN',
                    'Unknown delivery failure',
                ),
                'failed_at': (
                    f['updated_at'].isoformat() if f['updated_at'] else None
                ),
            }
            for f in failures
        ]

        return JsonResponse({
            'total':    len(failure_list),
            'failures': failure_list,
        })

