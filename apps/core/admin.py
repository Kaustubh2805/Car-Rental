"""Admin configuration for core business settings."""

from django.contrib import admin

from apps.core.models import AuditLog, PricingSettings


@admin.register(PricingSettings)
class PricingSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "tax_rate_pct",
        "booking_buffer_hours",
        "late_fee_multiplier",
        "late_fee_grace_minutes",
        "cancellation_free_hours",
        "cancellation_fee_pct",
        "minimum_driver_age",
    )

    def has_add_permission(self, request):
        return not PricingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "object_repr")
    list_filter = ("action", "timestamp")
    search_fields = ("actor__email", "object_repr", "object_id")
    readonly_fields = (
        "actor",
        "action",
        "content_type",
        "object_id",
        "object_repr",
        "changes",
        "timestamp",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
