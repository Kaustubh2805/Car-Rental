"""Booking pages and JSON API routes."""

from django.urls import path

from apps.bookings.views import (
    BookingCancelView,
    BookingConfirmationView,
    BookingDetailView,
    BookingModifyView,
    BookingPaymentView,
    BookingReceiptView,
    BookingReviewView,
    BookingStartView,
    MyBookingsView,
)

app_name = "bookings"

urlpatterns = [
    path("my/", MyBookingsView.as_view(), name="my_bookings"),
    path(
        "vehicles/<int:vehicle_id>/book/",
        BookingStartView.as_view(),
        name="start",
    ),
    path("review/", BookingReviewView.as_view(), name="review"),
    path(
        "<int:reservation_id>/receipt/",
        BookingReceiptView.as_view(),
        name="receipt",
    ),
    path(
        "<int:reservation_id>/",
        BookingDetailView.as_view(),
        name="detail",
    ),
    path(
        "<int:reservation_id>/modify/",
        BookingModifyView.as_view(),
        name="modify",
    ),
    path(
        "<int:reservation_id>/payment/",
        BookingPaymentView.as_view(),
        name="payment",
    ),
    path(
        "<int:reservation_id>/confirmation/",
        BookingConfirmationView.as_view(),
        name="confirmation",
    ),
    path(
        "<int:reservation_id>/cancel/",
        BookingCancelView.as_view(),
        name="cancel",
    ),
]
