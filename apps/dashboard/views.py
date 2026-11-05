"""Staff and administrator operations dashboard views."""

from calendar import month_abbr
import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.accounts.models import User
from apps.bookings.models import Payment, Reservation
from apps.bookings.services.availability import search_available_vehicles
from apps.bookings.services.lifecycle import (
    confirm_reservation,
    pick_up_reservation,
    return_reservation,
    staff_cancel_reservation,
)
from apps.bookings.services.pricing import calculate_late_fee
from apps.core.audit import record_audit
from apps.core.mixins import RoleRequiredMixin
from apps.core.models import AuditLog, PricingSettings
from apps.dashboard.forms import (
    CustomerSearchForm,
    MaintenanceBlockForm,
    PickupForm,
    PricingSettingsForm,
    ReportsDateRangeForm,
    ReservationFilterForm,
    ReturnForm,
    StaffCreateForm,
    VehicleForm,
    VehicleStatusForm,
)
from apps.vehicles.models import MaintenanceBlock, Vehicle, VehicleImage
from apps.vehicles.validators import validate_vehicle_image

STAFF_ROLES = (User.Role.STAFF, User.Role.ADMIN)
ADMIN_ROLES = (User.Role.ADMIN,)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ADMIN_ROLES


class DashboardOverviewView(RoleRequiredMixin, TemplateView):
    allowed_roles = STAFF_ROLES
    template_name = "dashboard/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.localtime()
        today = now.date()
        month_start = today.replace(day=1)
        context["total_vehicles"] = Vehicle.objects.count()
        context["available_vehicles"] = search_available_vehicles(
            now,
            now + timedelta(minutes=1),
        ).count()
        context["active_rentals"] = Reservation.objects.filter(
            status=Reservation.Status.ACTIVE
        ).count()
        context["today_pickups"] = Reservation.objects.filter(
            pickup_datetime__date=today,
            status__in=(Reservation.Status.PENDING, Reservation.Status.CONFIRMED),
        ).count()
        context["today_returns"] = Reservation.objects.filter(
            return_datetime__date=today,
            status=Reservation.Status.ACTIVE,
        ).count()
        context["month_revenue"] = Payment.objects.filter(
            status=Payment.Status.PAID,
            paid_at__date__gte=month_start,
            paid_at__date__lte=today,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        context["recent_reservations"] = Reservation.objects.select_related(
            "customer", "vehicle"
        ).order_by("-created_at")[:8]

        week_start = today - timedelta(days=today.weekday())
        weeks_ago = week_start - timedelta(weeks=7)
        weekly = (
            Reservation.objects.filter(created_at__date__gte=weeks_ago)
            .annotate(period=TruncWeek("created_at"))
            .values("period")
            .annotate(total=Count("pk"))
            .order_by("period")
        )
        weekly_counts = {row["period"].date(): row["total"] for row in weekly}
        week_labels = [week_start - timedelta(weeks=i) for i in range(7, -1, -1)]
        context["weekly_labels"] = [day.strftime("%b %d") for day in week_labels]
        context["weekly_values"] = [weekly_counts.get(day, 0) for day in week_labels]

        month_first = month_start.replace(day=1)
        month_starts = [month_first]
        for _ in range(5):
            previous = month_starts[-1] - timedelta(days=1)
            month_starts.append(previous.replace(day=1))
        month_starts.reverse()
        payments = (
            Payment.objects.filter(
                status=Payment.Status.PAID,
                paid_at__date__gte=month_starts[0],
                paid_at__date__lte=today,
            )
            .annotate(period=TruncMonth("paid_at"))
            .values("period")
            .annotate(total=Sum("amount"))
            .order_by("period")
        )
        revenue_by_month = {
            row["period"].date().replace(day=1): row["total"] for row in payments
        }
        context["revenue_labels"] = [month_abbr[month.month] for month in month_starts]
        context["revenue_values"] = [
            float(revenue_by_month.get(month, Decimal("0.00")))
            for month in month_starts
        ]
        return context


class DashboardVehicleListView(RoleRequiredMixin, ListView):
    allowed_roles = STAFF_ROLES
    template_name = "dashboard/vehicle_list.html"
    context_object_name = "vehicles"
    paginate_by = 20

    def get_queryset(self):
        queryset = Vehicle.objects.select_related("category", "location")
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        if query:
            queryset = queryset.filter(
                Q(make__icontains=query)
                | Q(model__icontains=query)
                | Q(registration_number__icontains=query)
            )
        if status in Vehicle.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["status_choices"] = Vehicle.Status.choices
        context["status_form"] = VehicleStatusForm(
            admin_user=self.request.user.role == User.Role.ADMIN
        )
        return context


class AdminVehicleFormMixin(AdminRequiredMixin):
    form_class = VehicleForm
    template_name = "dashboard/vehicle_form.html"

    def form_valid(self, form):
        files = self.request.FILES.getlist("images")
        for uploaded in files:
            image = VehicleImage(vehicle=form.instance, image=uploaded)
            try:
                image.full_clean()
            except ValidationError as error:
                form.add_error(None, error)
                return self.form_invalid(form)
        is_new = form.instance.pk is None
        old_values = {}
        if not is_new:
            old = Vehicle.objects.get(pk=form.instance.pk)
            old_values = {
                "daily_price": str(old.daily_price),
                "weekly_discount_pct": str(old.weekly_discount_pct),
                "security_deposit": str(old.security_deposit),
                "status": old.status,
            }
        for uploaded in files:
            try:
                validate_vehicle_image(uploaded)
            except ValidationError as error:
                form.add_error(None, error)
                return self.form_invalid(form)
        response = super().form_valid(form)
        for uploaded in files:
            VehicleImage.objects.create(vehicle=self.object, image=uploaded)
        changes = {}
        if is_new:
            changes["created"] = True
        else:
            for field in ("daily_price", "weekly_discount_pct", "security_deposit"):
                new_value = str(getattr(self.object, field))
                if old_values[field] != new_value:
                    changes[field] = {
                        "from": old_values[field],
                        "to": new_value,
                    }
        if old_values and old_values["status"] != self.object.status:
            changes["status"] = {
                "from": old_values["status"],
                "to": self.object.status,
            }
        if changes:
            record_audit(
                actor=self.request.user,
                action="vehicle.updated" if not is_new else "vehicle.created",
                obj=self.object,
                changes=changes,
            )
        return response

    def get_success_url(self):
        return reverse("dashboard:vehicles")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vehicle_images"] = (
            self.object.images.all()
            if self.object is not None and self.object.pk
            else ()
        )
        return context


