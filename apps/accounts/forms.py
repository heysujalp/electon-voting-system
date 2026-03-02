"""
ElectON v2 — Accounts forms.
All password validation uses constants from accounts.constants (single source).
"""
import re

from django import forms
from django.contrib.auth import get_user_model

from .constants import (
    MAX_ANSWER_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PASSWORD_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_ANSWER_LENGTH,
    MIN_PASSWORD_LENGTH,
    MIN_USERNAME_LENGTH,
    NAME_ERROR_MSG,
    NAME_PATTERN,
    PASSWORD_REQUIRES_DIGIT,
    PASSWORD_REQUIRES_LOWERCASE,
    PASSWORD_REQUIRES_SPECIAL,
    PASSWORD_REQUIRES_UPPERCASE,
    SECURITY_QUESTIONS,
    SECURITY_QUESTIONS_REQUIRED,
    USERNAME_ERROR_MSG,
    USERNAME_PATTERN,
)

User = get_user_model()


def validate_password_strength(password: str, username: str = '', email: str = '') -> list[str]:
    """
    Validate password strength. Returns list of error messages (empty = valid).
    Single implementation used by all forms. References constants for each rule.
    """
    errors = []

    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f'Password must be at most {MAX_PASSWORD_LENGTH} characters.')
    if PASSWORD_REQUIRES_UPPERCASE and not re.search(r'[A-Z]', password):
        errors.append('Password must contain at least one uppercase letter.')
    if PASSWORD_REQUIRES_LOWERCASE and not re.search(r'[a-z]', password):
        errors.append('Password must contain at least one lowercase letter.')
    if PASSWORD_REQUIRES_DIGIT and not re.search(r'\d', password):
        errors.append('Password must contain at least one digit.')
    if PASSWORD_REQUIRES_SPECIAL and not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', password):
        errors.append('Password must contain at least one special character.')

    # Use Django's built-in 20K common password list
    from django.contrib.auth.password_validation import CommonPasswordValidator
    try:
        CommonPasswordValidator().validate(password)
    except forms.ValidationError:
        errors.append('This password is too common.')

    if username and len(username) >= 3 and username.lower() in password.lower():
        errors.append('Password cannot contain your username.')
    if email and email.split('@')[0].lower() in password.lower():
        errors.append('Password cannot contain your email address.')

    return errors


class RegistrationForm(forms.Form):
    """Admin account registration form."""
    username = forms.CharField(
        min_length=MIN_USERNAME_LENGTH,
        max_length=MAX_USERNAME_LENGTH,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Choose a username',
            'autocomplete': 'username',
            'aria-describedby': 'id_username-error',
        }),
    )
    full_name = forms.CharField(
        max_length=MAX_NAME_LENGTH,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your full name',
            'autocomplete': 'name',
            'aria-describedby': 'id_full_name-error',
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'your@email.com',
            'autocomplete': 'email',
            'aria-describedby': 'id_email-error',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password',
            'aria-describedby': 'passwordMeter id_password-error',
        }),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password',
            'aria-describedby': 'passwordMatch id_confirm_password-error',
        }),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError(USERNAME_ERROR_MSG)
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_full_name(self):
        name = self.cleaned_data['full_name'].strip()
        if not NAME_PATTERN.match(name):
            raise forms.ValidationError(NAME_ERROR_MSG)
        return name

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password', '')
        confirm = cleaned.get('confirm_password', '')

        if password and confirm and password != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')

        if password:
            errors = validate_password_strength(
                password,
                username=cleaned.get('username', ''),
                email=cleaned.get('email', ''),
            )
            for error in errors:
                self.add_error('password', error)

        return cleaned


class AdminLoginForm(forms.Form):
    """Admin login form."""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'autocomplete': 'username',
            'aria-describedby': 'id_username-error',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'autocomplete': 'current-password',
            'aria-describedby': 'id_password-error',
        }),
    )


class CleanCodeMixin:
    """Shared clean_code() for 6-digit OTP forms."""

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit():
            raise forms.ValidationError('Code must contain only digits.')
        return code


class EmailVerificationForm(CleanCodeMixin, forms.Form):
    """6-digit OTP code verification form."""
    code = forms.CharField(
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control text-center',
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': r'\d{6}',
            'maxlength': '6',
        }),
    )


