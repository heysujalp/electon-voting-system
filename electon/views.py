"""
ElectON v2 — Root views (public home, legal pages + error handlers).
"""
from django.shortcuts import render
from django.views.generic import TemplateView


class PublicHomeView(TemplateView):
    """Public homepage — visible to unauthenticated users."""
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'ElectON — Secure Online Voting'
        return context


class PrivacyPolicyView(TemplateView):
    """GDPR-ready privacy policy page."""
    template_name = 'core/privacy_policy.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Privacy Policy — ElectON'
        return context


class TermsOfServiceView(TemplateView):
    """Terms of service page."""
    template_name = 'core/terms_of_service.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Terms of Service — ElectON'
        return context


def handler404_view(request, exception):
    """Custom 404 error page."""
    return render(request, 'errors/404.html', status=404)


def handler500_view(request):
    """Custom 500 error page."""
    return render(request, 'errors/500.html', status=500)
