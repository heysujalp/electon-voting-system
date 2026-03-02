"""ElectON v2 — Notifications URL configuration."""

from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path(
        '<uuid:election_uuid>/send-invitations/',
        views.SendVoterInvitationsView.as_view(),
        name='send_invitations',
    ),
    path(
        '<uuid:election_uuid>/email-status/',
        views.EmailStatusView.as_view(),
        name='email_status',
    ),
    path(
        '<uuid:election_uuid>/check-duplicates/',
        views.CheckDuplicatesView.as_view(),
        name='check_duplicates',
    ),
    path(
        '<uuid:election_uuid>/resolve-and-send/',
        views.ResolveDuplicatesAndSendView.as_view(),
        name='resolve_and_send',
    ),
    path(
        '<uuid:election_uuid>/failed-invitations/',
        views.FailedInvitationsView.as_view(),
        name='failed_invitations',
    ),
]
