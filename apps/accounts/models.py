"""Account and customer profile models."""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone

from apps.accounts.validators import validate_adult, validate_future_date


class UserManager(BaseUserManager):
    """Create users using their email address as the login identifier."""

    use_in_migrations = True

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> User:
        """Create and return a regular user."""
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(
            email=self.normalize_email(email).casefold(),
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> User:
        """Create and return a user with administrative permissions."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_active", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        if extra_fields["role"] != User.Role.ADMIN:
            raise ValueError("A superuser must have the admin role.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Application user authenticated with a unique email address."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF = "staff", "Staff"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True, default="")
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "phone"]

    def clean(self) -> None:
        """Normalize email addresses before form and model validation."""
        super().clean()
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email).casefold()

    def __str__(self) -> str:
        return self.email


class CustomerProfile(models.Model):
    """Personal and driving-licence details for a customer."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    address = models.TextField(blank=True, validators=[MaxLengthValidator(500)])
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        validators=[validate_adult],
    )
    licence_number = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    licence_expiry = models.DateField(
        null=True,
        blank=True,
        validators=[validate_future_date],
    )
    id_proof = models.ImageField(
        upload_to="customer_id_proofs/",
        blank=True,
    )

    def clean(self) -> None:
        """Validate completed customer identity details."""
        super().clean()
        errors: dict[str, str] = {}
        if self.date_of_birth:
            try:
                validate_adult(self.date_of_birth)
            except ValidationError as error:
                errors["date_of_birth"] = error.messages[0]
        if self.licence_expiry:
            try:
                validate_future_date(self.licence_expiry)
            except ValidationError as error:
                errors["licence_expiry"] = error.messages[0]
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"Profile for {self.user.email}"


class LoginAttempt(models.Model):
    """Record failed authentication attempts for a time-windowed lockout."""

    email = models.EmailField(max_length=254)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["email", "created_at"],
                name="account_login_attempt_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Failed login for {self.email} at {self.created_at}"
