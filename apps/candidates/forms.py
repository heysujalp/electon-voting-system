"""
ElectON v2 — Candidate & voter-import forms.
"""
from django import forms
from django.conf import settings


class BulkVoterUploadForm(forms.Form):
    """Form for uploading a CSV/Excel file of voters."""

    voter_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls',
        }),
    )

    def clean_voter_file(self):
        f = self.cleaned_data['voter_file']
        max_size = settings.ELECTON_SETTINGS.get('MAX_UPLOAD_SIZE', 5 * 1024 * 1024)

        if f.size > max_size:
            raise forms.ValidationError(
                f"File too large. Maximum size is {max_size // (1024 * 1024)} MB."
            )

        allowed = ('.csv', '.xlsx', '.xls')
        if not f.name.lower().endswith(allowed):
            raise forms.ValidationError(
                f"Invalid file format. Allowed: {', '.join(allowed)}."
            )

        return f
