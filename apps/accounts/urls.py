"""
ElectON v2 — Accounts URL configuration.
"""
from django.urls import path

from .views import (
    AccountSettingsView,
    AdminLoginView,
    CheckUsernameView,
    DeleteAccountView,
    EmailVerificationView,
    ForgotPasswordView,
    LogoutView,
    RegisterView,
    ResetPasswordView,
    ResetVerifyCodeView,
    ResetVerifyQuestionsView,
    SecurityQuestionsView,
    UpdateEmailView,
    UpdateFullNameView,
    UpdatePasswordView,
    UpdateSecurityQuestionsView,
    UpdateUsernameView,
    VerifyEmailChangeView,
    VerifyPasswordView,
)
from .views.auth import AdminLoginVerificationView

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('login/', AdminLoginView.as_view(), name='login'),
    path('login/verify/', AdminLoginVerificationView.as_view(), name='admin_login_verification'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Registration & Email Verification
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-email/', EmailVerificationView.as_view(), name='email_verification'),
    path('register/security-questions/', SecurityQuestionsView.as_view(), name='security_questions'),

    # Password Reset (4-step flow)
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('forgot-password/security-questions/', ResetVerifyQuestionsView.as_view(), name='reset_verify_questions'),
    path('forgot-password/verify-code/', ResetVerifyCodeView.as_view(), name='reset_verify_code'),
    path('forgot-password/new-password/', ResetPasswordView.as_view(), name='reset_password'),

    # Profile
    path('settings/', AccountSettingsView.as_view(), name='account_settings'),
    path('settings/update-name/', UpdateFullNameView.as_view(), name='update_full_name'),
    path('settings/update-username/', UpdateUsernameView.as_view(), name='update_username'),
    path('settings/update-password/', UpdatePasswordView.as_view(), name='update_password'),
    path('settings/send-email-code/', UpdateEmailView.as_view(), name='send_email_code'),
    path('settings/verify-email-change/', VerifyEmailChangeView.as_view(), name='verify_email_change'),
    path('settings/check-username/', CheckUsernameView.as_view(), name='check_username'),
    path('settings/update-security-questions/', UpdateSecurityQuestionsView.as_view(), name='update_security_questions'),
    path('settings/delete-account/', DeleteAccountView.as_view(), name='delete_account'),
    path('settings/verify-password/', VerifyPasswordView.as_view(), name='verify_password'),
]
