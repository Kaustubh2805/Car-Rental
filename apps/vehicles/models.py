"""Vehicle catalog and maintenance models."""

from io import BytesIO
from pathlib import Path

from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import F, Q
from django.utils.text import slugify
from PIL import Image, ImageOps

from apps.vehicles.validators import validate_vehicle_image


class Location(models.Model):
    """A branch or pickup location."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["city", "name"]
        indexes = [models.Index(fields=["is_active", "city"])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.city})"


class VehicleCategory(models.Model):
    """A named class of rental vehicle."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "vehicle categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Feature(models.Model):
    """A feature that can be associated with multiple vehicles."""

    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Vehicle(models.Model):
    """A rentable vehicle and its current catalog information."""

    class Transmission(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        AUTOMATIC = "AUTOMATIC", "Automatic"

    class FuelType(models.TextChoices):
        PETROL = "PETROL", "Petrol"
        DIESEL = "DIESEL", "Diesel"
        HYBRID = "HYBRID", "Hybrid"
        ELECTRIC = "ELECTRIC", "Electric"
        CNG = "CNG", "CNG"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        RETIRED = "RETIRED", "Retired"

    make = models.CharField(max_length=80)
    model = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1886), MaxValueValidator(2100)]
    )
    registration_number = models.CharField(max_length=30, unique=True)
    category = models.ForeignKey(
        VehicleCategory,
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    transmission = models.CharField(
        max_length=12,
        choices=Transmission.choices,
    )
    fuel_type = models.CharField(max_length=10, choices=FuelType.choices)
    seats = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(20)]
    )
    luggage_capacity = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(30)],
    )
    daily_price = models.DecimalField(max_digits=10, decimal_places=2)
    weekly_discount_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    security_deposit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    odometer_km = models.PositiveIntegerField(default=0)
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    features = models.ManyToManyField(Feature, related_name="vehicles", blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "make", "model"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["status", "transmission", "fuel_type"]),
            models.Index(fields=["location", "status"]),
            models.Index(fields=["daily_price"]),
            models.Index(fields=["seats"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(daily_price__gte=0),
                name="vehicle_daily_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(security_deposit__gte=0),
                name="vehicle_deposit_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(seats__gte=1),
                name="vehicle_seats_positive",
            ),
            models.CheckConstraint(
                condition=Q(weekly_discount_pct__gte=0)
                & Q(weekly_discount_pct__lte=100),
                name="vehicle_weekly_discount_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.year} {self.make} {self.model}"


class VehicleImage(models.Model):
    """A validated photo belonging to a vehicle."""

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(
        upload_to="vehicles/",
        validators=[validate_vehicle_image],
    )
    thumbnail = models.ImageField(
        upload_to="vehicles/thumbnails/",
        blank=True,
    )
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "sort_order", "pk"]
        indexes = [models.Index(fields=["vehicle", "is_primary", "sort_order"])]

    def save(self, *args, **kwargs):
        image_changed = self._state.adding
        if self.pk and not image_changed:
            previous_image = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("image", flat=True)
                .first()
            )
            image_changed = previous_image != self.image.name

        super().save(*args, **kwargs)

        if image_changed and self.image:
            with self.image.open("rb") as source:
                with Image.open(source) as original:
                    thumbnail = ImageOps.exif_transpose(original)
                    thumbnail.thumbnail((480, 320), Image.Resampling.LANCZOS)
                    if thumbnail.mode not in ("RGB", "RGBA"):
                        thumbnail = thumbnail.convert("RGB")
                    output = BytesIO()
                    thumbnail.save(output, format="WEBP", quality=82, method=6)

            name = f"{Path(self.image.name).stem}.webp"
            self.thumbnail.save(name, ContentFile(output.getvalue()), save=False)
            super().save(update_fields=["thumbnail"])

    def __str__(self) -> str:
        return f"Image for {self.vehicle}"


class MaintenanceBlock(models.Model):
    """A period when a vehicle must not be rented."""

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="maintenance_blocks",
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_datetime"]
        indexes = [
            models.Index(fields=["vehicle", "start_datetime", "end_datetime"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_datetime__gt=F("start_datetime")),
                name="maintenance_block_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"Maintenance for {self.vehicle} from {self.start_datetime}"
