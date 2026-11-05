"""Staff and administrator dashboard routes."""

from django.urls import path

from apps.dashboard.views import (
    AuditLogListView,
    CustomerActivationView,
    CustomerDetailView,
    CustomerListView,
    DashboardOverviewView,
    DashboardVehicleCreateView,
    DashboardVehicleListView,
    DashboardVehicleRetireView,
    DashboardVehicleStatusView,
    DashboardVehicleUpdateView,
    MaintenanceCreateView,
    MaintenanceListView,
    ReservationDetailView,
    ReservationListView,
    ReportsView,
    PricingSettingsView,
    StaffCreateView,
    StaffDeactivateView,
    StaffListView,
)

app_name = "dashboard"

urlpatterns = [
    path("", DashboardOverviewView.as_view(), name="overview"),
    path("vehicles/", DashboardVehicleListView.as_view(), name="vehicles"),
    path("vehicles/add/", DashboardVehicleCreateView.as_view(), name="vehicle_add"),
    path(
        "vehicles/<int:vehicle_id>/edit/",
        DashboardVehicleUpdateView.as_view(),
        name="vehicle_edit",
    ),
    path(
        "vehicles/<int:vehicle_id>/status/",
        DashboardVehicleStatusView.as_view(),
        name="vehicle_status",
    ),
    path(
        "vehicles/<int:vehicle_id>/retire/",
        DashboardVehicleRetireView.as_view(),
        name="vehicle_retire",
    ),
    path("maintenance/", MaintenanceListView.as_view(), name="maintenance"),
    path(
        "maintenance/add/",
        MaintenanceCreateView.as_view(),
        name="maintenance_add",
    ),
    path("reservations/", ReservationListView.as_view(), name="reservations"),
    path(
        "reservations/<int:reservation_id>/",
        ReservationDetailView.as_view(),
        name="reservation_detail",
    ),
    path("customers/", CustomerListView.as_view(), name="customers"),
    path(
        "customers/<int:customer_id>/",
        CustomerDetailView.as_view(),
        name="customer_detail",
    ),
    path(
        "customers/<int:customer_id>/activation/",
        CustomerActivationView.as_view(),
        name="customer_activation",
    ),
    path("staff/", StaffListView.as_view(), name="staff"),
    path("staff/add/", StaffCreateView.as_view(), name="staff_add"),
    path(
        "staff/<int:staff_id>/deactivate/",
        StaffDeactivateView.as_view(),
        name="staff_deactivate",
    ),
    path("audit/", AuditLogListView.as_view(), name="audit_log"),
    path("reports/", ReportsView.as_view(), name="reports"),
    path("settings/", PricingSettingsView.as_view(), name="settings"),
]
