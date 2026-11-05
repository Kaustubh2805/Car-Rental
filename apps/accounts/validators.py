"""Validation helpers for customer identity and password data."""

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_adult(value: date) -> None:
    """Require the configured minimum driver age."""
    today = timezone.localdate()
    age = (
        today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    )
    from apps.core.models import PricingSettings

    minimum_age = PricingSettings.get_solo().minimum_driver_age
    if age < minimum_age:
        raise ValidationError(f"You must be at least {minimum_age} years old.")


def validate_future_date(value: date) -> None:
    """Require a date that falls after the current local date."""
    if value <= timezone.localdate():
        raise ValidationError("The licence expiry date must be in the future.")


def _strong_password_errors(value: str) -> list[str]:
    requirements = (
        (len(value) >= 12, "at least 12 characters"),
        (re.search(r"[a-z]", value), "a lowercase letter"),
        (re.search(r"[A-Z]", value), "an uppercase letter"),
        (re.search(r"\d", value), "a number"),
        (re.search(r"[^A-Za-z0-9]", value), "a symbol"),
    )
    return [description for passed, description in requirements if not passed]


class StrongPasswordValidator:
    """Enforce a minimum length and mixed character categories."""

    def validate(self, password: str, user=None) -> None:
        """Raise a validation error when the password is not sufficiently strong."""
        missing = _strong_password_errors(password)
        if missing:
            raise ValidationError("Password must contain " + ", ".join(missing) + ".")

    def get_help_text(self) -> str:
        """Describe the password requirements to account forms."""
        return (
            "Your password must be at least 12 characters and include "
            "lowercase and uppercase letters, a number, and a symbol."
        )
