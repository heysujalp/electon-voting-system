"""ElectON v2 — Candidates URL configuration."""

from django.urls import path

from . import views

app_name = 'candidates'

urlpatterns = [
    # Candidate CRUD
    path(
        '<uuid:election_uuid>/candidate/<int:candidate_id>/delete/',
        views.DeleteCandidateView.as_view(),
        name='delete_candidate',
    ),
    path(
        '<uuid:election_uuid>/candidate/<int:candidate_id>/update-image/',
        views.UpdateCandidateImageView.as_view(),
        name='update_candidate_image',
    ),
    path(
        '<uuid:election_uuid>/candidate/<int:candidate_id>/presign-upload/',
        views.GenerateUploadUrlView.as_view(),
        name='presign_candidate_upload',
    ),
    path(
        '<uuid:election_uuid>/candidate/<int:candidate_id>/confirm-upload/',
        views.ConfirmUploadView.as_view(),
        name='confirm_candidate_upload',
    ),
    path(
        '<uuid:election_uuid>/candidate/<int:candidate_id>/update/',
        views.UpdateCandidateView.as_view(),
        name='update_candidate',
    ),
    path(
        '<uuid:election_uuid>/post/<int:post_id>/add-candidates-bulk/',
        views.AddCandidatesBulkView.as_view(),
        name='add_candidates_bulk',
    ),
    path(
        '<uuid:election_uuid>/post/<int:post_id>/reorder-candidates/',
        views.ReorderCandidatesView.as_view(),
        name='reorder_candidates',
    ),

    # Voter import / export
    path(
        '<uuid:election_uuid>/import-voters/',
        views.ImportVotersView.as_view(),
        name='import_voters',
    ),
    path(
        '<uuid:election_uuid>/parse-voter-file/',
        views.ParseVoterFileView.as_view(),
        name='parse_voter_file',
    ),
    path(
        '<uuid:election_uuid>/export-voters/csv/',
        views.ExportVotersCSVView.as_view(),
        name='export_voters_csv',
    ),
    path(
        '<uuid:election_uuid>/export-voters/excel/',
        views.ExportVotersExcelView.as_view(),
        name='export_voters_excel',
    ),
    path(
        '<uuid:election_uuid>/export-voters/pdf/',
        views.ExportVotersPDFView.as_view(),
        name='export_voters_pdf',
    ),

    # Sample template download
    path(
        'download-template/<str:fmt>/',
        views.DownloadTemplateView.as_view(),
        name='download_template',
    ),

    # FEAT-04: Credential regeneration
    path(
        '<uuid:election_uuid>/voter/<int:credential_id>/regenerate/',
        views.RegenerateCredentialView.as_view(),
        name='regenerate_credential',
    ),

    # FEAT-08: Bulk candidate import
    path(
        '<uuid:election_uuid>/import-candidates/',
        views.ImportCandidatesView.as_view(),
        name='import_candidates',
    ),
    path(
        '<uuid:election_uuid>/candidate-template/<str:fmt>/',
        views.DownloadCandidateTemplateView.as_view(),
        name='download_candidate_template',
    ),

    # Phase 3: Offline credentials & voter revoke
    path(
        '<uuid:election_uuid>/generate-offline-creds/',
        views.GenerateOfflineCredentialsView.as_view(),
        name='generate_offline_creds',
    ),
    path(
        '<uuid:election_uuid>/voter/<int:credential_id>/revoke/',
        views.RevokeVoterView.as_view(),
        name='revoke_voter',
    ),

    # Bulk voter actions
    path(
        '<uuid:election_uuid>/voters/revoke-all/',
        views.RevokeAllVotersView.as_view(),
        name='revoke_all_voters',
    ),
    path(
        '<uuid:election_uuid>/voters/resend-all/',
        views.ResendAllInvitationsView.as_view(),
        name='resend_all_invitations',
    ),
    path(
        '<uuid:election_uuid>/voters/revoke-batch/<str:batch>/',
        views.RevokeBatchView.as_view(),
        name='revoke_batch',
    ),
    path(
        '<uuid:election_uuid>/voters/revoke-all-batches/',
        views.RevokeAllBatchesView.as_view(),
        name='revoke_all_batches',
    ),
]
