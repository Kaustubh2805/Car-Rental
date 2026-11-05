"""Reusable role-based access controls."""

from collections.abc import Sequence
from functools import wraps
from typing import Any, Callable

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse


class RoleRequiredMixin(AccessMixin):
    """Allow a view only to authenticated users with an allowed role."""

    allowed_roles: Sequence[str] = ()

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def role_required(allowed_roles: Sequence[str]) -> Callable:
    """Restrict a function view to authenticated users with an allowed role."""

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if request.user.role not in allowed_roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
