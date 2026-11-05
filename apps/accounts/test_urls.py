"""Temporary routes for account access-control tests."""

from django.http import HttpResponse
from django.urls import path
from django.views import View

from apps.accounts.models import User
from apps.core.mixins import RoleRequiredMixin


class StaffOnlyTestView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STAFF, User.Role.ADMIN]

    def get(self, request):
        return HttpResponse("staff-only")


urlpatterns = [
    path("staff-only/", StaffOnlyTestView.as_view(), name="staff_only_test"),
]
