"""
Custom DRF permissions for the ElectON API.
"""

from rest_framework.permissions import BasePermission


class IsElectionOwner(BasePermission):
    """
    Allow access only if the authenticated user owns the election.
    Expects the view to set `self.election` or the object to have a `created_by` field.
    """

    message = "You do not have permission to access this election."

    def has_object_permission(self, request, view, obj):
        return obj.created_by_id == request.user.pk


class HasVoterSession(BasePermission):
    """
    Allow access only if the request has a valid voter session.
    The voting views store voter info in the session after voter login.
    """

    message = "Voter session required. Please log in first."

    def has_permission(self, request, view):
        cred_id = request.session.get("voter_credential_id")
        election_uuid = request.session.get("election_uuid")
        if not (cred_id and election_uuid):
            return False

        # Verify the credential actually belongs to the claimed election
        from apps.voting.models import VoterCredential
        try:
            cred = VoterCredential.objects.only("election_id", "election__election_uuid").select_related("election").get(pk=cred_id)
        except VoterCredential.DoesNotExist:
            return False

        return str(cred.election.election_uuid) == election_uuid
