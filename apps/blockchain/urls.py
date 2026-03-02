"""Blockchain app URL configuration."""

from django.urls import path

from . import views

app_name = "blockchain"

urlpatterns = [
    path(
        "<uuid:election_uuid>/verify/",
        views.VerifyVoteView.as_view(),
        name="verify_vote",
    ),
    path(
        "<uuid:election_uuid>/integrity/",
        views.IntegrityCheckView.as_view(),
        name="integrity_check",
    ),
]
