"""Tests for vehicle catalog models, filtering, and public views."""

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from io import StringIO
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.vehicles.models import (
    Feature,
    Location,
    MaintenanceBlock,
    Vehicle,
    VehicleCategory,
    VehicleImage,
)


def make_png(name="vehicle.png", color="blue"):
    """Create a small in-memory PNG image for upload tests."""
    image = Image.new("RGB", (20, 20), color)
    content = BytesIO()
    image.save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


class VehicleCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.city = Location.objects.create(
            name="Pune Central",
            city="Pune",
            state="Maharashtra",
        )
        cls.other_city = Location.objects.create(
            name="Mumbai Airport",
            city="Mumbai",
            state="Maharashtra",
        )
        cls.sedan = VehicleCategory.objects.create(name="Sedan")
        cls.suv = VehicleCategory.objects.create(name="SUV")
        cls.feature = Feature.objects.create(name="Air conditioning")
        cls.vehicles = []
        for index in range(14):
            vehicle = Vehicle.objects.create(
                make="Example",
                model=f"Car {index + 1}",
                year=2020 + index % 5,
                registration_number=f"TEST-{index + 1:04d}",
                category=cls.sedan if index % 2 == 0 else cls.suv,
                transmission=(
                    Vehicle.Transmission.AUTOMATIC
                    if index % 2 == 0
                    else Vehicle.Transmission.MANUAL
                ),
                fuel_type=(
                    Vehicle.FuelType.PETROL
                    if index % 2 == 0
                    else Vehicle.FuelType.DIESEL
                ),
                seats=4 + index % 4,
                luggage_capacity=2,
                daily_price=Decimal(1000 + index * 100),
                weekly_discount_pct=5,
                security_deposit=Decimal("5000.00"),
                odometer_km=10000,
                location=cls.city if index % 2 == 0 else cls.other_city,
                status=Vehicle.Status.AVAILABLE,
                description="A test vehicle.",
            )
            cls.vehicles.append(vehicle)

        cls.retired = Vehicle.objects.create(
            make="Example",
            model="Retired",
            year=2022,
            registration_number="TEST-RETIRED",
            category=cls.sedan,
            transmission=Vehicle.Transmission.AUTOMATIC,
            fuel_type=Vehicle.FuelType.PETROL,
            seats=5,
            luggage_capacity=2,
            daily_price=Decimal("500.00"),
            weekly_discount_pct=0,
            security_deposit=Decimal("0.00"),
            odometer_km=20000,
            location=cls.city,
            status=Vehicle.Status.RETIRED,
        )

    def test_public_list_excludes_retired_vehicles(self):
        response = self.client.get(reverse("vehicles:list"))

        self.assertEqual(response.status_code, 200)
        listed_ids = [vehicle.pk for vehicle in response.context["vehicles"]]
        self.assertNotIn(self.retired.pk, listed_ids)
        self.assertEqual(response.context["paginator"].count, 14)

    def test_list_filters_by_category_transmission_fuel_seats_price_location(self):
        response = self.client.get(
            reverse("vehicles:list"),
            {
                "category": self.sedan.pk,
                "transmission": Vehicle.Transmission.AUTOMATIC,
                "fuel_type": Vehicle.FuelType.PETROL,
                "seats": 5,
                "min_price": "1000",
                "max_price": "2200",
                "location": self.city.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        vehicles = list(response.context["vehicles"])
        self.assertTrue(vehicles)
        for vehicle in vehicles:
            self.assertEqual(vehicle.category, self.sedan)
            self.assertEqual(vehicle.transmission, Vehicle.Transmission.AUTOMATIC)
            self.assertEqual(vehicle.fuel_type, Vehicle.FuelType.PETROL)
            self.assertGreaterEqual(vehicle.seats, 5)
            self.assertGreaterEqual(vehicle.daily_price, Decimal("1000"))
            self.assertLessEqual(vehicle.daily_price, Decimal("2200"))
            self.assertEqual(vehicle.location, self.city)

    def test_list_sorts_by_price_ascending_and_descending(self):
        ascending = self.client.get(
            reverse("vehicles:list"),
            {"sort": "price_asc"},
        )
        descending = self.client.get(
            reverse("vehicles:list"),
            {"sort": "price_desc"},
        )

        ascending_prices = [v.daily_price for v in ascending.context["vehicles"]]
        descending_prices = [v.daily_price for v in descending.context["vehicles"]]
        self.assertEqual(ascending_prices, sorted(ascending_prices))
        self.assertEqual(descending_prices, sorted(descending_prices, reverse=True))

    def test_list_supports_newest_sort(self):
        response = self.client.get(
            reverse("vehicles:list"),
            {"sort": "newest"},
        )

        self.assertEqual(response.status_code, 200)
        actual = list(response.context["vehicles"])
        expected = list(
            Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE).order_by(
                "-created_at",
                "-pk",
            )[:12]
        )
        self.assertEqual([v.pk for v in actual], [v.pk for v in expected])

    def test_list_paginates_twelve_vehicles_and_retains_filters(self):
        response = self.client.get(
            reverse("vehicles:list"),
            {"page": 2, "sort": "price_asc"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["vehicles"]), 2)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertContains(response, "Page 2 of 2")
        self.assertContains(response, "page=1")

    def test_invalid_price_range_displays_validation_error(self):
        response = self.client.get(
            reverse("vehicles:list"),
            {"min_price": "3000", "max_price": "1000"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filter_form"].errors)

    def test_detail_shows_vehicle_specs_features_and_placeholder(self):
        vehicle = self.vehicles[0]
        vehicle.features.add(self.feature)

        response = self.client.get(
            reverse("vehicles:detail", kwargs={"pk": vehicle.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, vehicle.model)
        self.assertContains(response, self.feature.name)
        self.assertContains(response, "Booking")
        self.assertContains(response, "Photo coming soon")

    def test_retired_vehicle_detail_is_not_public(self):
        response = self.client.get(
            reverse("vehicles:detail", kwargs={"pk": self.retired.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_maintenance_block_requires_end_after_start(self):
        block = MaintenanceBlock(
            vehicle=self.vehicles[0],
            start_datetime=timezone.make_aware(datetime(2026, 1, 2, 10)),
            end_datetime=timezone.make_aware(datetime(2026, 1, 2, 9)),
        )

        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_vehicle_image_rejects_oversized_file(self):
        image = SimpleUploadedFile(
            "large.png",
            b"x" * (5 * 1024 * 1024 + 1),
            content_type="image/png",
        )
        vehicle_image = VehicleImage(vehicle=self.vehicles[0], image=image)

        with self.assertRaises(ValidationError):
            vehicle_image.full_clean()

    def test_vehicle_image_accepts_png(self):
        vehicle_image = VehicleImage(
            vehicle=self.vehicles[0],
            image=make_png(),
        )

        vehicle_image.full_clean()

    def test_vehicle_image_generates_small_webp_thumbnail(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                image = Image.new("RGB", (1200, 900), "blue")
                content = BytesIO()
                image.save(content, format="PNG")
                uploaded = SimpleUploadedFile(
                    "large-photo.png",
                    content.getvalue(),
                    content_type="image/png",
                )
                vehicle_image = VehicleImage.objects.create(
                    vehicle=self.vehicles[0],
                    image=uploaded,
                )

                self.assertTrue(vehicle_image.thumbnail.name.endswith(".webp"))
                with vehicle_image.thumbnail.open("rb") as thumbnail_file:
                    with Image.open(thumbnail_file) as thumbnail:
                        self.assertEqual(thumbnail.format, "WEBP")
                        self.assertLessEqual(thumbnail.width, 480)
                        self.assertLessEqual(thumbnail.height, 320)

    def test_vehicle_list_stays_within_bounded_image_query_count(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("vehicles:list"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 8)


class SeedDemoDataTests(TestCase):
    def test_command_seeds_expected_catalog_and_demo_users_idempotently(self):
        from django.core.management import call_command
        from django.contrib.auth import get_user_model

        User = get_user_model()
        call_command("seed_demo_data", stdout=StringIO())

        self.assertEqual(Location.objects.count(), 3)
        self.assertEqual(VehicleCategory.objects.count(), 7)
        self.assertEqual(Feature.objects.count(), 15)
        self.assertEqual(Vehicle.objects.count(), 20)
        self.assertTrue(
            User.objects.filter(
                email="admin@carrental.test", is_superuser=True
            ).exists()
        )
        self.assertTrue(
            User.objects.filter(
                email="staff@carrental.test", role=User.Role.STAFF
            ).exists()
        )
        self.assertTrue(User.objects.filter(email="customer@carrental.test").exists())

        call_command("seed_demo_data", stdout=StringIO())
        self.assertEqual(Vehicle.objects.count(), 20)
