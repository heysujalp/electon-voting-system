"""ElectON v2 — Voting URL configuration."""

from django.urls import path

from . import views

app_name = 'voting'

urlpatterns = [
    # Voter login page
    path('login/', views.VoterLoginPageView.as_view(), name='voter_login'),

    # Voting interface
    path('vote/', views.VoteView.as_view(), name='vote'),

    # Voter access
    path(
        'access-denied/<uuid:election_uuid>/',
        views.VoterAccessDeniedView.as_view(),
        name='voter_access_denied',
    ),
    path(
        'request-access/',
        views.VoterAccessRequestView.as_view(),
        name='voter_access_request',
    ),
    path(
        'results/<uuid:election_uuid>/',
        views.VoterElectionResultsView.as_view(),
        name='voter_election_results',
    ),

    # API
    path('api/voter-login/', views.VoterLoginView.as_view(), name='api_voter_login'),
]
