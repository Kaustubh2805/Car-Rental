"""Project URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path
from importlib.util import find_spec

from apps.core.views import HomeView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.bookings.api_urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("bookings/", include("apps.bookings.urls")),
    path("vehicles/", include("apps.vehicles.urls")),
    path("", HomeView.as_view(), name="home"),
]


def permission_denied(request, exception=None):
    """Render the public 403 page."""
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    """Render the public 404 page."""
    return render(request, "404.html", status=404)


def server_error(request):
    """Render the public 500 page without exposing internal details."""
    return render(request, "500.html", status=500)


handler403 = "config.urls.permission_denied"
handler404 = "config.urls.page_not_found"
handler500 = "config.urls.server_error"

if settings.DEBUG:
    if find_spec("debug_toolbar"):
        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
