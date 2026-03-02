"""API URL configuration."""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    # Health check
    path("health/", views.HealthCheckView.as_view(), name="health"),
    # Election endpoints (admin)
    path("elections/", views.ElectionListView.as_view(), name="election_list"),
    path(
        "elections/<uuid:election_uuid>/",
        views.ElectionDetailView.as_view(),
        name="election_detail",
    ),
    path(
        "elections/<uuid:election_uuid>/results/",
        views.ElectionResultsView.as_view(),
        name="election_results",
    ),
    # Voter endpoints
    path("voting/login/", views.VoterLoginView.as_view(), name="voter_login"),
    path("voting/cast/", views.VoteCastView.as_view(), name="vote_cast"),
    # Blockchain verification
    path(
        "blockchain/verify/<uuid:election_uuid>/",
        views.BlockchainVerifyView.as_view(),
        name="blockchain_verify",
    ),
]
