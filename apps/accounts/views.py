"""Class-based views for customer account flows."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy
from django.views.generic import FormView, UpdateView

from apps.accounts.forms import EmailAuthenticationForm, ProfileForm, RegistrationForm
from apps.accounts.models import LoginAttempt
from apps.core.mixins import RoleRequiredMixin

User = get_user_model()


class RegistrationView(FormView):
    """Register a new customer account."""

    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("accounts:login")

    def form_valid(self, form):
        form.save()
        next_url = self.request.GET.get("next") or self.request.POST.get("next")
        messages.success(
            self.request,
            "Your account has been created. You can now sign in.",
        )
        if next_url:
            return self.get_success_url_with_next(next_url)
        return super().form_valid(form)

    def get_success_url_with_next(self, next_url: str):
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(
            next_url,
            login_url=reverse_lazy("accounts:login"),
        )


class AccountLoginView(LoginView):
    """Sign in with email and apply the configured failed-login lockout."""

    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        LoginAttempt.objects.filter(email=form.normalized_email).delete()
        return super().form_valid(form)


class AccountLogoutView(LogoutView):
    """Sign out the current session."""

    next_page = reverse_lazy("home")


class CustomerProfileView(RoleRequiredMixin, UpdateView):
    """Display and edit the signed-in customer's account profile."""

    allowed_roles = [User.Role.CUSTOMER]
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile"] = self.request.user.customer_profile
        return context

    def form_valid(self, form):
        messages.success(self.request, "Your profile has been updated.")
        return super().form_valid(form)


class AccountPasswordResetView(PasswordResetView):
    """Email a password-reset link to a registered user."""

    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    html_email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class AccountPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class AccountPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
