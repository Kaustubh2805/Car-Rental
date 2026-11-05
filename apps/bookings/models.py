"""Reservation and payment records."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.vehicles.models import Location, Vehicle


class Reservation(models.Model):
    """A customer's rental request and its immutable price snapshot."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class FuelLevel(models.IntegerChoices):
        EMPTY = 0, "Empty"
        QUARTER = 25, "Quarter"
        HALF = 50, "Half"
        THREE_QUARTERS = 75, "Three quarters"
        FULL = 100, "Full"

    reference = models.CharField(max_length=20, unique=True, null=True, blank=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    pickup_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="pickup_reservations",
    )
    return_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="return_reservations",
    )
    pickup_datetime = models.DateTimeField()
    return_datetime = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    daily_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    rental_days = models.PositiveSmallIntegerField()
    base_amount = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    extras_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2)
    late_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    cancellation_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    actual_pickup_at = models.DateTimeField(null=True, blank=True)
    actual_return_at = models.DateTimeField(null=True, blank=True)
    pickup_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    return_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    pickup_odometer = models.PositiveIntegerField(null=True, blank=True)
    return_odometer = models.PositiveIntegerField(null=True, blank=True)
    fuel_level_out = models.PositiveSmallIntegerField(
        choices=FuelLevel.choices,
        null=True,
        blank=True,
    )
    fuel_level_in = models.PositiveSmallIntegerField(
        choices=FuelLevel.choices,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    damage_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=[
                    "vehicle",
                    "pickup_datetime",
                    "return_datetime",
                    "status",
                ],
                name="book_vehicle_dates_status_idx",
            ),
            models.Index(fields=["customer", "status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(return_datetime__gt=F("pickup_datetime")),
                name="reservation_return_after_pickup",
            ),
            models.CheckConstraint(
                condition=Q(fuel_level_out__isnull=True)
                | Q(fuel_level_out__gte=0, fuel_level_out__lte=100),
                name="reservation_fuel_out_range",
            ),
            models.CheckConstraint(
                condition=Q(fuel_level_in__isnull=True)
                | Q(fuel_level_in__gte=0, fuel_level_in__lte=100),
                name="reservation_fuel_in_range",
            ),
        ]

    def __str__(self) -> str:
        return self.reference or f"Reservation {self.pk or 'unsaved'}"


class Payment(models.Model):
    """A payment attempt or pay-at-pickup instruction for a reservation."""

    class Method(models.TextChoices):
        CARD_MOCK = "CARD_MOCK", "Mock card"
        CASH = "CASH", "Cash"
        PAY_AT_PICKUP = "PAY_AT_PICKUP", "Pay at pickup"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    transaction_ref = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["reservation", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payment_amount_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reservation} payment ({self.get_status_display()})"
