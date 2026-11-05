"""Staff reservation lifecycle operations with validated status transitions."""

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Reservation
from apps.bookings.services.pricing import calculate_late_fee
from apps.core.audit import record_audit


@transaction.atomic
def confirm_reservation(*, reservation: Reservation | int, actor: User) -> Reservation:
    """Confirm a pending reservation."""
    current = _lock_reservation(reservation)
    _require_status(current, Reservation.Status.PENDING, "confirmed")
    old_status = current.status
    current.status = Reservation.Status.CONFIRMED
    current.save(update_fields=["status", "updated_at"])
    _audit_status(actor, current, old_status)
    return current


@transaction.atomic
def pick_up_reservation(
    *,
    reservation: Reservation | int,
    actor: User,
    odometer_km: int,
    fuel_level: int,
    picked_up_at: datetime | None = None,
) -> Reservation:
    """Mark a confirmed vehicle as picked up and capture its condition."""
    current = _lock_reservation(reservation)
    _require_status(current, Reservation.Status.CONFIRMED, "picked up")
    if odometer_km < current.vehicle.odometer_km:
        raise ValidationError("Pickup odometer cannot be below the vehicle odometer.")
    _validate_fuel_level(fuel_level)

    old_status = current.status
    current.status = Reservation.Status.ACTIVE
    current.actual_pickup_at = picked_up_at or timezone.now()
    current.pickup_odometer = odometer_km
    current.fuel_level_out = fuel_level
    current.full_clean()
    current.save(
        update_fields=[
            "status",
            "actual_pickup_at",
            "pickup_odometer",
            "fuel_level_out",
            "updated_at",
        ]
    )
    current.vehicle.odometer_km = odometer_km
    current.vehicle.save(update_fields=["odometer_km", "updated_at"])
    _audit_status(actor, current, old_status)
    return current


@transaction.atomic
def return_reservation(
    *,
    reservation: Reservation | int,
    actor: User,
    odometer_km: int,
    fuel_level: int,
    damage_notes: str = "",
    returned_at: datetime | None = None,
) -> Reservation:
    """Complete an active rental, recording condition and any late fee."""
    current = _lock_reservation(reservation)
    _require_status(current, Reservation.Status.ACTIVE, "returned")
    if current.pickup_odometer is not None and odometer_km < current.pickup_odometer:
        raise ValidationError("Return odometer cannot be below pickup odometer.")
    _validate_fuel_level(fuel_level)
    actual_return = returned_at or timezone.now()
    if actual_return.utcoffset() is None:
        raise ValidationError("Return time must be timezone-aware.")

    old_status = current.status
    current.status = Reservation.Status.COMPLETED
    current.actual_return_at = actual_return
    current.return_odometer = odometer_km
    current.fuel_level_in = fuel_level
    current.damage_notes = damage_notes
    current.late_fee = calculate_late_fee(current, actual_return)
    current.full_clean()
    current.save(
        update_fields=[
            "status",
            "actual_return_at",
            "return_odometer",
            "fuel_level_in",
            "damage_notes",
            "late_fee",
            "updated_at",
        ]
    )
    current.vehicle.odometer_km = max(current.vehicle.odometer_km, odometer_km)
    current.vehicle.save(update_fields=["odometer_km", "updated_at"])
    _audit_status(actor, current, old_status)
    return current


@transaction.atomic
def staff_cancel_reservation(
    *,
    reservation: Reservation | int,
    actor: User,
) -> Reservation:
    """Cancel a pending or confirmed reservation before its scheduled pickup."""
    current = _lock_reservation(reservation)
    if current.status not in (
        Reservation.Status.PENDING,
        Reservation.Status.CONFIRMED,
    ):
        raise ValidationError(
            "Only pending or confirmed reservations can be cancelled."
        )
    if current.actual_pickup_at or timezone.now() >= current.pickup_datetime:
        raise ValidationError("A reservation cannot be cancelled after pickup.")

    old_status = current.status
    from apps.bookings.services.pricing import calculate_cancellation_fee

    current.cancellation_fee = calculate_cancellation_fee(current)
    current.status = Reservation.Status.CANCELLED
    current.save(update_fields=["cancellation_fee", "status", "updated_at"])
    _audit_status(actor, current, old_status)
    return current


def _lock_reservation(reservation: Reservation | int) -> Reservation:
    reservation_id = (
        reservation.pk if isinstance(reservation, Reservation) else reservation
    )
    return (
        Reservation.objects.select_for_update()
        .select_related("vehicle")
        .get(pk=reservation_id)
    )


def _require_status(
    reservation: Reservation,
    expected: str,
    action: str,
) -> None:
    if reservation.status != expected:
        raise ValidationError(
            "Only "
            f"{Reservation.Status(expected).label.lower()} reservations "
            f"can be {action}."
        )


def _validate_fuel_level(fuel_level: int) -> None:
    if fuel_level not in Reservation.FuelLevel.values:
        raise ValidationError("Select a valid fuel level.")


def _audit_status(actor: User, reservation: Reservation, old_status: str) -> None:
    record_audit(
        actor=actor,
        action="reservation.status_changed",
        obj=reservation,
        changes={"status": {"from": old_status, "to": reservation.status}},
    )
