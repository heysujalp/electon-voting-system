"""
ElectON v2 — Elections forms.
"""
from django import forms
from django.utils import timezone as tz
from django.utils.timezone import is_naive, make_aware

from .models import Election, Post


class ElectionForm(forms.ModelForm):
    """Form for creating and editing elections."""

    class Meta:
        model = Election
        fields = ['name', 'start_time', 'end_time', 'timezone', 'admin_message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter election name',
            }),
            'start_time': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
            'end_time': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
            'timezone': forms.Select(attrs={
                'class': 'form-select',
            }),
            'admin_message': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Enter a custom message for voters (shown on the ballot page)...',
                'rows': 3,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate timezone choices (Country / City format)
        from .services.timezone_service import TimezoneService
        self.fields['timezone'].widget = forms.Select(
            choices=TimezoneService.get_timezone_choices(),
            attrs={'class': 'form-select'},
        )
        # When editing an existing election, pre-fill start/end time fields in
        # the election's own timezone rather than the raw UTC stored value.
        # datetime-local inputs cannot carry timezone info, so showing UTC would
        # confuse the user and cause double-conversion on re-save.
        if self.instance.pk and self.instance.timezone and self.instance.start_time:
            import zoneinfo
            from django.utils.timezone import localtime as _localtime
            try:
                _tz = zoneinfo.ZoneInfo(self.instance.timezone)
                self.initial['start_time'] = _localtime(
                    self.instance.start_time, _tz
                ).strftime('%Y-%m-%dT%H:%M')
                if self.instance.end_time:
                    self.initial['end_time'] = _localtime(
                        self.instance.end_time, _tz
                    ).strftime('%Y-%m-%dT%H:%M')
            except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                pass

    def clean_start_time(self):
        """Strip any auto-applied timezone so clean() can re-apply election_tz.

        Django's forms.DateTimeField with USE_TZ=True silently calls
        from_current_timezone() on every parsed value, wrapping the naive
        datetime-local string in UTC before our clean() ever runs.
        We strip that here so clean() can apply the correct election timezone.
        """
        value = self.cleaned_data.get('start_time')
        if value is not None and not is_naive(value):
            value = value.replace(tzinfo=None)  # strip auto-applied UTC
        return value

    def clean_end_time(self):
        """Same as clean_start_time — strip auto-applied UTC before clean()."""
        value = self.cleaned_data.get('end_time')
        if value is not None and not is_naive(value):
            value = value.replace(tzinfo=None)  # strip auto-applied UTC
        return value

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')

        # Validate and resolve the election timezone
        tz_value = cleaned.get('timezone')
        import zoneinfo
        if tz_value:
            try:
                election_tz = zoneinfo.ZoneInfo(tz_value)
            except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                self.add_error('timezone', 'Invalid timezone.')
                election_tz = zoneinfo.ZoneInfo('UTC')
        else:
            election_tz = zoneinfo.ZoneInfo('UTC')

        # Convert datetimes to UTC using the election's own timezone.
        # clean_start_time / clean_end_time have already stripped any
        # auto-applied UTC offset, so start/end are always naive here.
        # We unconditionally apply make_aware so the election timezone is
        # ALWAYS respected regardless of Django's USE_TZ auto-localisation.
        if start:
            if not is_naive(start):         # belt-and-suspenders safety
                start = start.replace(tzinfo=None)
            start = make_aware(start, election_tz)
            cleaned['start_time'] = start
        if end:
            if not is_naive(end):
                end = end.replace(tzinfo=None)
            end = make_aware(end, election_tz)
            cleaned['end_time'] = end

        # Validate start is not in the past (MED-06)
        if start and start < tz.now():
            if not self.instance.pk or self.instance.start_time != start:
                self.add_error('start_time', 'Start time cannot be in the past.')

        if start and end:
            if end <= start:
                self.add_error('end_time', 'End time must be after start time.')

        return cleaned


class PostForm(forms.ModelForm):
    """Form for adding positions/posts to an election."""

    class Meta:
        model = Post
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Position name (e.g., President)',
            }),
        }
