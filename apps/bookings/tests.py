"""Tests for booking overlap, pricing, and reservation services."""

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from queue import Queue
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import (
    Client,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomerProfile
from apps.bookings.models import Payment, Reservation
from apps.bookings.services.availability import (
    is_vehicle_available,
    search_available_vehicles,
)
from apps.bookings.services.booking import (
    cancel_reservation,
    create_payment,
    create_reservation,
    modify_reservation,
)
from apps.bookings.services.pricing import (
    calculate_cancellation_fee,
    calculate_late_fee,
    calculate_quote,
)
from apps.core.models import PricingSettings
from apps.vehicles.models import Location, MaintenanceBlock, Vehicle, VehicleCategory

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BookingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.location = Location.objects.create(
            name="Booking Central",
            city="Pune",
            state="Maharashtra",
        )
        cls.category = VehicleCategory.objects.create(name="Booking Sedan")
        cls.vehicle = Vehicle.objects.create(
            make="Booking",
            model="Test",
            year=2025,
            registration_number="BOOK-0001",
            category=cls.category,
            transmission=Vehicle.Transmission.AUTOMATIC,
            fuel_type=Vehicle.FuelType.PETROL,
            seats=5,
            luggage_capacity=3,
            daily_price=Decimal("1000.00"),
            weekly_discount_pct=Decimal("10.00"),
            security_deposit=Decimal("5000.00"),
            odometer_km=1000,
            location=cls.location,
            status=Vehicle.Status.AVAILABLE,
        )
        cls.customer = User.objects.create_user(
            email="booking-customer@example.com",
            password="Vast!RoadTrip8427",
            first_name="Booking",
            last_name="Customer",
            phone="5550100",
        )
        cls.profile = cls.customer.customer_profile
        cls.profile.licence_number = "BOOKING-LICENCE-1"
        cls.profile.licence_expiry = timezone.localdate() + timedelta(days=3650)
        cls.profile.date_of_birth = timezone.localdate() - timedelta(days=30 * 365)
        cls.profile.save()

    def setUp(self):
        self.settings = PricingSettings.get_solo()
        self.settings.tax_rate_pct = Decimal("10.00")
        self.settings.booking_buffer_hours = 2
        self.settings.late_fee_multiplier = Decimal("1.50")
        self.settings.cancellation_free_hours = 24
        self.settings.cancellation_fee_pct = Decimal("20.00")
        self.settings.save()
        self.pickup = timezone.now() + timedelta(days=10)
        self.pickup = self.pickup.replace(second=0, microsecond=0)
        self.return_at = self.pickup + timedelta(days=2)

    def make_reservation(self, pickup=None, return_at=None, **kwargs):
        return create_reservation(
            customer=self.customer,
            vehicle=self.vehicle,
            pickup_location=self.location,
            return_location=self.location,
            pickup_datetime=pickup or self.pickup,
            return_datetime=return_at or self.return_at,
            **kwargs,
        )

    def test_overlap_start_end_inside_and_enclosing(self):
        settings = PricingSettings.get_solo()
        settings.booking_buffer_hours = 0
        settings.save()
        existing_start = self.pickup + timedelta(days=2)
        existing_end = existing_start + timedelta(hours=4)
        self.make_reservation(existing_start, existing_end)

        candidates = [
            (existing_start - timedelta(hours=1), existing_start + timedelta(hours=1)),
            (existing_start + timedelta(hours=1), existing_end + timedelta(hours=1)),
            (existing_start - timedelta(hours=1), existing_end + timedelta(hours=1)),
            (existing_start, existing_end),
        ]
        for pickup, return_at in candidates:
            with self.subTest(pickup=pickup, return_at=return_at):
                self.assertFalse(is_vehicle_available(self.vehicle, pickup, return_at))

    def test_exact_boundaries_and_back_to_back_buffer(self):
        settings = PricingSettings.get_solo()
        settings.booking_buffer_hours = 0
        settings.save()
        existing_start = self.pickup + timedelta(days=2)
        existing_end = existing_start + timedelta(hours=4)
        self.make_reservation(existing_start, existing_end)

        self.assertTrue(
            is_vehicle_available(
                self.vehicle,
                existing_start - timedelta(hours=2),
                existing_start,
            )
        )
        self.assertTrue(
            is_vehicle_available(
                self.vehicle,
                existing_end,
                existing_end + timedelta(hours=2),
            )
        )

        settings.booking_buffer_hours = 2
        settings.save()
        self.assertFalse(
            is_vehicle_available(
                self.vehicle,
                existing_end + timedelta(minutes=1),
                existing_end + timedelta(hours=2),
            )
        )
        self.assertTrue(
            is_vehicle_available(
                self.vehicle,
                existing_end + timedelta(hours=2),
                existing_end + timedelta(hours=4),
            )
        )

    def test_search_excludes_overlapping_reservations_and_maintenance(self):
        self.make_reservation()
        self.assertNotIn(
            self.vehicle.pk,
            search_available_vehicles(
                self.pickup,
                self.return_at,
            ).values_list("pk", flat=True),
        )

        reservation = Reservation.objects.get(vehicle=self.vehicle)
        reservation.status = Reservation.Status.CANCELLED
        reservation.save(update_fields=["status"])
        MaintenanceBlock.objects.create(
            vehicle=self.vehicle,
            start_datetime=self.pickup - timedelta(hours=1),
            end_datetime=self.return_at + timedelta(hours=1),
        )
        self.assertFalse(
            is_vehicle_available(self.vehicle, self.pickup, self.return_at)
        )

    def test_non_available_vehicle_and_non_blocking_statuses(self):
        self.vehicle.status = Vehicle.Status.MAINTENANCE
        self.vehicle.save(update_fields=["status"])
        self.assertFalse(
            is_vehicle_available(self.vehicle, self.pickup, self.return_at)
        )

    def test_period_must_be_aware_and_return_after_pickup(self):
        with self.assertRaises(ValueError):
            is_vehicle_available(
                self.vehicle,
                datetime(2030, 1, 1, 10),
                datetime(2030, 1, 2, 10),
            )
        with self.assertRaises(ValueError):
            is_vehicle_available(
                self.vehicle,
                self.pickup,
                self.pickup,
            )

    def test_quote_ceil_minimum_weekly_discount_tax_and_deposit(self):
        one_day = calculate_quote(
            self.vehicle,
            self.pickup,
            self.pickup + timedelta(minutes=1),
        )
        self.assertEqual(one_day.rental_days, 1)
        self.assertEqual(one_day.base_amount, Decimal("1000.00"))
        self.assertEqual(one_day.tax_amount, Decimal("100.00"))
        self.assertEqual(one_day.total_amount, Decimal("1100.00"))
        self.assertEqual(one_day.security_deposit, Decimal("5000.00"))

        weekly = calculate_quote(
            self.vehicle,
            self.pickup,
            self.pickup + timedelta(days=7),
        )
        self.assertEqual(weekly.rental_days, 7)
        self.assertEqual(weekly.discount_amount, Decimal("700.00"))
        self.assertEqual(weekly.tax_amount, Decimal("630.00"))
        self.assertEqual(weekly.total_amount, Decimal("6930.00"))

    def test_late_fee_rounds_partial_late_day_up(self):
        reservation = self.make_reservation()
        fee = calculate_late_fee(
            reservation,
            reservation.return_datetime + timedelta(minutes=1),
        )
        self.assertEqual(fee, Decimal("1500.00"))

    def test_cancellation_fee_free_beyond_24_hours_and_charged_within(self):
        reservation = self.make_reservation()

        self.assertEqual(
            calculate_cancellation_fee(
                reservation,
                reservation.pickup_datetime - timedelta(hours=24, seconds=1),
            ),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculate_cancellation_fee(
                reservation,
                reservation.pickup_datetime - timedelta(hours=24),
            ),
            Decimal("440.00"),
        )
        self.assertEqual(
            calculate_cancellation_fee(
                reservation,
                reservation.pickup_datetime - timedelta(hours=1),
            ),
            Decimal("440.00"),
        )

    def test_create_reservation_snapshots_price_and_emails(self):
        with self.captureOnCommitCallbacks(execute=True):
            reservation = self.make_reservation()

        self.assertEqual(
            reservation.reference,
            f"CR-{timezone.localdate().year}-{reservation.pk:06d}",
        )
        self.assertEqual(reservation.daily_price_snapshot, Decimal("1000.00"))
        self.assertEqual(reservation.rental_days, 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(reservation.reference, mail.outbox[0].subject)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)

        self.vehicle.daily_price = Decimal("9000.00")
        self.vehicle.save(update_fields=["daily_price"])
        reservation.refresh_from_db()
        self.assertEqual(reservation.daily_price_snapshot, Decimal("1000.00"))
        self.assertEqual(reservation.total_amount, Decimal("2200.00"))

    def test_booking_rejects_expired_licence(self):
        self.profile.licence_expiry = timezone.localdate() + timedelta(days=1)
        self.profile.save(update_fields=["licence_expiry"])
        with self.assertRaisesMessage(
            ValidationError, "expires before the return date"
        ):
            self.make_reservation()

    def test_modify_rechecks_availability_updates_snapshot_and_emails(self):
        changed_pickup = self.pickup + timedelta(days=4)
        changed_return = changed_pickup + timedelta(days=3)
        self.vehicle.daily_price = Decimal("2000.00")
        self.vehicle.save(update_fields=["daily_price"])

        with self.captureOnCommitCallbacks(execute=True):
            reservation = self.make_reservation()
            modified = modify_reservation(
                reservation=reservation,
                customer=self.customer,
                pickup_datetime=changed_pickup,
                return_datetime=changed_return,
            )

        self.assertEqual(modified.daily_price_snapshot, Decimal("2000.00"))
        self.assertEqual(modified.rental_days, 3)
        self.assertEqual(len(mail.outbox), 2)

    def test_modify_is_rejected_within_24_hours_of_pickup(self):
        pickup = timezone.now() + timedelta(hours=12)
        reservation = self.make_reservation(
            pickup=pickup,
            return_at=pickup + timedelta(days=1),
        )

        with self.assertRaisesMessage(ValidationError, "within 24 hours"):
            modify_reservation(
                reservation=reservation,
                customer=self.customer,
                pickup_datetime=pickup + timedelta(hours=1),
                return_datetime=pickup + timedelta(days=1, hours=1),
            )

    def test_cancellation_is_rejected_after_scheduled_or_actual_pickup(self):
        reservation = self.make_reservation()
        with self.assertRaisesMessage(ValidationError, "after pickup"):
            cancel_reservation(
                reservation=reservation,
                customer=self.customer,
                cancelled_at=reservation.pickup_datetime + timedelta(seconds=1),
            )

        reservation.actual_pickup_at = timezone.now()
        reservation.save(update_fields=["actual_pickup_at"])
        with self.assertRaisesMessage(ValidationError, "after pickup"):
            cancel_reservation(
                reservation=reservation,
                customer=self.customer,
                cancelled_at=timezone.now(),
            )

    def test_reminder_command_sends_each_due_reminder_once(self):
        now = timezone.now()
        pickup_reservation = self.make_reservation(
            pickup=now + timedelta(hours=6),
            return_at=now + timedelta(days=2),
        )
        pickup_reservation.status = Reservation.Status.CONFIRMED
        pickup_reservation.save(update_fields=["status"])
        return_vehicle = Vehicle.objects.create(
            make="Reminder",
            model="Return",
            year=2025,
            registration_number="REM-0001",
            category=self.category,
            transmission=Vehicle.Transmission.AUTOMATIC,
            fuel_type=Vehicle.FuelType.PETROL,
            seats=5,
            daily_price=Decimal("1000.00"),
            weekly_discount_pct=0,
            security_deposit=0,
            location=self.location,
        )
        return_reservation = create_reservation(
            customer=self.customer,
            vehicle=return_vehicle,
            pickup_location=self.location,
            return_location=self.location,
            pickup_datetime=now + timedelta(hours=12),
            return_datetime=now + timedelta(hours=20),
        )
        return_reservation.status = Reservation.Status.ACTIVE
        return_reservation.actual_pickup_at = now
        return_reservation.save(update_fields=["status", "actual_pickup_at"])

        call_command("send_reminders")
        pickup_reservation.refresh_from_db()
        return_reservation.refresh_from_db()
        self.assertIsNotNone(pickup_reservation.pickup_reminder_sent_at)
        self.assertIsNotNone(return_reservation.return_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 2)
        call_command("send_reminders")
        self.assertEqual(len(mail.outbox), 2)

    def test_late_fee_grace_period_is_read_from_pricing_settings(self):
        reservation = self.make_reservation()
        settings = PricingSettings.get_solo()
        settings.late_fee_grace_minutes = 60
        settings.save()

        self.assertEqual(
            calculate_late_fee(
                reservation,
                reservation.return_datetime + timedelta(minutes=45),
            ),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculate_late_fee(
                reservation,
                reservation.return_datetime + timedelta(minutes=61),
            ),
            Decimal("1500.00"),
        )

    def test_history_tabs_and_booking_pages_enforce_ownership(self):
        self.client.force_login(self.customer)
        upcoming = self.make_reservation()
        upcoming.status = Reservation.Status.CONFIRMED
        upcoming.save(update_fields=["status"])
        active_pickup = self.pickup + timedelta(days=4)
        active = self.make_reservation(
            pickup=active_pickup,
            return_at=active_pickup + timedelta(days=1),
        )
        active.status = Reservation.Status.ACTIVE
        active.save(update_fields=["status"])
        completed_pickup = self.pickup + timedelta(days=6)
        completed = self.make_reservation(
            pickup=completed_pickup,
            return_at=completed_pickup + timedelta(days=1),
        )
        completed.status = Reservation.Status.COMPLETED
        completed.save(update_fields=["status"])
        cancelled_pickup = self.pickup + timedelta(days=8)
        cancelled = self.make_reservation(
            pickup=cancelled_pickup,
            return_at=cancelled_pickup + timedelta(days=1),
        )
        cancelled.status = Reservation.Status.CANCELLED
        cancelled.save(update_fields=["status"])

        for tab, expected in (
            ("upcoming", upcoming),
            ("active", active),
            ("completed", completed),
            ("cancelled", cancelled),
        ):
            response = self.client.get(
                reverse("bookings:my_bookings"),
                {"tab": tab},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context["reservations"]), [expected])

        book_again = self.client.get(
            reverse("vehicles:list"),
            {"vehicle": upcoming.vehicle_id},
        )
        self.assertEqual(book_again.status_code, 200)
        self.assertEqual(
            book_again.context["filter_form"].cleaned_data["vehicle"],
            upcoming.vehicle,
        )
        self.assertEqual(list(book_again.context["vehicles"]), [upcoming.vehicle])

        self.assertEqual(
            self.client.get(
                reverse("bookings:detail", kwargs={"reservation_id": upcoming.pk})
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("bookings:receipt", kwargs={"reservation_id": upcoming.pk})
            ).status_code,
            200,
        )
        self.assertContains(
            self.client.get(
                reverse("bookings:detail", kwargs={"reservation_id": upcoming.pk})
            ),
            "Confirm cancellation",
        )
        self.assertEqual(
            self.client.get(
                reverse("bookings:my_bookings"), {"tab": "invalid"}
            ).context["active_tab"],
            "upcoming",
        )

        another_customer = User.objects.create_user(
            email="another-history-customer@example.com",
            password="SecurePass!234",
            first_name="Another",
            last_name="Customer",
            phone="5550101",
        )
        self.client.force_login(another_customer)
        for name in ("detail", "receipt"):
            response = self.client.get(
                reverse(
                    f"bookings:{name}",
                    kwargs={"reservation_id": upcoming.pk},
                )
            )
            self.assertEqual(response.status_code, 404)

    def test_booking_history_is_paginated(self):
        for day_offset in range(0, 22, 2):
            pickup = self.pickup + timedelta(days=day_offset)
            self.make_reservation(
                pickup=pickup,
                return_at=pickup + timedelta(hours=12),
            )

        self.client.force_login(self.customer)
        first_page = self.client.get(reverse("bookings:my_bookings"))
        self.assertTrue(first_page.context["is_paginated"])
        self.assertEqual(len(first_page.context["reservations"]), 10)
        second_page = self.client.get(
            reverse("bookings:my_bookings"),
            {"page": 2},
        )
        self.assertEqual(len(second_page.context["reservations"]), 1)

    def test_cancel_sets_fee_and_sends_email(self):
        reservation = self.make_reservation()
        cancelled_at = reservation.pickup_datetime - timedelta(hours=2)
        with self.captureOnCommitCallbacks(execute=True):
            cancelled = cancel_reservation(
                reservation=reservation,
                customer=self.customer,
                cancelled_at=cancelled_at,
            )

        self.assertEqual(cancelled.status, Reservation.Status.CANCELLED)
        self.assertEqual(cancelled.cancellation_fee, Decimal("440.00"))
        self.assertIn(cancelled.reference, mail.outbox[-1].subject)

    def test_create_payment_methods_and_confirmation(self):
        reservation = self.make_reservation()
        payment = create_payment(reservation, Payment.Method.CARD_MOCK)
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.amount, reservation.total_amount)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_booking_api_and_guest_login_redirect(self):
        client = Client()
        booking_path = reverse(
            "bookings:start",
            kwargs={"vehicle_id": self.vehicle.pk},
        )
        response = client.get(booking_path)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertIn("next=", response.url)

        api_response = self.client.get(
            reverse("availability_api"),
            {
                "vehicle_id": self.vehicle.pk,
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            },
        )
        self.assertEqual(api_response.status_code, 200)
        self.assertTrue(api_response.json()["available"])
        self.assertIn("total_amount", api_response.json()["quote"])

        booked = self.client.get(
            reverse(
                "vehicle_booked_dates_api",
                kwargs={"vehicle_id": self.vehicle.pk},
            )
        )
        self.assertEqual(booked.status_code, 200)
        self.assertIn("reservations", booked.json())
        self.assertIn("maintenance", booked.json())
        self.assertEqual(booked.json()["buffer_hours"], 2)

    def test_vehicle_catalog_date_search_hides_booked_vehicle(self):
        self.make_reservation()
        response = self.client.get(
            reverse("vehicles:list"),
            {
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paginator"].count, 0)

    def test_customer_booking_review_mock_payment_confirmation_flow(self):
        self.client.force_login(self.customer)
        start_url = reverse(
            "bookings:start",
            kwargs={"vehicle_id": self.vehicle.pk},
        )
        response = self.client.post(
            start_url,
            {
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
                "pickup_location": self.location.pk,
                "return_location": self.location.pk,
                "notes": "Please call on arrival.",
            },
        )
        self.assertRedirects(response, reverse("bookings:review"))
        self.assertEqual(Reservation.objects.count(), 0)

        review = self.client.get(reverse("bookings:review"))
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "Price breakdown")
        response = self.client.post(reverse("bookings:review"))
        reservation = Reservation.objects.get()
        self.assertRedirects(
            response,
            reverse("bookings:payment", kwargs={"reservation_id": reservation.pk}),
        )

        response = self.client.post(
            reverse("bookings:payment", kwargs={"reservation_id": reservation.pk}),
            {"method": Payment.Method.CARD_MOCK},
        )
        self.assertRedirects(
            response,
            reverse(
                "bookings:confirmation",
                kwargs={"reservation_id": reservation.pk},
            ),
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertTrue(Payment.objects.filter(reservation=reservation).exists())
        self.assertContains(
            self.client.get(
                reverse(
                    "bookings:confirmation",
                    kwargs={"reservation_id": reservation.pk},
                )
            ),
            reservation.reference,
        )

    def test_expired_licence_is_blocked_before_review(self):
        self.profile.licence_expiry = timezone.localdate() + timedelta(days=1)
        self.profile.save(update_fields=["licence_expiry"])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("bookings:start", kwargs={"vehicle_id": self.vehicle.pk}),
            {
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
                "pickup_location": self.location.pk,
                "return_location": self.location.pk,
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "licence must be valid through the return date")
        self.assertNotIn("booking_draft", self.client.session)

    def test_booking_start_get_prefills_vehicle_and_date_submission_errors(self):
        self.client.force_login(self.customer)
        start_url = reverse(
            "bookings:start",
            kwargs={"vehicle_id": self.vehicle.pk},
        )
        response = self.client.get(
            start_url,
            {
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].initial["pickup_location"],
            self.location.pk,
        )
        self.assertEqual(
            response.context["booked_dates_url"],
            reverse(
                "vehicle_booked_dates_api",
                kwargs={"vehicle_id": self.vehicle.pk},
            ),
        )

        payload = {
            "pickup_datetime": (timezone.now() - timedelta(days=1)).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "return_datetime": (timezone.now() + timedelta(days=1)).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "pickup_location": self.location.pk,
            "return_location": self.location.pk,
            "notes": "",
        }
        response = self.client.post(start_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pickup must be in the future")

    def test_booking_start_rejects_missing_profile_and_unavailable_vehicle(self):
        self.client.force_login(self.customer)
        start_url = reverse(
            "bookings:start",
            kwargs={"vehicle_id": self.vehicle.pk},
        )
        payload = {
            "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
            "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            "pickup_location": self.location.pk,
            "return_location": self.location.pk,
            "notes": "",
        }
        self.profile.delete()
        response = self.client.post(start_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Complete a valid driving licence")

        CustomerProfile.objects.create(
            user=self.customer,
            licence_number="RESTORED-LICENCE",
            licence_expiry=timezone.localdate() + timedelta(days=365),
            date_of_birth=timezone.localdate() - timedelta(days=30 * 365),
        )
        self.make_reservation()
        response = self.client.post(start_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not available for the selected dates")

    def test_review_redirects_for_missing_and_stale_booking_drafts(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("bookings:review"))
        self.assertRedirects(response, reverse("vehicles:list"))

        session = self.client.session
        session["booking_draft"] = {
            "user_id": self.customer.pk + 100,
            "vehicle_id": self.vehicle.pk,
            "pickup_location_id": self.location.pk,
            "return_location_id": self.location.pk,
            "pickup_datetime": self.pickup.isoformat(),
            "return_datetime": self.return_at.isoformat(),
        }
        session.save()
        response = self.client.get(reverse("bookings:review"))
        self.assertRedirects(response, reverse("vehicles:list"))

        session = self.client.session
        session["booking_draft"] = {
            "user_id": self.customer.pk,
            "vehicle_id": self.vehicle.pk,
            "pickup_location_id": self.location.pk,
            "return_location_id": self.location.pk,
            "pickup_datetime": self.pickup.isoformat(),
            "return_datetime": self.return_at.isoformat(),
        }
        session.save()
        self.make_reservation()
        response = self.client.get(reverse("bookings:review"))
        self.assertRedirects(
            response,
            reverse("vehicles:detail", kwargs={"pk": self.vehicle.pk}),
        )

    def test_modify_view_gets_context_and_reports_service_validation(self):
        self.client.force_login(self.customer)
        reservation = self.make_reservation()
        response = self.client.get(
            reverse("bookings:modify", kwargs={"reservation_id": reservation.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["reservation"], reservation)
        self.assertEqual(response.context["modification_cutoff_hours"], 24)

        conflicting_pickup = self.pickup + timedelta(days=10)
        self.make_reservation(
            pickup=conflicting_pickup,
            return_at=conflicting_pickup + timedelta(days=1),
        )
        response = self.client.post(
            reverse("bookings:modify", kwargs={"reservation_id": reservation.pk}),
            {
                "pickup_datetime": conflicting_pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": (conflicting_pickup + timedelta(days=1)).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "pickup_location": self.location.pk,
                "return_location": self.location.pk,
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not available")

    def test_payment_get_invalid_method_and_terminal_reservation(self):
        self.client.force_login(self.customer)
        reservation = self.make_reservation()
        payment_url = reverse(
            "bookings:payment",
            kwargs={"reservation_id": reservation.pk},
        )
        self.assertEqual(self.client.get(payment_url).status_code, 200)

        response = self.client.post(payment_url, {"method": "INVALID"})
        self.assertRedirects(response, payment_url)

        reservation.status = Reservation.Status.CANCELLED
        reservation.save(update_fields=["status"])
        response = self.client.get(payment_url)
        self.assertRedirects(
            response,
            reverse(
                "bookings:confirmation",
                kwargs={"reservation_id": reservation.pk},
            ),
        )

    def test_cancel_view_success_and_validation_error(self):
        self.client.force_login(self.customer)
        reservation = self.make_reservation()
        cancel_url = reverse(
            "bookings:cancel",
            kwargs={"reservation_id": reservation.pk},
        )
        response = self.client.post(cancel_url)
        self.assertRedirects(
            response,
            reverse("bookings:detail", kwargs={"reservation_id": reservation.pk}),
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CANCELLED)

        late_pickup = timezone.now() + timedelta(hours=5)
        late_reservation = self.make_reservation(
            pickup=late_pickup,
            return_at=late_pickup + timedelta(days=1),
        )
        late_reservation.actual_pickup_at = timezone.now()
        late_reservation.save(update_fields=["actual_pickup_at"])
        response = self.client.post(
            reverse(
                "bookings:cancel",
                kwargs={"reservation_id": late_reservation.pk},
            )
        )
        self.assertRedirects(
            response,
            reverse(
                "bookings:detail",
                kwargs={"reservation_id": late_reservation.pk},
            ),
        )
        late_reservation.refresh_from_db()
        self.assertEqual(late_reservation.status, Reservation.Status.PENDING)

    def test_cancel_post_requires_csrf_token(self):
        reservation = self.make_reservation()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.customer)

        response = csrf_client.post(
            reverse(
                "bookings:cancel",
                kwargs={"reservation_id": reservation.pk},
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_availability_api_validates_dates_and_returns_unavailable(self):
        api_url = reverse("availability_api")
        response = self.client.get(api_url, {"vehicle_id": self.vehicle.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())

        response = self.client.get(
            api_url,
            {
                "vehicle_id": self.vehicle.pk,
                "pickup_datetime": (timezone.now() - timedelta(days=1)).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", response.json()["error"])

        self.make_reservation()
        response = self.client.get(
            api_url,
            {
                "vehicle_id": self.vehicle.pk,
                "pickup_datetime": self.pickup.strftime("%Y-%m-%d %H:%M"),
                "return_datetime": self.return_at.strftime("%Y-%m-%d %H:%M"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertIsNone(response.json()["quote"])

    def test_booked_dates_api_serializes_reservations_and_maintenance(self):
        reservation = self.make_reservation()
        MaintenanceBlock.objects.create(
            vehicle=self.vehicle,
            start_datetime=self.return_at + timedelta(days=1),
            end_datetime=self.return_at + timedelta(days=2),
            reason="Inspection",
        )

        response = self.client.get(
            reverse(
                "vehicle_booked_dates_api",
                kwargs={"vehicle_id": self.vehicle.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["reservations"][0]["start"], reservation.pickup_datetime.isoformat()
        )
        self.assertEqual(
            data["maintenance"][0]["start"],
            (self.return_at + timedelta(days=1)).isoformat(),
        )


@skipUnless(
    connection.features.has_select_for_update,
    "Database backend does not support SELECT FOR UPDATE.",
)
class ConcurrentBookingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.location = Location.objects.create(
            name="Concurrent Central",
            city="Pune",
            state="Maharashtra",
        )
        category = VehicleCategory.objects.create(name="Concurrent Sedan")
        self.vehicle = Vehicle.objects.create(
            make="Concurrent",
            model="Car",
            year=2025,
            registration_number="CONC-0001",
            category=category,
            transmission=Vehicle.Transmission.AUTOMATIC,
            fuel_type=Vehicle.FuelType.PETROL,
            seats=5,
            daily_price=Decimal("1000.00"),
            weekly_discount_pct=0,
            security_deposit=Decimal("0.00"),
            odometer_km=0,
            location=self.location,
        )
        self.customer = User.objects.create_user(
            email="concurrent@example.com",
            password="Vast!RoadTrip8427",
            first_name="Concurrent",
            last_name="Customer",
            phone="5550100",
        )
        profile = self.customer.customer_profile
        profile.licence_number = "CONCURRENT-LICENCE"
        profile.licence_expiry = timezone.localdate() + timedelta(days=1000)
        profile.save()

    def test_simultaneous_requests_for_same_vehicle_create_only_one(self):
        pickup = timezone.now() + timedelta(days=5)
        return_at = pickup + timedelta(days=1)
        barrier = threading.Barrier(2)
        outcomes = Queue()
        vehicle_id = self.vehicle.pk
        customer_id = self.customer.pk
        location_id = self.location.pk

        def attempt_booking():
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                booking = create_reservation(
                    customer=User.objects.get(pk=customer_id),
                    vehicle=vehicle_id,
                    pickup_location=location_id,
                    return_location=location_id,
                    pickup_datetime=pickup,
                    return_datetime=return_at,
                )
            except ValidationError:
                outcomes.put("unavailable")
            else:
                outcomes.put(booking.pk)
            finally:
                close_old_connections()

        workers = [
            threading.Thread(target=attempt_booking),
            threading.Thread(target=attempt_booking),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        results = [outcomes.get_nowait(), outcomes.get_nowait()]
        self.assertEqual(sum(isinstance(result, int) for result in results), 1)
        self.assertEqual(Reservation.objects.count(), 1)
