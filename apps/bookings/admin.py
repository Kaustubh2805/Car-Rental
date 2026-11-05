"""Django admin configuration for reservations and payments."""

from django.contrib import admin

from apps.bookings.models import Payment, Reservation


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "customer",
        "vehicle",
        "pickup_datetime",
        "return_datetime",
        "status",
        "total_amount",
    )
    list_filter = ("status", "pickup_datetime", "vehicle__category")
    search_fields = (
        "reference",
        "customer__email",
        "vehicle__make",
        "vehicle__model",
        "vehicle__registration_number",
    )
    autocomplete_fields = (
        "customer",
        "vehicle",
        "pickup_location",
        "return_location",
    )
    readonly_fields = (
        "reference",
        "daily_price_snapshot",
        "rental_days",
        "base_amount",
        "tax_amount",
        "extras_amount",
        "discount_amount",
        "total_amount",
        "security_deposit",
        "created_at",
        "updated_at",
    )
    inlines = [PaymentInline]
    date_hierarchy = "pickup_datetime"
    list_select_related = ("customer", "vehicle", "pickup_location", "return_location")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reservation",
        "amount",
        "method",
        "status",
        "transaction_ref",
        "paid_at",
    )
    list_filter = ("method", "status", "paid_at")
    search_fields = ("reservation__reference", "transaction_ref")
    autocomplete_fields = ("reservation",)
