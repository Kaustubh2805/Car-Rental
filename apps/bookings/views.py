"""Views and JSON endpoints for the reservation flow."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, ListView, TemplateView
from django.views.generic.detail import DetailView

from apps.accounts.models import CustomerProfile, User
from apps.bookings.forms import BookingRequestForm, DateRangeForm
from apps.bookings.models import Reservation
from apps.bookings.services.availability import (
    BLOCKING_STATUSES,
    is_vehicle_available,
)
from apps.bookings.services.booking import (
    MODIFICATION_CUTOFF_HOURS,
    cancel_reservation,
    create_payment,
    create_reservation,
    modify_reservation,
)
from apps.bookings.services.pricing import (
    calculate_cancellation_fee,
    calculate_quote,
)
from apps.core.models import PricingSettings
from apps.core.mixins import RoleRequiredMixin
from apps.vehicles.models import Vehicle


def _json_quote(vehicle, pickup, return_at):
    quote = calculate_quote(vehicle, pickup, return_at)
    return quote.as_dict()


class AvailabilityAPIView(View):
    """Return one vehicle's availability and current quote."""

    def get(self, request):
        vehicle = get_object_or_404(
            Vehicle.objects.select_related("category"),
            pk=request.GET.get("vehicle_id"),
        )
        form = DateRangeForm(request.GET)
        if not form.is_valid():
            return JsonResponse(
                {"available": False, "errors": form.errors.get_json_data()},
                status=400,
            )
        pickup = form.cleaned_data["pickup_datetime"]
        return_at = form.cleaned_data["return_datetime"]
        if pickup <= timezone.now():
            return JsonResponse(
                {"available": False, "error": "Pickup must be in the future."},
                status=400,
            )
        available = is_vehicle_available(vehicle, pickup, return_at)
        response = {"available": available, "quote": None}
        if available:
            response["quote"] = _json_quote(vehicle, pickup, return_at)
        return JsonResponse(response)


class VehicleBookedDatesAPIView(View):
    """Return blocking reservation and maintenance intervals for a vehicle."""

    def get(self, request, vehicle_id: int):
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
        reservations = (
            vehicle.reservations.filter(status__in=BLOCKING_STATUSES)
            .order_by("pickup_datetime")
            .values("pickup_datetime", "return_datetime")
        )
        maintenance = vehicle.maintenance_blocks.order_by("start_datetime").values(
            "start_datetime", "end_datetime"
        )
        return JsonResponse(
            {
                "buffer_hours": PricingSettings.get_solo().booking_buffer_hours,
                "reservations": [
                    {
                        "start": item["pickup_datetime"].isoformat(),
                        "end": item["return_datetime"].isoformat(),
                    }
                    for item in reservations
                ],
                "maintenance": [
                    {
                        "start": item["start_datetime"].isoformat(),
                        "end": item["end_datetime"].isoformat(),
                    }
                    for item in maintenance
                ],
            }
        )


