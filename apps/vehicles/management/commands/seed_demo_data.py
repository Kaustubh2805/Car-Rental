"""Seed repeatable vehicle catalog data and demo accounts."""

import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import CustomerProfile
from apps.vehicles.models import (
    Feature,
    Location,
    Vehicle,
    VehicleCategory,
)

User = get_user_model()

LOCATIONS = (
    ("Central Pune", "Pune", "Maharashtra", "411001"),
    ("Mumbai Airport", "Mumbai", "Maharashtra", "400099"),
    ("Bengaluru Central", "Bengaluru", "Karnataka", "560001"),
)
CATEGORIES = (
    ("Hatchback", "Compact and easy to park"),
    ("Sedan", "Comfortable everyday travel"),
    ("SUV", "Extra space for passengers and luggage"),
    ("Luxury", "Premium comfort and features"),
    ("Electric", "All-electric vehicles"),
    ("Hybrid", "Fuel-efficient hybrid vehicles"),
    ("Van", "Room for larger groups"),
)
FEATURES = (
    "Air conditioning",
    "Bluetooth",
    "USB charging",
    "Rear camera",
    "Parking sensors",
    "Cruise control",
    "Apple CarPlay",
    "Android Auto",
    "Child seat available",
    "GPS navigation",
    "Sunroof",
    "All-wheel drive",
    "Lane assist",
    "ABS",
    "Airbags",
)
VEHICLE_SPECS = (
    ("Maruti Suzuki", "Swift", "Hatchback", "PETROL", "MANUAL", 5),
    ("Hyundai", "i20", "Hatchback", "PETROL", "AUTOMATIC", 5),
    ("Tata", "Nexon", "SUV", "PETROL", "AUTOMATIC", 5),
    ("Honda", "City", "Sedan", "PETROL", "AUTOMATIC", 5),
    ("Toyota", "Innova", "Van", "DIESEL", "MANUAL", 7),
    ("Mahindra", "XUV700", "SUV", "DIESEL", "AUTOMATIC", 7),
    ("Tata", "Nexon EV", "Electric", "ELECTRIC", "AUTOMATIC", 5),
    ("Toyota", "Camry Hybrid", "Hybrid", "HYBRID", "AUTOMATIC", 5),
    ("BMW", "3 Series", "Luxury", "PETROL", "AUTOMATIC", 5),
    ("Kia", "Carens", "Van", "DIESEL", "MANUAL", 7),
    ("Renault", "Kwid", "Hatchback", "PETROL", "MANUAL", 5),
    ("Skoda", "Slavia", "Sedan", "PETROL", "AUTOMATIC", 5),
    ("Hyundai", "Creta", "SUV", "DIESEL", "AUTOMATIC", 5),
    ("MG", "Comet EV", "Electric", "ELECTRIC", "AUTOMATIC", 4),
    ("Lexus", "ES", "Luxury", "HYBRID", "AUTOMATIC", 5),
    ("Tata", "Tiago", "Hatchback", "CNG", "MANUAL", 5),
    ("Volkswagen", "Virtus", "Sedan", "PETROL", "AUTOMATIC", 5),
    ("BYD", "Atto 3", "Electric", "ELECTRIC", "AUTOMATIC", 5),
    ("Toyota", "Urban Cruiser Hyryder", "Hybrid", "HYBRID", "AUTOMATIC", 5),
    ("Kia", "Seltos", "SUV", "PETROL", "MANUAL", 5),
)


def make_demo_password() -> str:
    """Generate a one-time strong password for a newly seeded demo account."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(20))
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in "!@#$%^&*" for char in password)
        ):
            return password


class Command(BaseCommand):
    help = "Create sample vehicle catalog data and demo accounts."

    @transaction.atomic
    def handle(self, *args, **options):
        locations = [
            Location.objects.get_or_create(
                name=name,
                defaults={
                    "city": city,
                    "state": state,
                    "postal_code": postal_code,
                    "address": f"{name}, {city}",
                },
            )[0]
            for name, city, state, postal_code in LOCATIONS
        ]
        categories = {
            name: VehicleCategory.objects.get_or_create(
                name=name,
                defaults={"description": description},
            )[0]
            for name, description in CATEGORIES
        }
        features = [Feature.objects.get_or_create(name=name)[0] for name in FEATURES]

        for index, (make, model, category, fuel, transmission, seats) in enumerate(
            VEHICLE_SPECS
        ):
            vehicle, _ = Vehicle.objects.get_or_create(
                registration_number=f"DEMO-{index + 1:04d}",
                defaults={
                    "make": make,
                    "model": model,
                    "year": 2021 + index % 5,
                    "category": categories[category],
                    "transmission": transmission,
                    "fuel_type": fuel,
                    "seats": seats,
                    "luggage_capacity": 2 if seats <= 5 else 4,
                    "daily_price": 1800 + index * 350,
                    "weekly_discount_pct": 5 if index % 2 == 0 else 0,
                    "security_deposit": 5000 + index * 500,
                    "odometer_km": 8000 + index * 2700,
                    "location": locations[index % len(locations)],
                    "status": Vehicle.Status.AVAILABLE,
                    "description": (
                        f"Well-maintained {make} {model} available for rent."
                    ),
                },
            )
            vehicle.features.set(
                [features[(index + offset) % len(features)] for offset in range(4)]
            )

        demo_accounts = (
            ("admin@carrental.test", User.Role.ADMIN, True, True),
            ("staff@carrental.test", User.Role.STAFF, True, False),
            ("customer@carrental.test", User.Role.CUSTOMER, False, False),
        )
        new_credentials = []
        for email, role, is_staff, is_superuser in demo_accounts:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                password = make_demo_password()
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    first_name=role.title(),
                    last_name="Demo",
                    phone="0000000000",
                    role=role,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                )
                new_credentials.append((email, password))
            else:
                user.role = role
                user.is_staff = is_staff
                user.is_superuser = is_superuser
                user.is_active = True
                user.save(
                    update_fields=[
                        "role",
                        "is_staff",
                        "is_superuser",
                        "is_active",
                    ]
                )
            if role == User.Role.CUSTOMER:
                CustomerProfile.objects.get_or_create(user=user)

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded 3 locations, 7 categories, 15 features, and 20 vehicles."
            )
        )
        if new_credentials:
            self.stdout.write(
                self.style.WARNING(
                    "Save these one-time demo passwords now; existing passwords "
                    "are not reset when this command is rerun."
                )
            )
            for email, password in new_credentials:
                self.stdout.write(f"{email}: {password}")
        else:
            self.stdout.write("Demo accounts already existed; passwords unchanged.")
