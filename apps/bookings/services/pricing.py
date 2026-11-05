"""Rental quote, late-fee, and cancellation-fee calculations."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from django.utils import timezone

from apps.bookings.models import Reservation
from apps.core.models import PricingSettings
from apps.vehicles.models import Vehicle

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Quote:
    """A fully calculated price quote with the deposit kept separate."""

    rental_days: int
    daily_price: Decimal
    base_amount: Decimal
    tax_amount: Decimal
    extras_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    security_deposit: Decimal
    tax_rate_pct: Decimal

    def as_dict(self) -> dict[str, int | str]:
        """Return a JSON-ready representation of this quote."""
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_quote(
    vehicle: Vehicle,
    pickup: datetime,
    return_at: datetime,
    extras_amount: Decimal = Decimal("0.00"),
) -> Quote:
    """Calculate rental price, weekly discount, tax, extras, and deposit."""
    if pickup.utcoffset() is None or return_at.utcoffset() is None:
        raise ValueError("Pickup and return datetimes must be timezone-aware.")
    if return_at <= pickup:
        raise ValueError("Return must be after pickup.")
    if extras_amount < 0:
        raise ValueError("Extras amount cannot be negative.")

    elapsed_seconds = Decimal(str((return_at - pickup).total_seconds()))
    rental_days = max(1, ceil(elapsed_seconds / Decimal(86400)))
    daily_price = Decimal(vehicle.daily_price)
    base_amount = _money(daily_price * rental_days)
    discount_pct = (
        Decimal(vehicle.weekly_discount_pct) if rental_days >= 7 else Decimal("0")
    )
    discount_amount = _money(base_amount * discount_pct / Decimal(100))
    extras_amount = _money(extras_amount)
    taxable_amount = base_amount - discount_amount + extras_amount
    settings = PricingSettings.get_solo()
    tax_amount = _money(taxable_amount * settings.tax_rate_pct / Decimal(100))
    total_amount = _money(taxable_amount + tax_amount)

    return Quote(
        rental_days=rental_days,
        daily_price=daily_price,
        base_amount=base_amount,
        tax_amount=tax_amount,
        extras_amount=extras_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        security_deposit=_money(Decimal(vehicle.security_deposit)),
        tax_rate_pct=Decimal(settings.tax_rate_pct),
    )


def calculate_late_fee(
    reservation: Reservation,
    actual_return_at: datetime,
) -> Decimal:
    """Charge the configured per-day multiplier for complete late days."""
    if actual_return_at.utcoffset() is None:
        raise ValueError("Actual return datetime must be timezone-aware.")
    settings = PricingSettings.get_solo()
    chargeable_from = reservation.return_datetime + timedelta(
        minutes=settings.late_fee_grace_minutes
    )
    if actual_return_at <= chargeable_from:
        return Decimal("0.00")
    overdue_seconds = Decimal(str((actual_return_at - chargeable_from).total_seconds()))
    overdue_days = max(1, ceil(overdue_seconds / Decimal(86400)))
    amount = (
        Decimal(reservation.daily_price_snapshot)
        * Decimal(settings.late_fee_multiplier)
        * overdue_days
    )
    return _money(amount)


def calculate_cancellation_fee(
    reservation: Reservation,
    cancelled_at: datetime | None = None,
) -> Decimal:
    """Apply the configured percentage inside the free cancellation window."""
    cancelled_at = cancelled_at or timezone.now()
    if cancelled_at.utcoffset() is None:
        raise ValueError("Cancellation datetime must be timezone-aware.")
    settings = PricingSettings.get_solo()
    hours_before_pickup = (
        reservation.pickup_datetime - cancelled_at
    ).total_seconds() / 3600
    if hours_before_pickup > settings.cancellation_free_hours:
        return Decimal("0.00")
    return _money(
        Decimal(reservation.total_amount)
        * Decimal(settings.cancellation_fee_pct)
        / Decimal(100)
    )
