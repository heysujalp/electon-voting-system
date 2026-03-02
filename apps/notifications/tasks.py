"""
ElectON v2 — Notification Celery tasks.
Offloads email sending to background workers to avoid blocking HTTP requests.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from celery import shared_task

    @shared_task(bind=True, max_retries=3, default_retry_delay=60)
    def send_bulk_invitations_task(self, credential_password_pairs, election_id):
        """
        Async bulk email sending for voter invitations.

        Args:
            credential_password_pairs: list of (credential_id, plain_password) tuples
            election_id: Election PK
        """
        from apps.elections.models import Election
        from apps.notifications.services.email_service import EmailService
        from apps.voting.models import VoterCredential

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("send_bulk_invitations_task: election %s not found", election_id)
            return {'sent': 0, 'failed': 0, 'errors': ['Election not found']}

        pairs = []
        for cred_id, pwd in credential_password_pairs:
            try:
                cred = VoterCredential.objects.get(pk=cred_id, election=election)
                pairs.append((cred, pwd))
            except VoterCredential.DoesNotExist:
                logger.warning("Credential %s not found for election %s", cred_id, election_id)

        if not pairs:
            return {'sent': 0, 'failed': 0, 'errors': ['No valid credentials']}

        result = EmailService.send_bulk_voter_invitations(pairs, election)
        logger.info(
            "Bulk invitations for election %s: sent=%d failed=%d",
            election.election_uuid, result['sent'], result['failed'],
        )
        return result

except ImportError:
    # Celery not installed — provide a synchronous fallback
    def _send_bulk_invitations_sync(credential_password_pairs, election_id):
        """Synchronous fallback when Celery is not available."""
        from apps.elections.models import Election
        from apps.notifications.services.email_service import EmailService
        from apps.voting.models import VoterCredential

        election = Election.objects.get(pk=election_id)
        pairs = []
        for cred_id, pwd in credential_password_pairs:
            try:
                cred = VoterCredential.objects.get(pk=cred_id, election=election)
                pairs.append((cred, pwd))
            except VoterCredential.DoesNotExist:
                pass
        return EmailService.send_bulk_voter_invitations(pairs, election)

    # Expose under the canonical name; add .delay shim for call-site compatibility
    send_bulk_invitations_task = _send_bulk_invitations_sync  # type: ignore[assignment]
    setattr(send_bulk_invitations_task, 'delay', _send_bulk_invitations_sync)
