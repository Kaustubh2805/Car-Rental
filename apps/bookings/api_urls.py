"""Root-level JSON API URL patterns."""

from django.urls import path

from apps.bookings.views import AvailabilityAPIView, VehicleBookedDatesAPIView

urlpatterns = [
    path("availability/", AvailabilityAPIView.as_view(), name="availability_api"),
    path(
        "vehicles/<int:vehicle_id>/booked-dates/",
        VehicleBookedDatesAPIView.as_view(),
        name="vehicle_booked_dates_api",
    ),
]
