"""
DRF serializers for the ElectON API.

No models live in this app — all serializers reference models from
elections, candidates, voting, and blockchain apps.
"""

from rest_framework import serializers

from apps.candidates.models import Candidate
from apps.elections.models import Election, Post


# ──────────────────────────────────────────────
#  Nested serializers
# ──────────────────────────────────────────────

class CandidateSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = ["id", "name", "bio", "image_url"]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class PostSerializer(serializers.ModelSerializer):
    candidates = CandidateSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = ["id", "name", "order", "candidates"]


# ──────────────────────────────────────────────
#  Election serializers
# ──────────────────────────────────────────────

class ElectionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for election lists."""

    post_count = serializers.IntegerField(read_only=True)
    voter_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Election
        fields = [
            "election_uuid",
            "name",
            "current_status",
            "start_time",
            "end_time",
            "timezone",
            "allow_voter_results_view",
            "post_count",
            "voter_count",
            "created_at",
        ]


class ElectionDetailSerializer(serializers.ModelSerializer):
    """Full election detail with nested posts and candidates."""

    posts = PostSerializer(many=True, read_only=True)
    post_count = serializers.IntegerField(read_only=True)
    voter_count = serializers.IntegerField(read_only=True)
    votes_cast = serializers.IntegerField(read_only=True)

    class Meta:
        model = Election
        fields = [
            "election_uuid",
            "name",
            "current_status",
            "start_time",
            "end_time",
            "timezone",
            "admin_message",
            "allow_voter_results_view",
            "blockchain_contract_address",
            "post_count",
            "voter_count",
            "votes_cast",
            "posts",
            "created_at",
            "updated_at",
        ]


# ──────────────────────────────────────────────
#  Results serializer
# ──────────────────────────────────────────────

class CandidateResultSerializer(serializers.Serializer):
    """Candidate with vote count for results."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    vote_count = serializers.IntegerField()


class PostResultSerializer(serializers.Serializer):
    """Post with candidates and their vote counts."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    candidates = CandidateResultSerializer(many=True)


class ElectionResultsSerializer(serializers.Serializer):
    """Full election results response."""

    election_uuid = serializers.UUIDField()
    election_name = serializers.CharField()
    total_voters = serializers.IntegerField()
    total_votes_cast = serializers.IntegerField()
    turnout_percentage = serializers.FloatField()
    posts = PostResultSerializer(many=True)


# ──────────────────────────────────────────────
#  Voter / voting serializers
# ──────────────────────────────────────────────

class VoterLoginSerializer(serializers.Serializer):
    """Input serializer for voter login."""

    username = serializers.CharField(max_length=150, required=True)
    password = serializers.CharField(max_length=128, required=True)
    election_uuid = serializers.UUIDField(required=True)


class VoteCastSerializer(serializers.Serializer):
    """Input serializer for casting votes."""

    # Dict of { post_id: candidate_id }
    votes = serializers.DictField(
        child=serializers.IntegerField(),
        required=True,
        help_text="Mapping of post_id → candidate_id.",
    )


# ──────────────────────────────────────────────
#  Blockchain serializer
# ──────────────────────────────────────────────

class BlockchainVerifySerializer(serializers.Serializer):
    """Response serializer for Solana vote verification."""

    verified = serializers.BooleanField()
    voter_hash = serializers.CharField()
    error = serializers.CharField(allow_null=True)