class DashboardVehicleCreateView(AdminVehicleFormMixin, CreateView):
    model = Vehicle


class DashboardVehicleUpdateView(AdminVehicleFormMixin, UpdateView):
    model = Vehicle
    pk_url_kwarg = "vehicle_id"


class DashboardVehicleRetireView(AdminRequiredMixin, View):
    def post(self, request, vehicle_id):
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
        old_status = vehicle.status
        vehicle.status = Vehicle.Status.RETIRED
        vehicle.save(update_fields=["status", "updated_at"])
        record_audit(
            actor=request.user,
            action="vehicle.retired",
            obj=vehicle,
            changes={"status": {"from": old_status, "to": vehicle.status}},
        )
        messages.success(request, "Vehicle retired from the rental fleet.")
        return redirect("dashboard:vehicles")


class DashboardVehicleStatusView(RoleRequiredMixin, View):
    allowed_roles = STAFF_ROLES

    def post(self, request, vehicle_id):
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
        form = VehicleStatusForm(
            request.POST,
            admin_user=request.user.role == User.Role.ADMIN,
        )
        if not form.is_valid():
            messages.error(request, "Select a valid vehicle status.")
            return redirect("dashboard:vehicles")
        if (
            request.user.role != User.Role.ADMIN
            and vehicle.status == Vehicle.Status.RETIRED
        ):
            messages.error(
                request, "Only an administrator can restore a retired vehicle."
            )
            return redirect("dashboard:vehicles")
        old_status = vehicle.status
        vehicle.status = form.cleaned_data["status"]
        vehicle.save(update_fields=["status", "updated_at"])
        if old_status != vehicle.status:
            record_audit(
                actor=request.user,
                action="vehicle.status_changed",
                obj=vehicle,
                changes={"status": {"from": old_status, "to": vehicle.status}},
            )
        messages.success(request, "Vehicle status updated.")
        return redirect("dashboard:vehicles")


class MaintenanceListView(AdminRequiredMixin, ListView):
    template_name = "dashboard/maintenance_list.html"
    context_object_name = "blocks"
    queryset = MaintenanceBlock.objects.select_related("vehicle")


class MaintenanceCreateView(AdminRequiredMixin, CreateView):
    form_class = MaintenanceBlockForm
    template_name = "dashboard/maintenance_form.html"
    success_url = reverse_lazy("dashboard:maintenance")


