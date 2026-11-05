"""Views shared by the project."""

from django.views.generic import TemplateView

from apps.bookings.forms import DateRangeForm
from apps.vehicles.models import Vehicle


class HomeView(TemplateView):
    """Display the public home page."""

    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["date_range_form"] = DateRangeForm()
        context["featured_vehicles"] = (
            Vehicle.objects.filter(status=Vehicle.Status.AVAILABLE)
            .select_related("category", "location")
            .prefetch_related("images")
            .order_by("-created_at", "-pk")[:3]
        )
        return context
