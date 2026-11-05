"""Public vehicle catalog URL patterns."""

from django.urls import path

from apps.vehicles.views import VehicleDetailView, VehicleListView

app_name = "vehicles"

urlpatterns = [
    path("", VehicleListView.as_view(), name="list"),
    path("<int:pk>/", VehicleDetailView.as_view(), name="detail"),
]
