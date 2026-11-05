"""Forms for filtering the public vehicle catalog."""

from decimal import Decimal

from django import forms

from apps.vehicles.models import Location, Vehicle, VehicleCategory


class VehicleFilterForm(forms.Form):
    """Validate catalog filters before applying them to a queryset."""

    category = forms.ModelChoiceField(
        queryset=VehicleCategory.objects.all(),
        required=False,
        empty_label="All categories",
    )
    transmission = forms.ChoiceField(
        choices=[("", "Any transmission"), *Vehicle.Transmission.choices],
        required=False,
    )
    fuel_type = forms.ChoiceField(
        choices=[("", "Any fuel type"), *Vehicle.FuelType.choices],
        required=False,
    )
    seats = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=20,
        widget=forms.NumberInput(attrs={"min": 1, "max": 20}),
    )
    min_price = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
    )
    max_price = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True),
        required=False,
        empty_label="All locations",
    )
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE),
        required=False,
        empty_label="Any vehicle",
    )
    sort = forms.ChoiceField(
        choices=[
            ("newest", "Newest"),
            ("price_asc", "Price: low to high"),
            ("price_desc", "Price: high to low"),
        ],
        required=False,
        initial="newest",
    )
    pickup_datetime = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"],
        widget=forms.TextInput(
            attrs={
                "class": "form-control flatpickr-datetime",
                "autocomplete": "off",
                "placeholder": "Pickup date and time",
            }
        ),
    )
    return_datetime = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"],
        widget=forms.TextInput(
            attrs={
                "class": "form-control flatpickr-datetime",
                "autocomplete": "off",
                "placeholder": "Return date and time",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        minimum = cleaned_data.get("min_price")
        maximum = cleaned_data.get("max_price")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error("max_price", "Maximum price must be at least minimum price.")
        pickup = cleaned_data.get("pickup_datetime")
        return_at = cleaned_data.get("return_datetime")
        if bool(pickup) != bool(return_at):
            raise forms.ValidationError("Enter both a pickup and return date and time.")
        if pickup and return_at and return_at <= pickup:
            self.add_error("return_datetime", "Return must be after pickup.")
        return cleaned_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-select")
        for name in ("seats", "min_price", "max_price"):
            self.fields[name].widget.attrs["class"] = "form-control"
        self.fields["min_price"].widget.attrs["min"] = "0"
        self.fields["max_price"].widget.attrs["min"] = "0"
