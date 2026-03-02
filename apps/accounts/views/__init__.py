"""ElectON v2 — Accounts views package."""
from .auth import AdminLoginView, LogoutView
from .registration import RegisterView, EmailVerificationView, SecurityQuestionsView
from .password import (
    ForgotPasswordView,
    ResetVerifyQuestionsView,
    ResetVerifyCodeView,
    ResetPasswordView,
)
from .profile import (
    AccountSettingsView,
    UpdateFullNameView,
    UpdateUsernameView,
    UpdatePasswordView,
    UpdateSecurityQuestionsView,
    DeleteAccountView,
    VerifyPasswordView,
    CheckUsernameView,
    UpdateEmailView,
    VerifyEmailChangeView,
)

__all__ = [
    'AdminLoginView',
    'LogoutView',
    'RegisterView',
    'EmailVerificationView',
    'SecurityQuestionsView',
    'ForgotPasswordView',
    'ResetVerifyQuestionsView',
    'ResetVerifyCodeView',
    'ResetPasswordView',
    'AccountSettingsView',
    'UpdateFullNameView',
    'UpdateUsernameView',
    'UpdatePasswordView',
    'UpdateSecurityQuestionsView',
    'DeleteAccountView',
    'VerifyPasswordView',
    'CheckUsernameView',
    'UpdateEmailView',
    'VerifyEmailChangeView',
]
