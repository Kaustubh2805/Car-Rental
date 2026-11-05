"""Vehicle availability checks and date-range catalog searches."""

from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef, QuerySet

from apps.bookings.models import Reservation
from apps.core.models import PricingSettings
from apps.vehicles.models import MaintenanceBlock, Vehicle

BLOCKING_STATUSES = (
    Reservation.Status.PENDING,
    Reservation.Status.CONFIRMED,
    Reservation.Status.ACTIVE,
)


def _validate_period(pickup: datetime, return_at: datetime) -> None:
    if pickup.utcoffset() is None or return_at.utcoffset() is None:
        raise ValueError("Pickup and return datetimes must be timezone-aware.")
    if return_at <= pickup:
        raise ValueError("Return must be after pickup.")


def _buffered_period(
    pickup: datetime,
    return_at: datetime,
) -> tuple[datetime, datetime]:
    buffer = timedelta(hours=PricingSettings.get_solo().booking_buffer_hours)
    return pickup - buffer, return_at + buffer


def is_vehicle_available(
    vehicle: Vehicle | int,
    pickup: datetime,
    return_at: datetime,
    exclude_reservation: Reservation | int | None = None,
) -> bool:
    """Check vehicle status, reservations, maintenance, and the gap buffer.

    The buffer is applied once between adjacent bookings: either an existing
    pickup may not fall before this rental's buffered return, or an existing
    return may not fall after this rental's buffered pickup.
    """
    _validate_period(pickup, return_at)
    vehicle_id = vehicle.pk if isinstance(vehicle, Vehicle) else vehicle
    if not Vehicle.objects.filter(
        pk=vehicle_id,
        status=Vehicle.Status.AVAILABLE,
    ).exists():
        return False

    buffered_pickup, buffered_return = _buffered_period(pickup, return_at)
    reservations = Reservation.objects.filter(
        vehicle_id=vehicle_id,
        status__in=BLOCKING_STATUSES,
        pickup_datetime__lt=buffered_return,
        return_datetime__gt=buffered_pickup,
    )
    if exclude_reservation is not None:
        reservation_id = (
            exclude_reservation.pk
            if isinstance(exclude_reservation, Reservation)
            else exclude_reservation
        )
        reservations = reservations.exclude(pk=reservation_id)
    if reservations.exists():
        return False

    return not MaintenanceBlock.objects.filter(
        vehicle_id=vehicle_id,
        start_datetime__lt=buffered_return,
        end_datetime__gt=buffered_pickup,
    ).exists()


def search_available_vehicles(
    pickup: datetime,
    return_at: datetime,
    queryset: QuerySet[Vehicle] | None = None,
) -> QuerySet[Vehicle]:
    """Return vehicles free of blocking reservations and maintenance."""
    _validate_period(pickup, return_at)
    if queryset is None:
        queryset = Vehicle.objects.all()
    buffered_pickup, buffered_return = _buffered_period(pickup, return_at)

    overlapping_reservations = Reservation.objects.filter(
        vehicle_id=OuterRef("pk"),
        status__in=BLOCKING_STATUSES,
        pickup_datetime__lt=buffered_return,
        return_datetime__gt=buffered_pickup,
    )
    overlapping_maintenance = MaintenanceBlock.objects.filter(
        vehicle_id=OuterRef("pk"),
        start_datetime__lt=buffered_return,
        end_datetime__gt=buffered_pickup,
    )
    return (
        queryset.filter(status=Vehicle.Status.AVAILABLE)
        .annotate(
            has_overlapping_reservation=Exists(overlapping_reservations),
            has_overlapping_maintenance=Exists(overlapping_maintenance),
        )
        .filter(
            has_overlapping_reservation=False,
            has_overlapping_maintenance=False,
        )
    )