class AdminLoginVerificationForm(CleanCodeMixin, forms.Form):
    """Admin login 2FA verification form."""
    code = forms.CharField(
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control text-center',
            'placeholder': '000000',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
        }),
    )


class ForgotPasswordForm(forms.Form):
    """Request password reset link via email."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'your@email.com',
            'autocomplete': 'email',
        }),
    )


class ResetPasswordForm(forms.Form):
    """Set a new password using a reset token."""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password',
            'autocomplete': 'new-password',
        }),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password', '')
        confirm = cleaned.get('confirm_password', '')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')
        if password:
            username = getattr(self.user, 'username', None) if self.user else None
            email = getattr(self.user, 'email', None) if self.user else None
            errors = validate_password_strength(password, username=username, email=email)
            for error in errors:
                self.add_error('password', error)
        return cleaned


class UpdateFullNameForm(forms.Form):
    """Update full name."""
    full_name = forms.CharField(
        max_length=MAX_NAME_LENGTH,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def clean_full_name(self):
        name = self.cleaned_data['full_name'].strip()
        if not NAME_PATTERN.match(name):
            raise forms.ValidationError(NAME_ERROR_MSG)
        return name


class UpdateUsernameForm(forms.Form):
    """Update username."""
    username = forms.CharField(
        min_length=MIN_USERNAME_LENGTH,
        max_length=MAX_USERNAME_LENGTH,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError(USERNAME_ERROR_MSG)
        qs = User.objects.filter(username__iexact=username)
        if self.current_user:
            qs = qs.exclude(pk=self.current_user.pk)
        if qs.exists():
            raise forms.ValidationError('This username is already taken.')
        return username


class UpdatePasswordForm(forms.Form):
    """Change password (requires current password)."""
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
        }),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        new_pw = cleaned.get('new_password', '')
        confirm = cleaned.get('confirm_password', '')
        if new_pw and confirm and new_pw != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')
        if new_pw:
            username = getattr(self.user, 'username', None) if self.user else None
            email = getattr(self.user, 'email', None) if self.user else None
            errors = validate_password_strength(new_pw, username=username, email=email)
            for error in errors:
                self.add_error('new_password', error)
        return cleaned


# ─── Security Questions Forms ────────────────────────────────────

class SecurityQuestionsSetupForm(forms.Form):
    """
    Step 3 of registration — user picks 3 unique questions and answers each.
    Fields are named question_1..3 / answer_1..3.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', 'Select a security question…')] + list(SECURITY_QUESTIONS)
        for i in range(1, SECURITY_QUESTIONS_REQUIRED + 1):
            self.fields[f'question_{i}'] = forms.ChoiceField(
                choices=choices,
                widget=forms.Select(attrs={
                    'class': 'form-control security-q-select',
                    'data-index': str(i),
                }),
            )
            self.fields[f'answer_{i}'] = forms.CharField(
                min_length=MIN_ANSWER_LENGTH,
                max_length=MAX_ANSWER_LENGTH,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'Your answer',
                    'autocomplete': 'off',
                }),
            )

    def clean(self):
        cleaned = super().clean()
        chosen_keys = []
        for i in range(1, SECURITY_QUESTIONS_REQUIRED + 1):
            key = cleaned.get(f'question_{i}')
            if key:
                if key in chosen_keys:
                    self.add_error(f'question_{i}', 'Each question must be different.')
                chosen_keys.append(key)
        return cleaned


class SecurityQuestionsVerifyForm(forms.Form):
    """
    Verify security-question answers (forgot-password / delete-account).
    Dynamically built from the user's stored questions.
    """

    def __init__(self, *args, question_keys=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.question_keys = question_keys or []
        question_map = dict(SECURITY_QUESTIONS)
        for i, key in enumerate(self.question_keys, start=1):
            self.fields[f'answer_{i}'] = forms.CharField(
                label=question_map.get(key, key),
                min_length=MIN_ANSWER_LENGTH,
                max_length=MAX_ANSWER_LENGTH,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'Your answer',
                    'autocomplete': 'off',
                }),
            )
