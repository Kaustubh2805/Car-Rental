"""URL patterns for customer account flows."""

from django.urls import path

from apps.accounts.views import (
    AccountLoginView,
    AccountLogoutView,
    AccountPasswordResetCompleteView,
    AccountPasswordResetConfirmView,
    AccountPasswordResetDoneView,
    AccountPasswordResetView,
    CustomerProfileView,
    RegistrationView,
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("login/", AccountLoginView.as_view(), name="login"),
    path("logout/", AccountLogoutView.as_view(), name="logout"),
    path("profile/", CustomerProfileView.as_view(), name="profile"),
    path(
        "password-reset/",
        AccountPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        AccountPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        AccountPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        AccountPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
