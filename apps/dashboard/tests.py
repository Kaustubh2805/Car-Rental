"""Tests for dashboard permissions and staff rental operations."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.accounts.validators import validate_adult
from apps.accounts.models import User
from apps.bookings.models import Reservation
from apps.bookings.models import Payment
from apps.bookings.services.pricing import calculate_quote
from apps.bookings.services.lifecycle import (
    confirm_reservation,
    pick_up_reservation,
    return_reservation,
    staff_cancel_reservation,
)
from apps.core.models import AuditLog, PricingSettings
from apps.vehicles.models import Location, Vehicle, VehicleCategory


class DashboardTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.location = Location.objects.create(
            name="Operations Branch",
            city="Pune",
            state="Maharashtra",
        )
        cls.category = VehicleCategory.objects.create(name="Operations Category")
        cls.vehicle = Vehicle.objects.create(
            make="Operations",
            model="Test",
            year=2025,
            registration_number="OPS-0001",
            category=cls.category,
            transmission=Vehicle.Transmission.AUTOMATIC,
            fuel_type=Vehicle.FuelType.PETROL,
            seats=5,
            luggage_capacity=3,
            daily_price=Decimal("800.00"),
            weekly_discount_pct=Decimal("5.00"),
            security_deposit=Decimal("3000.00"),
            odometer_km=1000,
            location=cls.location,
        )
        cls.customer = User.objects.create_user(
            email="dashboard-customer@example.com",
            password="SecurePass!234",
            first_name="Dash",
            last_name="Customer",
            phone="5550100",
        )
        profile = cls.customer.customer_profile
        profile.licence_number = "DASHBOARD-LICENCE"
        profile.licence_expiry = timezone.localdate() + timedelta(days=365)
        profile.save()
        cls.staff = User.objects.create_user(
            email="dashboard-staff@example.com",
            password="SecurePass!234",
            first_name="Dash",
            last_name="Staff",
            role=User.Role.STAFF,
            is_staff=True,
        )
        cls.admin = User.objects.create_superuser(
            email="dashboard-admin@example.com",
            password="SecurePass!234",
            first_name="Dash",
            last_name="Admin",
            phone="5550102",
        )
        pickup = timezone.now() + timedelta(days=5)
        cls.reservation = Reservation.objects.create(
            reference="CR-2026-900001",
            customer=cls.customer,
            vehicle=cls.vehicle,
            pickup_location=cls.location,
            return_location=cls.location,
            pickup_datetime=pickup,
            return_datetime=pickup + timedelta(days=2),
            status=Reservation.Status.PENDING,
            daily_price_snapshot=Decimal("800.00"),
            rental_days=2,
            base_amount=Decimal("1600.00"),
            tax_amount=Decimal("288.00"),
            extras_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("1888.00"),
            security_deposit=Decimal("3000.00"),
        )

    def setUp(self):
        self.settings = PricingSettings.get_solo()
        self.settings.late_fee_multiplier = Decimal("1.50")
        self.settings.save()


class DashboardPermissionTests(DashboardTestCase):
    def test_guest_redirects_from_dashboard(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_customer_is_denied_every_dashboard_page_and_action(self):
        self.client.force_login(self.customer)
        get_urls = (
            "overview",
            "vehicles",
            "vehicle_add",
            "vehicle_edit",
            "maintenance",
            "maintenance_add",
            "reservations",
            "reservation_detail",
            "customers",
            "customer_detail",
            "staff",
            "staff_add",
            "audit_log",
            "reports",
            "settings",
        )
        for name in get_urls:
            with self.subTest(name=name):
                kwargs = {}
                if name == "vehicle_edit":
                    kwargs["vehicle_id"] = self.vehicle.pk
                elif name == "reservation_detail":
                    kwargs["reservation_id"] = self.reservation.pk
                elif name == "customer_detail":
                    kwargs["customer_id"] = self.customer.pk
                response = self.client.get(
                    reverse(f"dashboard:{name}", kwargs=kwargs or None)
                )
                self.assertEqual(response.status_code, 403)

        post_routes = (
            (
                "vehicle_status",
                {"vehicle_id": self.vehicle.pk},
                {"status": "MAINTENANCE"},
            ),
            ("vehicle_retire", {"vehicle_id": self.vehicle.pk}, {}),
            (
                "customer_activation",
                {"customer_id": self.customer.pk},
                {"active": "false"},
            ),
            ("staff_deactivate", {"staff_id": self.staff.pk}, {}),
            (
                "reservation_detail",
                {"reservation_id": self.reservation.pk},
                {"action": "confirm"},
            ),
        )
        for name, kwargs, data in post_routes:
            with self.subTest(name=name):
                response = self.client.post(
                    reverse(f"dashboard:{name}", kwargs=kwargs),
                    data,
                )
                self.assertEqual(response.status_code, 403)

    def test_staff_can_read_operations_pages_but_admin_only_routes_are_denied(self):
        self.client.force_login(self.staff)
        for name, kwargs in (
            ("overview", None),
            ("vehicles", None),
            ("reservations", None),
            ("reservation_detail", {"reservation_id": self.reservation.pk}),
            ("customers", None),
            ("customer_detail", {"customer_id": self.customer.pk}),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f"dashboard:{name}", kwargs=kwargs)
                    ).status_code,
                    200,
                )

        for name, kwargs in (
            ("vehicle_add", None),
            ("vehicle_edit", {"vehicle_id": self.vehicle.pk}),
            ("maintenance", None),
            ("maintenance_add", None),
            ("staff", None),
            ("staff_add", None),
            ("audit_log", None),
            ("reports", None),
            ("settings", None),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"dashboard:{name}", kwargs=kwargs))
                self.assertEqual(response.status_code, 403)

        for name, kwargs, data in (
            ("vehicle_retire", {"vehicle_id": self.vehicle.pk}, {}),
            (
                "customer_activation",
                {"customer_id": self.customer.pk},
                {"active": "false"},
            ),
            ("staff_deactivate", {"staff_id": self.staff.pk}, {}),
        ):
            with self.subTest(name=name):
                response = self.client.post(
                    reverse(f"dashboard:{name}", kwargs=kwargs),
                    data,
                )
                self.assertEqual(response.status_code, 403)

    def test_admin_can_access_admin_sections_and_staff_can_change_vehicle_status(self):
        self.client.force_login(self.admin)
        for name, kwargs in (
            ("vehicle_add", None),
            ("vehicle_edit", {"vehicle_id": self.vehicle.pk}),
            ("maintenance", None),
            ("maintenance_add", None),
            ("staff", None),
            ("staff_add", None),
            ("audit_log", None),
            ("reports", None),
            ("settings", None),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(
                        reverse(f"dashboard:{name}", kwargs=kwargs)
                    ).status_code,
                    200,
                )

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("dashboard:vehicle_status", kwargs={"vehicle_id": self.vehicle.pk}),
            {"status": Vehicle.Status.MAINTENANCE},
        )
        self.assertEqual(response.status_code, 302)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, Vehicle.Status.MAINTENANCE)

    def test_staff_cannot_restore_a_retired_vehicle(self):
        self.vehicle.status = Vehicle.Status.RETIRED
        self.vehicle.save(update_fields=["status"])
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("dashboard:vehicle_status", kwargs={"vehicle_id": self.vehicle.pk}),
            {"status": Vehicle.Status.AVAILABLE},
        )
        self.assertEqual(response.status_code, 302)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, Vehicle.Status.RETIRED)

    def test_admin_vehicle_price_edits_and_customer_deactivation_are_audited(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dashboard:vehicle_edit", kwargs={"vehicle_id": self.vehicle.pk}),
            {
                "make": self.vehicle.make,
                "model": self.vehicle.model,
                "year": self.vehicle.year,
                "registration_number": self.vehicle.registration_number,
                "category": self.category.pk,
                "transmission": self.vehicle.transmission,
                "fuel_type": self.vehicle.fuel_type,
                "seats": self.vehicle.seats,
                "luggage_capacity": self.vehicle.luggage_capacity,
                "daily_price": "925.00",
                "weekly_discount_pct": "7.00",
                "security_deposit": "3500.00",
                "odometer_km": self.vehicle.odometer_km,
                "location": self.location.pk,
                "status": self.vehicle.status,
                "description": "",
                "features": [],
            },
        )
        self.assertEqual(response.status_code, 302)
        price_event = AuditLog.objects.get(action="vehicle.updated")
        self.assertEqual(price_event.changes["daily_price"]["from"], "800.00")
        self.assertEqual(price_event.changes["daily_price"]["to"], "925.00")
        self.assertEqual(price_event.changes["weekly_discount_pct"]["to"], "7.00")

        response = self.client.post(
            reverse(
                "dashboard:customer_activation",
                kwargs={"customer_id": self.customer.pk},
            ),
            {"active": "false"},
        )
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user.deactivated",
                object_id=str(self.customer.pk),
            ).exists()
        )
        response = self.client.post(
            reverse(
                "dashboard:customer_activation",
                kwargs={"customer_id": self.customer.pk},
            ),
            {"active": "true"},
        )
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user.reactivated",
                object_id=str(self.customer.pk),
            ).exists()
        )

    def test_admin_can_soft_retire_vehicle_and_audit_status(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dashboard:vehicle_retire", kwargs={"vehicle_id": self.vehicle.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.status, Vehicle.Status.RETIRED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="vehicle.retired",
                object_id=str(self.vehicle.pk),
            ).exists()
        )

    def test_admin_can_create_staff_account_and_audit_it(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dashboard:staff_add"),
            {
                "email": "new-operations-staff@example.com",
                "first_name": "New",
                "last_name": "Staff",
                "phone": "5550199",
                "password1": "ExcellentStaff!987",
                "password2": "ExcellentStaff!987",
            },
        )
        self.assertEqual(response.status_code, 302)
        new_staff = User.objects.get(email="new-operations-staff@example.com")
        self.assertEqual(new_staff.role, User.Role.STAFF)
        self.assertTrue(new_staff.is_staff)
        self.assertTrue(
            AuditLog.objects.filter(
                action="staff.created",
                object_id=str(new_staff.pk),
            ).exists()
        )
        response = self.client.post(
            reverse("dashboard:staff_deactivate", kwargs={"staff_id": new_staff.pk})
        )
        self.assertEqual(response.status_code, 302)
        new_staff.refresh_from_db()
        self.assertFalse(new_staff.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action="user.deactivated",
                object_id=str(new_staff.pk),
            ).exists()
        )


class ReservationLifecycleTests(DashboardTestCase):
    def test_staff_reservation_actions_work_through_dashboard(self):
        self.client.force_login(self.staff)
        detail_url = reverse(
            "dashboard:reservation_detail",
            kwargs={"reservation_id": self.reservation.pk},
        )
        response = self.client.post(detail_url, {"action": "confirm"})
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            detail_url,
            {
                "action": "pickup",
                "odometer_km": "1150",
                "fuel_level": str(Reservation.FuelLevel.FULL),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.ACTIVE)

        self.reservation.pickup_datetime = timezone.now() - timedelta(days=3)
        self.reservation.return_datetime = timezone.now() - timedelta(days=1)
        self.reservation.save(update_fields=["pickup_datetime", "return_datetime"])
        response = self.client.post(
            detail_url,
            {
                "action": "return",
                "odometer_km": "1300",
                "fuel_level": str(Reservation.FuelLevel.HALF),
                "damage_notes": "No damage noted.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.COMPLETED)
        self.assertEqual(self.reservation.late_fee, Decimal("2400.00"))

    def test_status_transitions_and_return_processing_calculate_late_fee(self):
        with self.assertRaisesMessage(ValidationError, "Only confirmed reservations"):
            pick_up_reservation(
                reservation=self.reservation,
                actor=self.staff,
                odometer_km=1100,
                fuel_level=Reservation.FuelLevel.FULL,
            )
        confirmed = confirm_reservation(
            reservation=self.reservation,
            actor=self.staff,
        )
        self.assertEqual(confirmed.status, Reservation.Status.CONFIRMED)
        with self.assertRaisesMessage(ValidationError, "Only pending reservations"):
            confirm_reservation(reservation=confirmed, actor=self.staff)

        with self.assertRaisesMessage(ValidationError, "below the vehicle odometer"):
            pick_up_reservation(
                reservation=confirmed,
                actor=self.staff,
                odometer_km=900,
                fuel_level=Reservation.FuelLevel.FULL,
            )
        picked_up = pick_up_reservation(
            reservation=confirmed,
            actor=self.staff,
            odometer_km=1200,
            fuel_level=Reservation.FuelLevel.THREE_QUARTERS,
        )
        self.assertEqual(picked_up.status, Reservation.Status.ACTIVE)
        self.assertEqual(picked_up.actual_pickup_at is not None, True)

        returned_at = self.reservation.return_datetime + timedelta(days=2)
        completed = return_reservation(
            reservation=picked_up,
            actor=self.staff,
            odometer_km=1400,
            fuel_level=Reservation.FuelLevel.HALF,
            damage_notes="Small scratch reported.",
            returned_at=returned_at,
        )
        self.assertEqual(completed.status, Reservation.Status.COMPLETED)
        self.assertEqual(completed.late_fee, Decimal("2400.00"))
        self.assertEqual(completed.damage_notes, "Small scratch reported.")
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.odometer_km, 1400)
        self.assertEqual(
            AuditLog.objects.filter(
                action="reservation.status_changed",
                object_id=str(self.reservation.pk),
            ).count(),
            3,
        )
        with self.assertRaisesMessage(ValidationError, "Only active reservations"):
            return_reservation(
                reservation=completed,
                actor=self.staff,
                odometer_km=1450,
                fuel_level=Reservation.FuelLevel.HALF,
            )
        with self.assertRaisesMessage(ValidationError, "Only pending or confirmed"):
            staff_cancel_reservation(reservation=completed, actor=self.staff)

    def test_cancel_requires_pending_or_confirmed_and_logs_status(self):
        cancelled = staff_cancel_reservation(
            reservation=self.reservation,
            actor=self.staff,
        )
        self.assertEqual(cancelled.status, Reservation.Status.CANCELLED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="reservation.status_changed",
                object_id=str(cancelled.pk),
            ).exists()
        )
        with self.assertRaisesMessage(ValidationError, "Only pending or confirmed"):
            staff_cancel_reservation(reservation=cancelled, actor=self.staff)

    def test_dashboard_pages_render_overview_and_filtered_reservations(self):
        self.client.force_login(self.staff)
        overview = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, "Revenue per month")
        response = self.client.get(
            reverse("dashboard:reservations"),
            {"status": Reservation.Status.PENDING, "customer": self.customer.email},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["reservations"]), [self.reservation])


class ReportsAndSettingsTests(DashboardTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_reports_aggregate_revenue_utilization_top_vehicle_and_status(self):
        today = timezone.localdate()
        start = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )
        self.reservation.pickup_datetime = start + timedelta(hours=2)
        self.reservation.return_datetime = start + timedelta(hours=26)
        self.reservation.status = Reservation.Status.COMPLETED
        self.reservation.save(
            update_fields=["pickup_datetime", "return_datetime", "status"]
        )
        Payment.objects.create(
            reservation=self.reservation,
            amount=Decimal("1888.00"),
            method=Payment.Method.CARD_MOCK,
            status=Payment.Status.PAID,
            paid_at=timezone.now(),
        )

        response = self.client.get(
            reverse("dashboard:reports"),
            {"start_date": today.isoformat(), "end_date": today.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["daily_revenue"])[0]["revenue"],
            Decimal("1888.00"),
        )
        self.assertEqual(
            list(response.context["monthly_revenue"])[0]["revenue"],
            Decimal("1888.00"),
        )
        self.assertEqual(
            list(response.context["top_vehicles"])[0]["bookings"],
            1,
        )
        self.assertEqual(
            list(response.context["status_breakdown"]),
            [{"status": Reservation.Status.COMPLETED, "count": 1}],
        )
        utilization = next(
            row
            for row in response.context["utilization"]
            if row["vehicle"].pk == self.vehicle.pk
        )
        self.assertEqual(utilization["booked_hours"], 22.0)

    def test_revenue_report_csv_export_has_expected_rows(self):
        today = timezone.localdate()
        Payment.objects.create(
            reservation=self.reservation,
            amount=Decimal("1888.00"),
            method=Payment.Method.CARD_MOCK,
            status=Payment.Status.PAID,
            paid_at=timezone.now(),
        )
        response = self.client.get(
            reverse("dashboard:reports"),
            {
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
                "export": "revenue_daily",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("date,revenue", response.content.decode())
        self.assertIn("1888.00", response.content.decode())
        self.assertIn("attachment;", response["Content-Disposition"])
        for report in (
            "revenue_monthly",
            "utilization",
            "top_vehicles",
            "booking_status",
        ):
            with self.subTest(report=report):
                csv_response = self.client.get(
                    reverse("dashboard:reports"),
                    {
                        "start_date": today.isoformat(),
                        "end_date": today.isoformat(),
                        "export": report,
                    },
                )
                self.assertEqual(csv_response.status_code, 200)
                self.assertTrue(csv_response["Content-Type"].startswith("text/csv"))

    def test_settings_update_changes_quote_tax_and_late_fee_policy(self):
        vehicle = self.vehicle
        pickup = timezone.now() + timedelta(days=5)
        quote_before = calculate_quote(
            vehicle,
            pickup,
            pickup + timedelta(days=1),
        )
        response = self.client.post(
            reverse("dashboard:settings"),
            {
                "tax_rate_pct": "5.00",
                "booking_buffer_hours": "4",
                "cancellation_free_hours": "48",
                "cancellation_fee_pct": "35.00",
                "late_fee_multiplier": "2.00",
                "late_fee_grace_minutes": "90",
                "minimum_driver_age": "21",
            },
        )
        self.assertRedirects(response, reverse("dashboard:settings"))
        settings_obj = PricingSettings.get_solo()
        self.assertEqual(settings_obj.minimum_driver_age, 21)
        self.assertEqual(settings_obj.late_fee_grace_minutes, 90)
        quote_after = calculate_quote(
            vehicle,
            pickup,
            pickup + timedelta(days=1),
        )
        self.assertNotEqual(quote_before.tax_amount, quote_after.tax_amount)
        self.assertEqual(quote_after.tax_amount, Decimal("40.00"))
        self.assertTrue(
            AuditLog.objects.filter(action="pricing_settings.updated").exists()
        )
        with self.assertRaisesMessage(DjangoValidationError, "at least 21 years old"):
            validate_adult(timezone.localdate() - timedelta(days=365 * 20))
