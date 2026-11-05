"""Django admin configuration for vehicle catalog models."""

from django.contrib import admin

from apps.vehicles.models import (
    Feature,
    Location,
    MaintenanceBlock,
    Vehicle,
    VehicleCategory,
    VehicleImage,
)


class VehicleImageInline(admin.TabularInline):
    model = VehicleImage
    extra = 1
    fields = ("image", "is_primary", "sort_order")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "make",
        "model",
        "year",
        "registration_number",
        "category",
        "daily_price",
        "location",
        "status",
    )
    list_filter = (
        "status",
        "category",
        "transmission",
        "fuel_type",
        "location",
    )
    search_fields = ("make", "model", "registration_number")
    autocomplete_fields = ("category", "location", "features")
    filter_horizontal = ("features",)
    inlines = [VehicleImageInline]
    list_select_related = ("category", "location")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "postal_code", "is_active")
    list_filter = ("is_active", "state", "city")
    search_fields = ("name", "city", "state")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(VehicleCategory)
class VehicleCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(VehicleImage)
class VehicleImageAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "is_primary", "sort_order", "created_at")
    list_filter = ("is_primary",)
    search_fields = ("vehicle__make", "vehicle__model", "vehicle__registration_number")
    autocomplete_fields = ("vehicle",)


@admin.register(MaintenanceBlock)
class MaintenanceBlockAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "start_datetime", "end_datetime", "reason")
    list_filter = ("start_datetime", "end_datetime")
    search_fields = ("vehicle__make", "vehicle__model", "reason")
    autocomplete_fields = ("vehicle",)
