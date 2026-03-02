"""ElectON v2 — Results URL configuration."""

from django.urls import path

from . import views

app_name = 'results'

urlpatterns = [
    # PDF downloads
    path(
        'pdf/voter-list/<uuid:election_uuid>/',
        views.VoterListPDFView.as_view(),
        name='voter_list_pdf',
    ),
    path(
        'pdf/results/<uuid:election_uuid>/',
        views.ElectionResultsPDFView.as_view(),
        name='results_pdf',
    ),
    path(
        'pdf/audit-trail/<uuid:election_uuid>/',
        views.AuditTrailPDFView.as_view(),
        name='audit_trail_pdf',
    ),

    # Charts & real-time data
    path(
        'charts/<uuid:election_uuid>/',
        views.ElectionChartsView.as_view(),
        name='election_charts',
    ),
    path(
        'api/real-time/<uuid:election_uuid>/',
        views.RealTimeDataAPIView.as_view(),
        name='real_time_data',
    ),

    # Results CSV / Excel exports
    path(
        'export/csv/<uuid:election_uuid>/',
        views.ExportResultsCSVView.as_view(),
        name='export_results_csv',
    ),
    path(
        'export/excel/<uuid:election_uuid>/',
        views.ExportResultsExcelView.as_view(),
        name='export_results_excel',
    ),
]
