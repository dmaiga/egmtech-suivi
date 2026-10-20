from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy

from .models import User


def _default_url_for(user):
    if user.is_client():
        return reverse("portal:dashboard")
    return reverse("visits:mission-list")


class RoleAwareLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        return _default_url_for(self.request.user)


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect(_default_url_for(request.user))
    return redirect("accounts:login")


def app_home(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return redirect(_default_url_for(request.user))
