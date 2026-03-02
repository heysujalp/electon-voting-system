"""
ElectON v2 — Elections URL configuration.
"""
from django.urls import path

from . import sse, views

app_name = 'elections'

urlpatterns = [
    # SSE streams
    path('user-stream/', sse.UserSSEView.as_view(), name='user_stream'),

    path('manage/', views.ManageMyElectionsView.as_view(), name='manage'),
    path('create/', views.CreateElectionView.as_view(), name='create'),
    path('<uuid:election_uuid>/', views.ElectionDashboardView.as_view(), name='dashboard'),
    path('<uuid:election_uuid>/edit/', views.EditElectionView.as_view(), name='edit'),
    path('<uuid:election_uuid>/launch/', views.LaunchElectionView.as_view(), name='launch'),

    path('<uuid:election_uuid>/update-name/', views.UpdateElectionNameView.as_view(), name='update_name'),
    path('<uuid:election_uuid>/update-period/', views.UpdateVotingPeriodView.as_view(), name='update_period'),
    path('<uuid:election_uuid>/update-message/', views.UpdateAdminMessageView.as_view(), name='update_message'),
    path('<uuid:election_uuid>/update-abstain/', views.UpdateAbstainView.as_view(), name='update_abstain'),
    path('<uuid:election_uuid>/delete/', views.DeleteElectionView.as_view(), name='delete'),
    path('<uuid:election_uuid>/duplicate/', views.DuplicateElectionView.as_view(), name='duplicate'),
    path('<uuid:election_uuid>/add-post/', views.AddPostView.as_view(), name='add_post'),
    path('<uuid:election_uuid>/add-posts-bulk/', views.AddPostsBulkView.as_view(), name='add_posts_bulk'),
    path('<uuid:election_uuid>/delete-post/<int:post_id>/', views.DeletePostView.as_view(), name='delete_post'),
    path('<uuid:election_uuid>/rename-post/<int:post_id>/', views.RenamePostView.as_view(), name='rename_post'),
    path('<uuid:election_uuid>/preview/', views.PreviewBallotView.as_view(), name='preview_ballot'),

    path('<uuid:election_uuid>/bulk-import/', views.BulkElectionImportView.as_view(), name='bulk_import'),
    path('<uuid:election_uuid>/reorder-posts/', views.ReorderPostsView.as_view(), name='reorder_posts'),
    path('<uuid:election_uuid>/delete-all-posts/', views.DeleteAllPostsView.as_view(), name='delete_all_posts'),
    path('<uuid:election_uuid>/export-positions-pdf/', views.ExportPositionsPDFView.as_view(), name='export_positions_pdf'),
    path('<uuid:election_uuid>/post-candidates/<int:post_id>/', views.GetPostCandidatesView.as_view(), name='post_candidates'),

    # Export endpoints
    path('<uuid:election_uuid>/template/<str:template_type>/', views.ExportTemplateView.as_view(), name='export_template'),
    path('<uuid:election_uuid>/export/', views.ExportElectionDataView.as_view(), name='export_data'),

    # Live stats API (dashboard & admin home refresh)
    path('<uuid:election_uuid>/stats/', views.ElectionStatsView.as_view(), name='election_stats'),
    path('<uuid:election_uuid>/stream/', sse.ElectionSSEView.as_view(), name='election_stream'),

    # Voter access requests (admin-facing)
    path('<uuid:election_uuid>/access-requests/', views.AccessRequestListView.as_view(), name='access_requests'),
    path('<uuid:election_uuid>/access-requests/<int:request_id>/approve/', views.ApproveAccessRequestView.as_view(), name='approve_access_request'),
    path('<uuid:election_uuid>/access-requests/<int:request_id>/reject/', views.RejectAccessRequestView.as_view(), name='reject_access_request'),
]
