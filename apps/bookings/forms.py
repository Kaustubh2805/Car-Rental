"""Forms for date searches and customer bookings."""

from django import forms

from apps.vehicles.models import Location

DATETIME_INPUT_FORMATS = ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"]


class DateRangeForm(forms.Form):
    """Validate a pickup and return date range."""

    pickup_datetime = forms.DateTimeField(
        input_formats=DATETIME_INPUT_FORMATS,
        widget=forms.TextInput(
            attrs={
                "class": "form-control flatpickr-datetime",
                "autocomplete": "off",
                "placeholder": "Select pickup",
            }
        ),
    )
    return_datetime = forms.DateTimeField(
        input_formats=DATETIME_INPUT_FORMATS,
        widget=forms.TextInput(
            attrs={
                "class": "form-control flatpickr-datetime",
                "autocomplete": "off",
                "placeholder": "Select return",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        pickup = cleaned_data.get("pickup_datetime")
        return_at = cleaned_data.get("return_datetime")
        if pickup and return_at and return_at <= pickup:
            self.add_error("return_datetime", "Return must be after pickup.")
        return cleaned_data


class BookingRequestForm(DateRangeForm):
    """Collect dates, pickup/drop-off locations, and customer notes."""

    pickup_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True),
        empty_label="Choose pickup location",
    )
    return_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True),
        empty_label="Choose return location",
    )
    notes = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("pickup_location", "return_location"):
            self.fields[field].widget.attrs["class"] = "form-select"
