"""Tests for the public home page."""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User


class HomePageTests(TestCase):
    def test_home_page_is_available(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find a car for the road ahead")
        self.assertContains(response, "How it works")

    def test_custom_error_pages_are_available(self):
        response = self.client.get("/missing-page/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "We couldn't find that page", status_code=404)

    def test_generic_server_error_page_does_not_expose_debug_details(self):
        from config.urls import server_error

        response = server_error(self.client.get("/"))

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)


class ProductionSettingsTests(SimpleTestCase):
    def test_production_settings_enforce_https_and_secure_cookies(self):
        from config.settings import prod

        self.assertFalse(prod.DEBUG)
        self.assertTrue(prod.SECURE_SSL_REDIRECT)
        self.assertGreaterEqual(prod.SECURE_HSTS_SECONDS, 31_536_000)
        self.assertTrue(prod.SESSION_COOKIE_SECURE)
        self.assertTrue(prod.CSRF_COOKIE_SECURE)


class UserModelTests(TestCase):
    def test_user_uses_email_for_login(self):
        user = User.objects.create_user(
            email="renter@example.com",
            password="Vast!RoadTrip8427",
            first_name="Renter",
            last_name="Example",
            phone="5550100",
        )

        self.assertEqual(user.get_username(), "renter@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
