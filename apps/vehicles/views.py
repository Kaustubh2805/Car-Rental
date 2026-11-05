"""Public views for browsing vehicles."""

from django.views.generic import DetailView, ListView

from apps.bookings.services.availability import search_available_vehicles
from apps.vehicles.forms import VehicleFilterForm
from apps.vehicles.models import Vehicle


class VehicleListView(ListView):
    """Display available vehicles with validated search filters."""

    template_name = "vehicles/vehicle_list.html"
    context_object_name = "vehicles"
    paginate_by = 12

    def get_filter_form(self) -> VehicleFilterForm:
        if not hasattr(self, "_filter_form"):
            self._filter_form = VehicleFilterForm(self.request.GET or None)
            self._filter_form.is_valid()
        return self._filter_form

    def get_queryset(self):
        queryset = (
            Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE)
            .select_related("category", "location")
            .prefetch_related("features", "images")
        )
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset.order_by("-created_at", "-pk")

        filters = form.cleaned_data
        if filters.get("category"):
            queryset = queryset.filter(category=filters["category"])
        if filters.get("transmission"):
            queryset = queryset.filter(transmission=filters["transmission"])
        if filters.get("fuel_type"):
            queryset = queryset.filter(fuel_type=filters["fuel_type"])
        if filters.get("seats"):
            queryset = queryset.filter(seats__gte=filters["seats"])
        if filters.get("min_price") is not None:
            queryset = queryset.filter(daily_price__gte=filters["min_price"])
        if filters.get("max_price") is not None:
            queryset = queryset.filter(daily_price__lte=filters["max_price"])
        if filters.get("location"):
            queryset = queryset.filter(location=filters["location"])
        if filters.get("vehicle"):
            queryset = queryset.filter(pk=filters["vehicle"].pk)
        if filters.get("pickup_datetime") and filters.get("return_datetime"):
            queryset = search_available_vehicles(
                filters["pickup_datetime"],
                filters["return_datetime"],
                queryset=queryset,
            )

        sort = filters.get("sort")
        if sort == "price_asc":
            return queryset.order_by("daily_price", "pk")
        if sort == "price_desc":
            return queryset.order_by("-daily_price", "pk")
        return queryset.order_by("-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context["query_string"] = query_params.urlencode()
        return context


class VehicleDetailView(DetailView):
    """Display a vehicle detail page and ordered image gallery."""

    template_name = "vehicles/vehicle_detail.html"
    context_object_name = "vehicle"

    def get_queryset(self):
        return (
            Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE)
            .select_related("category", "location")
            .prefetch_related("features", "images")
        )
