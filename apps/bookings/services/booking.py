"""Transactional reservation creation and lifecycle operations."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomerProfile, User
from apps.bookings.models import Payment, Reservation
from apps.bookings.services.availability import is_vehicle_available
from apps.bookings.services.notifications import send_reservation_email
from apps.bookings.services.pricing import (
    Quote,
    calculate_cancellation_fee,
    calculate_quote,
)
from apps.vehicles.models import Location, Vehicle

MODIFICATION_CUTOFF_HOURS = 24


def _require_valid_licence(customer: User, return_at: datetime) -> None:
    try:
        profile = customer.customer_profile
    except CustomerProfile.DoesNotExist:
        raise ValidationError("A valid customer driving licence is required.")
    if not profile.licence_expiry:
        raise ValidationError("A valid customer driving licence is required.")
    if profile.licence_expiry < timezone.localtime(return_at).date():
        raise ValidationError("Your driving licence expires before the return date.")


def _validate_customer(customer: User) -> None:
    if customer.role != User.Role.CUSTOMER or not customer.is_active:
        raise ValidationError("Only active customer accounts can make bookings.")


def _validate_locations(
    pickup_location: Location,
    return_location: Location,
) -> None:
    if not pickup_location.is_active or not return_location.is_active:
        raise ValidationError("Select active pickup and return locations.")


def _validate_datetime_period(pickup: datetime, return_at: datetime) -> None:
    if pickup.utcoffset() is None or return_at.utcoffset() is None:
        raise ValidationError("Pickup and return times must include a timezone.")
    if pickup <= timezone.now():
        raise ValidationError("Pickup time must be in the future.")
    if return_at <= pickup:
        raise ValidationError("Return time must be after pickup.")


def _save_quote_snapshot(reservation: Reservation, quote: Quote) -> None:
    reservation.daily_price_snapshot = quote.daily_price
    reservation.rental_days = quote.rental_days
    reservation.base_amount = quote.base_amount
    reservation.tax_amount = quote.tax_amount
    reservation.extras_amount = quote.extras_amount
    reservation.discount_amount = quote.discount_amount
    reservation.total_amount = quote.total_amount
    reservation.security_deposit = quote.security_deposit


def _assign_reference(reservation: Reservation) -> None:
    year = timezone.localdate().year
    reservation.reference = f"CR-{year}-{reservation.pk:06d}"
    reservation.save(update_fields=["reference", "updated_at"])


def _notify_after_commit(reservation: Reservation, event: str) -> None:
    transaction.on_commit(
        lambda: send_reservation_email(
            Reservation.objects.select_related(
                "customer",
                "vehicle",
                "pickup_location",
                "return_location",
            ).get(pk=reservation.pk),
            event,
        )
    )


@transaction.atomic
def create_reservation(
    *,
    customer: User,
    vehicle: Vehicle | int,
    pickup_location: Location | int,
    return_location: Location | int,
    pickup_datetime: datetime,
    return_datetime: datetime,
    notes: str = "",
    extras_amount: Decimal = Decimal("0.00"),
) -> Reservation:
    """Lock a vehicle, recheck availability, and persist a price snapshot."""
    _validate_customer(customer)
    _validate_datetime_period(pickup_datetime, return_datetime)
    locked_vehicle = Vehicle.objects.select_for_update().get(
        pk=vehicle.pk if isinstance(vehicle, Vehicle) else vehicle
    )
    pickup = (
        pickup_location
        if isinstance(pickup_location, Location)
        else Location.objects.get(pk=pickup_location)
    )
    return_location = (
        return_location
        if isinstance(return_location, Location)
        else Location.objects.get(pk=return_location)
    )
    _validate_locations(pickup, return_location)
    _require_valid_licence(customer, return_datetime)
    if not is_vehicle_available(
        locked_vehicle,
        pickup_datetime,
        return_datetime,
    ):
        raise ValidationError("This vehicle is not available for those dates.")

    quote = calculate_quote(
        locked_vehicle,
        pickup_datetime,
        return_datetime,
        extras_amount,
    )
    reservation = Reservation(
        customer=customer,
        vehicle=locked_vehicle,
        pickup_location=pickup,
        return_location=return_location,
        pickup_datetime=pickup_datetime,
        return_datetime=return_datetime,
        notes=notes,
    )
    _save_quote_snapshot(reservation, quote)
    reservation.full_clean(exclude=["reference"])
    reservation.save()
    _assign_reference(reservation)
    _notify_after_commit(reservation, "created")
    return reservation


@transaction.atomic
def modify_reservation(
    *,
    reservation: Reservation | int,
    customer: User,
    pickup_datetime: datetime,
    return_datetime: datetime,
    pickup_location: Location | int | None = None,
    return_location: Location | int | None = None,
    notes: str | None = None,
) -> Reservation:
    """Modify a pending or confirmed booking after rechecking availability."""
    reservation_id = (
        reservation.pk if isinstance(reservation, Reservation) else reservation
    )
    current = Reservation.objects.select_for_update().get(pk=reservation_id)
    if current.customer_id != customer.pk:
        raise ValidationError("You cannot modify another customer's reservation.")
    if current.status not in (
        Reservation.Status.PENDING,
        Reservation.Status.CONFIRMED,
    ):
        raise ValidationError("Only pending or confirmed reservations can be changed.")
    if current.pickup_datetime - timezone.now() <= timedelta(
        hours=MODIFICATION_CUTOFF_HOURS
    ):
        raise ValidationError(
            "Reservations cannot be modified within 24 hours of pickup."
        )
    _validate_datetime_period(pickup_datetime, return_datetime)
    locked_vehicle = Vehicle.objects.select_for_update().get(pk=current.vehicle_id)
    _require_valid_licence(customer, return_datetime)

    pickup = (
        current.pickup_location
        if pickup_location is None
        else (
            pickup_location
            if isinstance(pickup_location, Location)
            else Location.objects.get(pk=pickup_location)
        )
    )
    return_loc = (
        current.return_location
        if return_location is None
        else (
            return_location
            if isinstance(return_location, Location)
            else Location.objects.get(pk=return_location)
        )
    )
    _validate_locations(pickup, return_loc)
    if not is_vehicle_available(
        locked_vehicle,
        pickup_datetime,
        return_datetime,
        exclude_reservation=current,
    ):
        raise ValidationError("This vehicle is not available for those dates.")

    quote = calculate_quote(
        locked_vehicle,
        pickup_datetime,
        return_datetime,
        Decimal(current.extras_amount),
    )
    current.pickup_datetime = pickup_datetime
    current.return_datetime = return_datetime
    current.pickup_location = pickup
    current.return_location = return_loc
    if notes is not None:
        current.notes = notes
    _save_quote_snapshot(current, quote)
    current.full_clean()
    current.save()
    _notify_after_commit(current, "modified")
    return current


@transaction.atomic
def cancel_reservation(
    *,
    reservation: Reservation | int,
    customer: User | None = None,
    cancelled_at: datetime | None = None,
) -> Reservation:
    """Cancel a pending or confirmed booking and calculate its fee."""
    reservation_id = (
        reservation.pk if isinstance(reservation, Reservation) else reservation
    )
    current = Reservation.objects.select_for_update().get(pk=reservation_id)
    if customer is not None and current.customer_id != customer.pk:
        raise ValidationError("You cannot cancel another customer's reservation.")
    if current.status not in (
        Reservation.Status.PENDING,
        Reservation.Status.CONFIRMED,
    ):
        raise ValidationError(
            "Only pending or confirmed reservations can be cancelled."
        )
    cancellation_time = cancelled_at or timezone.now()
    if current.actual_pickup_at or cancellation_time >= current.pickup_datetime:
        raise ValidationError("A reservation cannot be cancelled after pickup time.")
    current.cancellation_fee = calculate_cancellation_fee(
        current,
        cancellation_time,
    )
    current.status = Reservation.Status.CANCELLED
    current.save(update_fields=["cancellation_fee", "status", "updated_at"])
    _notify_after_commit(current, "cancelled")
    return current


@transaction.atomic
def create_payment(
    reservation: Reservation | int,
    method: str,
) -> Payment:
    """Record a mock-card or pay-at-pickup selection for the reservation."""
    reservation_id = (
        reservation.pk if isinstance(reservation, Reservation) else reservation
    )
    current = Reservation.objects.select_for_update().get(pk=reservation_id)
    if method not in Payment.Method.values:
        raise ValidationError("Select a supported payment method.")
    if current.status not in (
        Reservation.Status.PENDING,
        Reservation.Status.CONFIRMED,
    ):
        raise ValidationError("This reservation cannot accept payment.")
    paid = method in (Payment.Method.CARD_MOCK, Payment.Method.CASH)
    payment = Payment.objects.create(
        reservation=current,
        amount=current.total_amount,
        method=method,
        status=Payment.Status.PAID if paid else Payment.Status.PENDING,
        transaction_ref=(
            f"MOCK-{current.reference}" if method == Payment.Method.CARD_MOCK else ""
        ),
        paid_at=timezone.now() if paid else None,
    )
    if paid:
        current.status = Reservation.Status.CONFIRMED
        current.save(update_fields=["status", "updated_at"])
    return payment