class ReservationListView(RoleRequiredMixin, ListView):
    allowed_roles = STAFF_ROLES
    template_name = "dashboard/reservation_list.html"
    context_object_name = "reservations"
    paginate_by = 25

    def get_queryset(self):
        self.filter_form = ReservationFilterForm(self.request.GET or None)
        self.filter_form.is_valid()
        queryset = Reservation.objects.select_related(
            "customer", "vehicle", "pickup_location", "return_location"
        )
        filters = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        if filters.get("status"):
            queryset = queryset.filter(status=filters["status"])
        if filters.get("vehicle"):
            queryset = queryset.filter(vehicle=filters["vehicle"])
        if filters.get("customer"):
            value = filters["customer"]
            queryset = queryset.filter(
                Q(customer__email__icontains=value)
                | Q(customer__first_name__icontains=value)
                | Q(customer__last_name__icontains=value)
            )
        if filters.get("start_date"):
            queryset = queryset.filter(pickup_datetime__date__gte=filters["start_date"])
        if filters.get("end_date"):
            queryset = queryset.filter(pickup_datetime__date__lte=filters["end_date"])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class ReservationDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = STAFF_ROLES
    model = Reservation
    template_name = "dashboard/reservation_detail.html"
    context_object_name = "reservation"
    pk_url_kwarg = "reservation_id"

    def get_queryset(self):
        return Reservation.objects.select_related(
            "customer", "vehicle", "pickup_location", "return_location"
        ).prefetch_related("payments")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pickup_form"] = PickupForm()
        context["return_form"] = ReturnForm()
        context["estimated_late_fee"] = calculate_late_fee(
            self.object,
            timezone.now(),
        )
        return context

    def post(self, request, reservation_id):
        self.object = get_object_or_404(self.get_queryset(), pk=reservation_id)
        action = request.POST.get("action")
        try:
            if action == "confirm":
                confirm_reservation(reservation=self.object, actor=request.user)
            elif action == "pickup":
                form = PickupForm(request.POST)
                if not form.is_valid():
                    raise ValidationError(form.errors.as_text())
                pick_up_reservation(
                    reservation=self.object,
                    actor=request.user,
                    odometer_km=form.cleaned_data["odometer_km"],
                    fuel_level=form.cleaned_data["fuel_level"],
                )
            elif action == "return":
                form = ReturnForm(request.POST)
                if not form.is_valid():
                    raise ValidationError(form.errors.as_text())
                returned = return_reservation(
                    reservation=self.object,
                    actor=request.user,
                    odometer_km=form.cleaned_data["odometer_km"],
                    fuel_level=form.cleaned_data["fuel_level"],
                    damage_notes=form.cleaned_data["damage_notes"],
                )
                messages.success(
                    request,
                    f"Rental returned. Late fee: ₹{returned.late_fee}.",
                )
                return redirect(
                    "dashboard:reservation_detail", reservation_id=self.object.pk
                )
            elif action == "cancel":
                staff_cancel_reservation(reservation=self.object, actor=request.user)
            else:
                raise ValidationError("Select a valid reservation action.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Reservation status updated.")
        return redirect("dashboard:reservation_detail", reservation_id=self.object.pk)


