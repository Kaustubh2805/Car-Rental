"""Tests for account registration, authentication, and access control."""

from datetime import date
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import CustomerProfile, LoginAttempt
from apps.accounts.validators import StrongPasswordValidator

User = get_user_model()


class AccountFlowTests(TestCase):
    def create_customer(self, email="customer@example.com"):
        return User.objects.create_user(
            email=email,
            password="Vast!RoadTrip8427",
            first_name="Casey",
            last_name="Renter",
            phone="5550100",
        )

    def test_registration_creates_customer_and_profile(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "new-customer@example.com",
                "first_name": "Avery",
                "last_name": "Driver",
                "phone": "5550123",
                "date_of_birth": "1995-01-15",
                "licence_number": "LICENCE-100",
                "licence_expiry": "2099-12-31",
                "password1": "Vast!RoadTrip8427",
                "password2": "Vast!RoadTrip8427",
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(email="new-customer@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.check_password("Vast!RoadTrip8427"))
        profile = CustomerProfile.objects.get(user=user)
        self.assertEqual(profile.licence_number, "LICENCE-100")

    def test_registration_rejects_underage_customer(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "young-customer@example.com",
                "first_name": "Young",
                "last_name": "Driver",
                "phone": "5550123",
                "date_of_birth": date.today().isoformat(),
                "licence_number": "LICENCE-101",
                "licence_expiry": "2099-12-31",
                "password1": "Vast!RoadTrip8427",
                "password2": "Vast!RoadTrip8427",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            User.objects.filter(email="young-customer@example.com").exists()
        )
        self.assertContains(response, "at least 18 years old")

    def test_registration_rejects_expired_licence(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "expired-licence@example.com",
                "first_name": "Avery",
                "last_name": "Driver",
                "phone": "5550123",
                "date_of_birth": "1995-01-15",
                "licence_number": "LICENCE-102",
                "licence_expiry": timezone.localdate().isoformat(),
                "password1": "Vast!RoadTrip8427",
                "password2": "Vast!RoadTrip8427",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            User.objects.filter(email="expired-licence@example.com").exists()
        )
        self.assertContains(response, "must be in the future")

    def test_strong_password_validator_rejects_weak_password(self):
        with self.assertRaises(ValidationError):
            StrongPasswordValidator().validate("weak")

    def test_login_honors_next_and_logout_clears_session(self):
        user = self.create_customer()
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.email,
                "password": "Vast!RoadTrip8427",
                "next": "/requested-page/",
            },
        )
        self.assertRedirects(
            response,
            "/requested-page/",
            fetch_redirect_response=False,
        )

        logout_response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(logout_response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_profile_can_be_edited(self):
        user = self.create_customer()
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Casey",
                "last_name": "Renter",
                "phone": "5550199",
                "address": "12 Rental Street",
                "city": "Pune",
                "state": "Maharashtra",
                "postal_code": "411001",
                "date_of_birth": "1995-01-15",
                "licence_number": "LICENCE-200",
                "licence_expiry": "2099-12-31",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.phone, "5550199")
        profile = CustomerProfile.objects.get(user=user)
        self.assertEqual(profile.city, "Pune")
        self.assertEqual(profile.licence_number, "LICENCE-200")

    def test_five_failed_logins_trigger_lockout(self):
        self.create_customer()
        login_url = reverse("accounts:login")

        for _ in range(5):
            response = self.client.post(
                login_url,
                {
                    "username": "customer@example.com",
                    "password": "wrong-password",
                },
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(LoginAttempt.objects.count(), 5)
        response = self.client.post(
            login_url,
            {
                "username": "customer@example.com",
                "password": "Vast!RoadTrip8427",
            },
        )
        self.assertContains(response, "Too many failed sign-in attempts")
        self.assertEqual(LoginAttempt.objects.count(), 5)

    def test_expired_login_attempts_do_not_trigger_lockout(self):
        for _ in range(5):
            LoginAttempt.objects.create(
                email="customer@example.com",
                ip_address="127.0.0.1",
            )
        LoginAttempt.objects.all().update(
            created_at=timezone.now() - timedelta(minutes=16)
        )

        user = self.create_customer()
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.email,
                "password": "Vast!RoadTrip8427",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_email_and_confirmation_flow(self):
        user = self.create_customer()
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": user.email},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        confirm_url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uid, "token": token},
        )
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/set-password/"))
        response = self.client.post(
            response.url,
            {
                "new_password1": "NewVast!RoadTrip8427",
                "new_password2": "NewVast!RoadTrip8427",
            },
        )

        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewVast!RoadTrip8427"))


@override_settings(ROOT_URLCONF="apps.accounts.test_urls")
class RoleRestrictionTests(TestCase):
    def test_customer_gets_forbidden_on_staff_only_view(self):
        customer = User.objects.create_user(
            email="customer@example.com",
            password="Vast!RoadTrip8427",
            first_name="Casey",
            last_name="Renter",
            phone="5550100",
        )
        self.client.force_login(customer)

        response = self.client.get("/staff-only/")

        self.assertEqual(response.status_code, 403)


class AccountAdminTests(TestCase):
    def test_staff_can_open_user_and_customer_profile_admin(self):
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="Vast!RoadTrip8427",
            first_name="Admin",
            last_name="User",
            phone="5550101",
        )
        self.client.force_login(admin_user)

        user_response = self.client.get(reverse("admin:accounts_user_add"))
        profile_response = self.client.get(
            reverse("admin:accounts_customerprofile_changelist")
        )

        self.assertEqual(user_response.status_code, 200)
        self.assertEqual(profile_response.status_code, 200)
