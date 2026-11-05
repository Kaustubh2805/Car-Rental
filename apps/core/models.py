"""Site-wide business policy settings."""

from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PricingSettings(models.Model):
    """Singleton settings for taxes, booking buffers, and fees."""

    tax_rate_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    booking_buffer_hours = models.PositiveSmallIntegerField(default=2)
    late_fee_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.50"),
        validators=[MinValueValidator(0)],
    )
    late_fee_grace_minutes = models.PositiveSmallIntegerField(default=0)
    cancellation_free_hours = models.PositiveSmallIntegerField(default=24)
    cancellation_fee_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    minimum_driver_age = models.PositiveSmallIntegerField(default=18)

    class Meta:
        verbose_name = "pricing and booking settings"
        verbose_name_plural = "pricing and booking settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "PricingSettings":
        """Return the sole settings row, creating it with defaults if needed."""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

    def __str__(self) -> str:
        return "Pricing and booking policies"


class AuditLog(models.Model):
    """Track important administrative changes and their actor."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=80)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["actor", "-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.action}: {self.object_repr}"