class CustomerListView(RoleRequiredMixin, ListView):
    allowed_roles = STAFF_ROLES
    template_name = "dashboard/customer_list.html"
    context_object_name = "customers"
    paginate_by = 25

    def get_queryset(self):
        self.search_form = CustomerSearchForm(self.request.GET or None)
        self.search_form.is_valid()
        queryset = (
            User.objects.filter(role=User.Role.CUSTOMER)
            .annotate(reservation_count=Count("reservations"))
            .order_by("email")
        )
        query = (
            self.search_form.cleaned_data.get("q", "")
            if self.search_form.is_valid()
            else ""
        )
        if query:
            queryset = queryset.filter(
                Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(phone__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_form"] = self.search_form
        return context


class CustomerDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = STAFF_ROLES
    model = User
    template_name = "dashboard/customer_detail.html"
    context_object_name = "customer"
    pk_url_kwarg = "customer_id"

    def get_queryset(self):
        return User.objects.filter(role=User.Role.CUSTOMER).prefetch_related(
            "reservations__vehicle", "reservations__payments"
        )


class CustomerActivationView(AdminRequiredMixin, View):
    def post(self, request, customer_id):
        active_value = request.POST.get("active")
        if active_value not in {"true", "false"}:
            messages.error(request, "Select a valid account action.")
            return redirect("dashboard:customer_detail", customer_id=customer_id)
        customer = get_object_or_404(
            User,
            pk=customer_id,
            role=User.Role.CUSTOMER,
        )
        old_value = customer.is_active
        customer.is_active = active_value == "true"
        customer.save(update_fields=["is_active"])
        if old_value != customer.is_active:
            record_audit(
                actor=request.user,
                action=(
                    "user.deactivated" if not customer.is_active else "user.reactivated"
                ),
                obj=customer,
                changes={"is_active": {"from": old_value, "to": customer.is_active}},
            )
        messages.success(request, "Customer access status updated.")
        return redirect("dashboard:customer_detail", customer_id=customer.pk)


class StaffListView(AdminRequiredMixin, ListView):
    template_name = "dashboard/staff_list.html"
    context_object_name = "staff_members"
    queryset = User.objects.filter(role=User.Role.STAFF).order_by("email")


class StaffCreateView(AdminRequiredMixin, CreateView):
    form_class = StaffCreateForm
    template_name = "dashboard/staff_form.html"
    success_url = reverse_lazy("dashboard:staff")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(
            actor=self.request.user,
            action="staff.created",
            obj=self.object,
            changes={"role": User.Role.STAFF, "is_active": self.object.is_active},
        )
        return response


class StaffDeactivateView(AdminRequiredMixin, View):
    def post(self, request, staff_id):
        staff_member = get_object_or_404(User, pk=staff_id, role=User.Role.STAFF)
        old_value = staff_member.is_active
        staff_member.is_active = False
        staff_member.save(update_fields=["is_active"])
        if old_value:
            record_audit(
                actor=request.user,
                action="user.deactivated",
                obj=staff_member,
                changes={"is_active": {"from": True, "to": False}},
            )
        messages.success(request, "Staff account deactivated.")
        return redirect("dashboard:staff")


class AuditLogListView(AdminRequiredMixin, ListView):
    template_name = "dashboard/audit_log.html"
    context_object_name = "audit_logs"
    paginate_by = 50
    queryset = AuditLog.objects.select_related("actor", "content_type")


class ReportsView(AdminRequiredMixin, TemplateView):
    template_name = "dashboard/reports.html"
    csv_reports = (
        ("revenue_daily", "daily revenue"),
        ("revenue_monthly", "monthly revenue"),
        ("utilization", "vehicle utilization"),
        ("top_vehicles", "top vehicles"),
        ("booking_status", "booking status"),
    )

    def _date_range(self):
        today = timezone.localdate()
        form = ReportsDateRangeForm(
            self.request.GET or None,
            initial={
                "start_date": today - timedelta(days=29),
                "end_date": today,
            },
        )
        if form.is_valid():
            return form, form.cleaned_data["start_date"], form.cleaned_data["end_date"]
        return (
            form,
            today - timedelta(days=29),
            today,
        )

    def get(self, request, *args, **kwargs):
        form, start_date, end_date = self._date_range()
        export = request.GET.get("export")
        if export:
            if not form.is_valid() and request.GET:
                return self.render_to_response(
                    self.get_context_data(
                        form=form, start_date=start_date, end_date=end_date
                    )
                )
            response = self._csv_response(export, start_date, end_date)
            if response is not None:
                return response
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form, start_date, end_date = self._date_range()
        start, end_exclusive = _date_bounds(start_date, end_date)
        context.update(
            form=kwargs.get("form", form),
            start_date=start_date,
            end_date=end_date,
            csv_reports=self.csv_reports,
        )

        paid_payments = Payment.objects.filter(
            status=Payment.Status.PAID,
            paid_at__gte=start,
            paid_at__lt=end_exclusive,
        )
        daily = (
            paid_payments.annotate(day=TruncDate("paid_at"))
            .values("day")
            .annotate(revenue=Sum("amount"))
            .order_by("day")
        )
        monthly = (
            paid_payments.annotate(month=TruncMonth("paid_at"))
            .values("month")
            .annotate(revenue=Sum("amount"))
            .order_by("month")
        )
        reservations = Reservation.objects.filter(
            pickup_datetime__lt=end_exclusive,
            return_datetime__gt=start,
            status__in=(
                Reservation.Status.CONFIRMED,
                Reservation.Status.ACTIVE,
                Reservation.Status.COMPLETED,
            ),
        ).select_related("vehicle")
        utilization_seconds = {}
        for reservation in reservations:
            window_start = max(reservation.pickup_datetime, start)
            window_end = min(reservation.return_datetime, end_exclusive)
            if reservation.status == Reservation.Status.ACTIVE:
                window_end = min(max(timezone.now(), window_start), window_end)
            utilization_seconds[reservation.vehicle_id] = utilization_seconds.get(
                reservation.vehicle_id, 0
            ) + max(0, int((window_end - window_start).total_seconds()))
        total_seconds = max(1, int((end_exclusive - start).total_seconds()))
        utilization = []
        for vehicle in Vehicle.objects.order_by("make", "model"):
            booked = utilization_seconds.get(vehicle.pk, 0)
            utilization.append(
                {
                    "vehicle": vehicle,
                    "booked_hours": round(booked / 3600, 2),
                    "utilization_pct": round(
                        min(100, booked / total_seconds * 100),
                        2,
                    ),
                }
            )

        top_vehicles = (
            reservations.values(
                "vehicle_id",
                "vehicle__make",
                "vehicle__model",
                "vehicle__registration_number",
            )
            .annotate(bookings=Count("pk", distinct=True))
            .order_by("-bookings", "vehicle__make", "vehicle__model")[:10]
        )
        status_breakdown = (
            Reservation.objects.filter(
                pickup_datetime__gte=start,
                pickup_datetime__lt=end_exclusive,
            )
            .values("status")
            .annotate(count=Count("pk"))
            .order_by("status")
        )
        context.update(
            daily_revenue=daily,
            monthly_revenue=monthly,
            utilization=utilization,
            top_vehicles=top_vehicles,
            status_breakdown=status_breakdown,
            daily_labels=[row["day"].isoformat() for row in daily],
            daily_values=[float(row["revenue"]) for row in daily],
            monthly_labels=[row["month"].strftime("%b %Y") for row in monthly],
            monthly_values=[float(row["revenue"]) for row in monthly],
        )
        return context

    def _csv_response(self, report, start_date, end_date):
        context = self.get_context_data(
            form=self._date_range()[0],
            start_date=start_date,
            end_date=end_date,
        )
        reports = {
            "revenue_daily": (
                ["date", "revenue"],
                (
                    (row["day"], f'{row["revenue"]:.2f}')
                    for row in context["daily_revenue"]
                ),
            ),
            "revenue_monthly": (
                ["month", "revenue"],
                (
                    (row["month"], f'{row["revenue"]:.2f}')
                    for row in context["monthly_revenue"]
                ),
            ),
            "utilization": (
                ["registration", "vehicle", "booked_hours", "utilization_percent"],
                (
                    (
                        item["vehicle"].registration_number,
                        str(item["vehicle"]),
                        item["booked_hours"],
                        item["utilization_pct"],
                    )
                    for item in context["utilization"]
                ),
            ),
            "top_vehicles": (
                ["registration", "make", "model", "bookings"],
                (
                    (
                        item["vehicle__registration_number"],
                        item["vehicle__make"],
                        item["vehicle__model"],
                        item["bookings"],
                    )
                    for item in context["top_vehicles"]
                ),
            ),
            "booking_status": (
                ["status", "count"],
                (
                    (item["status"], item["count"])
                    for item in context["status_breakdown"]
                ),
            ),
        }
        selected = reports.get(report)
        if selected is None:
            return None
        filename = f"{report}_{start_date}_{end_date}.csv"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(selected[0])
        writer.writerows(selected[1])
        return response


class PricingSettingsView(AdminRequiredMixin, TemplateView):
    template_name = "dashboard/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault(
            "form", PricingSettingsForm(instance=PricingSettings.get_solo())
        )
        return context

    def post(self, request, *args, **kwargs):
        settings_obj = PricingSettings.get_solo()
        before = {
            field: str(getattr(settings_obj, field))
            for field in PricingSettingsForm.Meta.fields
        }
        form = PricingSettingsForm(request.POST, instance=settings_obj)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        updated = form.save()
        changes = {
            field: {"from": before[field], "to": str(getattr(updated, field))}
            for field in PricingSettingsForm.Meta.fields
            if before[field] != str(getattr(updated, field))
        }
        if changes:
            record_audit(
                actor=request.user,
                action="pricing_settings.updated",
                obj=updated,
                changes=changes,
            )
        messages.success(request, "Pricing and rental policies were saved.")
        return redirect("dashboard:settings")


def _date_bounds(start_date: date, end_date: date):
    start_naive = datetime.combine(start_date, time.min)
    end_naive = datetime.combine(end_date + timedelta(days=1), time.min)
    return (
        timezone.make_aware(start_naive),
        timezone.make_aware(end_naive),
    )
