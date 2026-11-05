"""Forms used by staff and administrators in the operations dashboard."""

from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import User
from apps.bookings.models import Reservation
from apps.core.models import PricingSettings
from apps.vehicles.models import (
    MaintenanceBlock,
    Vehicle,
)


class VehicleForm(forms.ModelForm):
    """Edit a vehicle and its catalog features."""

    class Meta:
        model = Vehicle
        fields = (
            "make",
            "model",
            "year",
            "registration_number",
            "category",
            "transmission",
            "fuel_type",
            "seats",
            "luggage_capacity",
            "daily_price",
            "weekly_discount_pct",
            "security_deposit",
            "odometer_km",
            "location",
            "status",
            "features",
            "description",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "features": forms.CheckboxSelectMultiple(),
        }


class VehicleStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Vehicle.Status.choices)

    def __init__(self, *args, admin_user=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not admin_user:
            self.fields["status"].choices = (
                (Vehicle.Status.AVAILABLE, Vehicle.Status.AVAILABLE.label),
                (Vehicle.Status.MAINTENANCE, Vehicle.Status.MAINTENANCE.label),
            )


class MaintenanceBlockForm(forms.ModelForm):
    start_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )
    end_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    class Meta:
        model = MaintenanceBlock
        fields = ("vehicle", "start_datetime", "end_datetime", "reason")


class ReservationFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", "All statuses"), *Reservation.Status.choices],
        required=False,
    )
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.all(),
        required=False,
        empty_label="All vehicles",
    )
    customer = forms.CharField(required=False, max_length=254)
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after start date.")
        return cleaned


class PickupForm(forms.Form):
    odometer_km = forms.IntegerField(min_value=0)
    fuel_level = forms.TypedChoiceField(
        choices=Reservation.FuelLevel.choices,
        coerce=int,
    )


class ReturnForm(PickupForm):
    damage_notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class CustomerSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=254, label="Search customers")


class PricingSettingsForm(forms.ModelForm):
    class Meta:
        model = PricingSettings
        fields = (
            "tax_rate_pct",
            "booking_buffer_hours",
            "cancellation_free_hours",
            "cancellation_fee_pct",
            "late_fee_multiplier",
            "late_fee_grace_minutes",
            "minimum_driver_age",
        )
        widgets = {
            "tax_rate_pct": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "0.01"}
            ),
            "booking_buffer_hours": forms.NumberInput(attrs={"min": "0"}),
            "cancellation_free_hours": forms.NumberInput(attrs={"min": "0"}),
            "cancellation_fee_pct": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "0.01"}
            ),
            "late_fee_multiplier": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "late_fee_grace_minutes": forms.NumberInput(attrs={"min": "0"}),
            "minimum_driver_age": forms.NumberInput(attrs={"min": "18", "max": "100"}),
        }

    def clean_minimum_driver_age(self):
        age = self.cleaned_data["minimum_driver_age"]
        if age < 18 or age > 100:
            raise forms.ValidationError(
                "Minimum driver age must be between 18 and 100."
            )
        return age


class ReportsDateRangeForm(forms.Form):
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after start date.")
        return cleaned


class StaffCreateForm(forms.ModelForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone")

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            validate_password(password1, self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STAFF
        user.is_staff = True
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
