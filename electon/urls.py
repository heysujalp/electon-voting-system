"""
ElectON v2 — Root URL configuration.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from .views import PublicHomeView, PrivacyPolicyView, TermsOfServiceView, handler404_view, handler500_view

urlpatterns = [
    path('', PublicHomeView.as_view(), name='public_home'),
    path('privacy/', PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('terms/', TermsOfServiceView.as_view(), name='terms_of_service'),
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('elections/', include('apps.elections.urls')),
    path('candidates/', include('apps.candidates.urls')),
    path('voting/', include('apps.voting.urls')),
    path('results/', include('apps.results.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('blockchain/', include('apps.blockchain.urls')),
    path('api/v1/', include(('apps.api.urls', 'api'), namespace='api-v1')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Django Debug Toolbar
    try:
        import debug_toolbar
        urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

# Custom error handlers
handler404 = handler404_view
handler500 = handler500_view

# Admin site customization
admin.site.site_header = 'ElectON Administration'
admin.site.site_title = 'ElectON Admin'
admin.site.index_title = 'Dashboard'
