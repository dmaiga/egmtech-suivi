from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy

from .models import User


class RoleAwareLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        user = self.request.user
        if user.role == User.Role.CLIENT:
            return "/portail/"
        return "/app/"


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")
