"""Forms for account registration, authentication, and profile management."""

from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomerProfile, LoginAttempt
from apps.accounts.validators import validate_adult, validate_future_date

User = get_user_model()


class RegistrationForm(UserCreationForm):
    """Create a customer account and collect required licence details."""

    phone = forms.CharField(max_length=30)
    date_of_birth = forms.DateField(
        validators=[validate_adult],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    licence_number = forms.CharField(max_length=100)
    licence_expiry = forms.DateField(
        validators=[validate_future_date],
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone",
            "date_of_birth",
            "licence_number",
            "licence_expiry",
        )

    def clean_licence_number(self):
        licence_number = self.cleaned_data["licence_number"]
        if CustomerProfile.objects.filter(licence_number=licence_number).exists():
            raise ValidationError("This licence number is already registered.")
        return licence_number

    @transaction.atomic
    def save(self, commit: bool = True):
        """Create a customer and save the validated profile fields."""
        user = super().save(commit=False)
        user.role = User.Role.CUSTOMER
        if commit:
            user.save()
            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            profile.date_of_birth = self.cleaned_data["date_of_birth"]
            profile.licence_number = self.cleaned_data["licence_number"]
            profile.licence_expiry = self.cleaned_data["licence_expiry"]
            profile.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    """Authenticate by email and lock an account/IP after five failures."""

    failure_limit = 5
    failure_window = timedelta(minutes=15)

    def clean_username(self):
        return self.cleaned_data["username"].strip().casefold()

    @property
    def normalized_email(self) -> str:
        """Return the submitted email in the format used for throttling."""
        value = self.cleaned_data.get(
            User.USERNAME_FIELD,
            self.cleaned_data.get("username", ""),
        )
        return str(value).strip().casefold()

    def _client_ip(self) -> str | None:
        if self.request is None:
            return None
        return self.request.META.get("REMOTE_ADDR") or None

    def clean(self):
        email = self.normalized_email
        if email:
            recent_attempts = LoginAttempt.objects.filter(
                email=email,
                created_at__gte=timezone.now() - self.failure_window,
            ).count()
            if recent_attempts >= self.failure_limit:
                raise ValidationError(
                    "Too many failed sign-in attempts. Try again in 15 minutes."
                )

        try:
            return super().clean()
        except ValidationError:
            if email:
                LoginAttempt.objects.create(
                    email=email,
                    ip_address=self._client_ip(),
                )
            raise


class ProfileForm(forms.ModelForm):
    """Update a customer's contact information and rental profile."""

    phone = forms.CharField(max_length=30)
    address = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    date_of_birth = forms.DateField(
        validators=[validate_adult],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    licence_number = forms.CharField(max_length=100)
    licence_expiry = forms.DateField(
        validators=[validate_future_date],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    id_proof = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone")

    def clean_licence_number(self):
        licence_number = self.cleaned_data["licence_number"]
        profiles = CustomerProfile.objects.filter(
            licence_number=licence_number
        ).exclude(user=self.instance)
        if profiles.exists():
            raise ValidationError("This licence number is already registered.")
        return licence_number

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, "customer_profile", None)
        if profile is not None:
            for field in (
                "address",
                "city",
                "state",
                "postal_code",
                "date_of_birth",
                "licence_number",
                "licence_expiry",
                "id_proof",
            ):
                self.fields[field].initial = getattr(profile, field)

    @transaction.atomic
    def save(self, commit: bool = True):
        """Save user and profile information together."""
        user = super().save(commit=commit)
        if commit:
            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            for field in (
                "address",
                "city",
                "state",
                "postal_code",
                "date_of_birth",
                "licence_number",
                "licence_expiry",
            ):
                setattr(profile, field, self.cleaned_data[field])
            if self.cleaned_data.get("id_proof"):
                profile.id_proof = self.cleaned_data["id_proof"]
            profile.save()
        return user