class BookingStartView(RoleRequiredMixin, FormView):
    """Validate a booking request and save it for the review step."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "bookings/booking_form.html"
    form_class = BookingRequestForm

    def dispatch(self, request, *args, **kwargs):
        self.vehicle = get_object_or_404(
            Vehicle.objects.select_related("category", "location").prefetch_related(
                "images"
            ),
            pk=kwargs["vehicle_id"],
            status=Vehicle.Status.AVAILABLE,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial["pickup_location"] = self.vehicle.location_id
        initial["return_location"] = self.vehicle.location_id
        initial.update(self.request.GET.dict())
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vehicle"] = self.vehicle
        context["availability_url"] = reverse("availability_api")
        context["booked_dates_url"] = reverse(
            "vehicle_booked_dates_api",
            kwargs={"vehicle_id": self.vehicle.pk},
        )
        return context

    def form_valid(self, form):
        pickup = form.cleaned_data["pickup_datetime"]
        return_at = form.cleaned_data["return_datetime"]
        if pickup <= timezone.now():
            form.add_error("pickup_datetime", "Pickup must be in the future.")
            return self.form_invalid(form)
        if return_at <= pickup:
            form.add_error("return_datetime", "Return must be after pickup.")
            return self.form_invalid(form)
        if not is_vehicle_available(self.vehicle, pickup, return_at):
            form.add_error(
                None,
                "This vehicle is not available for the selected dates.",
            )
            return self.form_invalid(form)
        try:
            profile = self.request.user.customer_profile
        except CustomerProfile.DoesNotExist:
            form.add_error(
                None,
                "Complete a valid driving licence in your profile before booking.",
            )
            return self.form_invalid(form)
        if (
            not profile.licence_expiry
            or profile.licence_expiry < timezone.localtime(return_at).date()
        ):
            form.add_error(
                None,
                "Your driving licence must be valid through the return date.",
            )
            return self.form_invalid(form)

        self.request.session["booking_draft"] = {
            "user_id": self.request.user.pk,
            "vehicle_id": self.vehicle.pk,
            "pickup_location_id": form.cleaned_data["pickup_location"].pk,
            "return_location_id": form.cleaned_data["return_location"].pk,
            "pickup_datetime": pickup.isoformat(),
            "return_datetime": return_at.isoformat(),
            "notes": form.cleaned_data["notes"],
        }
        return redirect("bookings:review")


class BookingReviewView(RoleRequiredMixin, TemplateView):
    """Show the quote and create the reservation after confirmation."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "bookings/booking_review.html"

    def _draft_form(self):
        draft = self.request.session.get("booking_draft")
        if not draft or draft.get("user_id") != self.request.user.pk:
            return None
        data = {
            "pickup_datetime": draft["pickup_datetime"],
            "return_datetime": draft["return_datetime"],
            "pickup_location": draft["pickup_location_id"],
            "return_location": draft["return_location_id"],
            "notes": draft.get("notes", ""),
        }
        form = BookingRequestForm(data)
        return form if form.is_valid() else None

    def get(self, request, *args, **kwargs):
        form = self._draft_form()
        if form is None:
            messages.error(request, "Please start your booking again.")
            return redirect("vehicles:list")
        vehicle = get_object_or_404(
            Vehicle.objects.select_related("category", "location"),
            pk=request.session["booking_draft"]["vehicle_id"],
        )
        if not is_vehicle_available(
            vehicle,
            form.cleaned_data["pickup_datetime"],
            form.cleaned_data["return_datetime"],
        ):
            messages.error(request, "This vehicle is no longer available.")
            return redirect("vehicles:detail", pk=vehicle.pk)
        return self.render_to_response(
            self.get_context_data(
                vehicle=vehicle,
                form=form,
                quote=calculate_quote(
                    vehicle,
                    form.cleaned_data["pickup_datetime"],
                    form.cleaned_data["return_datetime"],
                ),
            )
        )

    def post(self, request, *args, **kwargs):
        form = self._draft_form()
        if form is None:
            messages.error(request, "Please start your booking again.")
            return redirect("vehicles:list")
        draft = request.session["booking_draft"]
        try:
            reservation = create_reservation(
                customer=request.user,
                vehicle=draft["vehicle_id"],
                pickup_location=draft["pickup_location_id"],
                return_location=draft["return_location_id"],
                pickup_datetime=form.cleaned_data["pickup_datetime"],
                return_datetime=form.cleaned_data["return_datetime"],
                notes=draft.get("notes", ""),
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("vehicles:detail", pk=draft["vehicle_id"])
        request.session.pop("booking_draft", None)
        return redirect("bookings:payment", reservation_id=reservation.pk)


class BookingModifyView(RoleRequiredMixin, FormView):
    """Edit a customer's pending or confirmed booking dates."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "bookings/booking_modify.html"
    form_class = BookingRequestForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        self.reservation = get_object_or_404(
            Reservation.objects.select_related(
                "vehicle",
                "pickup_location",
                "return_location",
            ),
            pk=kwargs["reservation_id"],
            customer=request.user,
            status__in=(Reservation.Status.PENDING, Reservation.Status.CONFIRMED),
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial.update(
            pickup_datetime=self.reservation.pickup_datetime,
            return_datetime=self.reservation.return_datetime,
            pickup_location=self.reservation.pickup_location_id,
            return_location=self.reservation.return_location_id,
            notes=self.reservation.notes,
        )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["reservation"] = self.reservation
        context["modification_cutoff_hours"] = MODIFICATION_CUTOFF_HOURS
        return context

    def form_valid(self, form):
        try:
            reservation = modify_reservation(
                reservation=self.reservation,
                customer=self.request.user,
                pickup_datetime=form.cleaned_data["pickup_datetime"],
                return_datetime=form.cleaned_data["return_datetime"],
                pickup_location=form.cleaned_data["pickup_location"],
                return_location=form.cleaned_data["return_location"],
                notes=form.cleaned_data["notes"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Your reservation has been updated.")
        return redirect("bookings:confirmation", reservation_id=reservation.pk)


class BookingPaymentView(RoleRequiredMixin, TemplateView):
    """Record a mock-card or pay-at-pickup selection."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "bookings/payment.html"

    def _get_reservation(self):
        return get_object_or_404(
            Reservation.objects.select_related("vehicle", "customer"),
            pk=self.kwargs["reservation_id"],
            customer=self.request.user,
        )

    def get(self, request, *args, **kwargs):
        self.reservation = self._get_reservation()
        if self.reservation.status not in (
            Reservation.Status.PENDING,
            Reservation.Status.CONFIRMED,
        ):
            return redirect(
                "bookings:confirmation",
                reservation_id=self.reservation.pk,
            )
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        reservation = self._get_reservation()
        method = request.POST.get("method")
        try:
            create_payment(reservation, method)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("bookings:payment", reservation_id=reservation.pk)
        return redirect(
            "bookings:confirmation",
            reservation_id=reservation.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self, "reservation"):
            self.reservation = self._get_reservation()
        context["reservation"] = self.reservation
        return context


class BookingConfirmationView(RoleRequiredMixin, DetailView):
    """Show a customer's booking reference and payment summary."""

    allowed_roles = [User.Role.CUSTOMER]
    model = Reservation
    template_name = "bookings/confirmation.html"
    context_object_name = "reservation"
    pk_url_kwarg = "reservation_id"

    def get_queryset(self):
        return (
            Reservation.objects.filter(customer=self.request.user)
            .select_related("vehicle", "pickup_location", "return_location")
            .prefetch_related("payments")
        )


class MyBookingsView(RoleRequiredMixin, ListView):
    """List the signed-in customer's reservations by lifecycle tab."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "bookings/my_bookings.html"
    context_object_name = "reservations"
    paginate_by = 10
    tab_statuses = {
        "upcoming": (Reservation.Status.PENDING, Reservation.Status.CONFIRMED),
        "active": (Reservation.Status.ACTIVE,),
        "completed": (Reservation.Status.COMPLETED,),
        "cancelled": (Reservation.Status.CANCELLED,),
    }

    def get_tab(self):
        tab = self.request.GET.get("tab", "upcoming")
        return tab if tab in self.tab_statuses else "upcoming"

    def get_queryset(self):
        return (
            Reservation.objects.filter(
                customer=self.request.user,
                status__in=self.tab_statuses[self.get_tab()],
            )
            .select_related("vehicle", "pickup_location", "return_location")
            .prefetch_related("payments")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.get_tab()
        context["tabs"] = tuple(self.tab_statuses)
        return context


class BookingDetailView(RoleRequiredMixin, DetailView):
    """Show a reservation only to its owning customer."""

    allowed_roles = [User.Role.CUSTOMER]
    model = Reservation
    template_name = "bookings/booking_detail.html"
    context_object_name = "reservation"
    pk_url_kwarg = "reservation_id"

    def get_queryset(self):
        return (
            Reservation.objects.filter(customer=self.request.user)
            .select_related("vehicle", "pickup_location", "return_location")
            .prefetch_related("payments")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reservation = self.object
        settings = PricingSettings.get_solo()
        context["pricing_settings"] = settings
        context["cancellation_fee_quote"] = calculate_cancellation_fee(reservation)
        context["cancellation_free_hours"] = settings.cancellation_free_hours
        context["cancellation_fee_pct"] = settings.cancellation_fee_pct
        context["can_manage"] = (
            reservation.status
            in (Reservation.Status.PENDING, Reservation.Status.CONFIRMED)
            and reservation.pickup_datetime > timezone.now()
        )
        context["can_modify"] = context[
            "can_manage"
        ] and reservation.pickup_datetime - timezone.now() > timedelta(
            hours=MODIFICATION_CUTOFF_HOURS
        )
        context["can_cancel"] = (
            context["can_manage"] and reservation.actual_pickup_at is None
        )
        context["modification_cutoff_hours"] = MODIFICATION_CUTOFF_HOURS
        return context


class BookingReceiptView(BookingDetailView):
    """Render a printer-friendly invoice for the owning customer."""

    template_name = "bookings/booking_receipt.html"


class BookingCancelView(RoleRequiredMixin, View):
    """Cancel the signed-in customer's pending or confirmed booking."""

    allowed_roles = [User.Role.CUSTOMER]

    def post(self, request, reservation_id):
        reservation = get_object_or_404(
            Reservation,
            pk=reservation_id,
            customer=request.user,
        )
        try:
            cancel_reservation(reservation=reservation, customer=request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Your reservation has been cancelled.")
        return redirect("bookings:detail", reservation_id=reservation.pk)
