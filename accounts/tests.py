from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views import View

from .decorators import role_required
from .mixins import RoleRequiredMixin
from .models import User

UserModel = get_user_model()


def _make_user(username, role, is_superuser=False):
    user = UserModel.objects.create_user(username=username, password="pass12345")
    user.role = role
    user.is_superuser = is_superuser
    user.is_staff = is_superuser
    if role == User.Role.CLIENT:
        from clients.models import Client

        user.client = Client.objects.create(nom=f"Client de {username}")
    user.save()
    return user


class LoginRedirectTests(TestCase):
    def test_manager_redirected_to_app(self):
        _make_user("manager1", User.Role.MANAGER)
        response = self.client.post(
            reverse("accounts:login"), {"username": "manager1", "password": "pass12345"}
        )
        self.assertRedirects(response, reverse("visits:mission-list"))

    def test_superviseur_redirected_to_app(self):
        _make_user("sup1", User.Role.SUPERVISEUR)
        response = self.client.post(
            reverse("accounts:login"), {"username": "sup1", "password": "pass12345"}
        )
        self.assertRedirects(response, reverse("visits:mission-list"))

    def test_client_redirected_to_portail(self):
        _make_user("client1", User.Role.CLIENT)
        response = self.client.post(
            reverse("accounts:login"), {"username": "client1", "password": "pass12345"}
        )
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_superuser_without_role_redirected_to_app(self):
        UserModel.objects.create_superuser(username="admin1", password="pass12345", email="")
        response = self.client.post(
            reverse("accounts:login"), {"username": "admin1", "password": "pass12345"}
        )
        self.assertRedirects(response, reverse("visits:mission-list"))

    def test_logout_redirects_to_login(self):
        _make_user("manager2", User.Role.MANAGER)
        self.client.login(username="manager2", password="pass12345")
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))


@role_required(User.Role.MANAGER)
def manager_only_view(request):
    return HttpResponse("ok")


class ManagerOnlyView(RoleRequiredMixin, View):
    allowed_roles = (User.Role.MANAGER,)

    def get(self, request):
        return HttpResponse("ok")


class RoleRequiredDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_is_redirected_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/fake/")
        request.user = AnonymousUser()
        response = manager_only_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/comptes/connexion/", response.url)

    def test_wrong_role_raises_permission_denied(self):
        user = _make_user("sup2", User.Role.SUPERVISEUR)
        request = self.factory.get("/fake/")
        request.user = user
        with self.assertRaises(PermissionDenied):
            manager_only_view(request)

    def test_correct_role_is_allowed(self):
        user = _make_user("manager3", User.Role.MANAGER)
        request = self.factory.get("/fake/")
        request.user = user
        response = manager_only_view(request)
        self.assertEqual(response.status_code, 200)

    def test_superuser_bypasses_role_check(self):
        user = _make_user("admin2", User.Role.CLIENT, is_superuser=True)
        request = self.factory.get("/fake/")
        request.user = user
        response = manager_only_view(request)
        self.assertEqual(response.status_code, 200)


class RoleRequiredMixinTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = ManagerOnlyView.as_view()

    def test_anonymous_is_redirected_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/fake/")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 302)

    def test_wrong_role_raises_permission_denied(self):
        user = _make_user("client2", User.Role.CLIENT)
        request = self.factory.get("/fake/")
        request.user = user
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_correct_role_is_allowed(self):
        user = _make_user("manager4", User.Role.MANAGER)
        request = self.factory.get("/fake/")
        request.user = user
        response = self.view(request)
        self.assertEqual(response.status_code, 200)


@override_settings(ROOT_URLCONF="accounts.urls_fixtures")
class ForbiddenPageTests(TestCase):
    def test_permission_denied_renders_custom_403(self):
        _make_user("client3", User.Role.CLIENT)
        self.client.login(username="client3", password="pass12345")

        response = self.client.get("/fake-manager-only/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Accès refusé", status_code=403)


class AppHomeTests(TestCase):
    def test_manager_sees_dashboard_and_stats(self):
        manager = _make_user("mgr_home", User.Role.MANAGER)
        self.client.login(username="mgr_home", password="pass12345")

        response = self.client.get(reverse("app-home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de bord")
        self.assertIn("visites_a_revoir", response.context)
        self.assertIn("visites_a_corriger", response.context)
        self.assertIn("missions_en_cours", response.context)
        self.assertIn("visites_publiees_mois", response.context)
        self.assertIn("dernieres_soumises", response.context)

    def test_superviseur_redirected_from_app_home_to_missions(self):
        _make_user("sup_home", User.Role.SUPERVISEUR)
        self.client.login(username="sup_home", password="pass12345")

        response = self.client.get(reverse("app-home"))
        self.assertRedirects(response, reverse("visits:mission-list"))

    def test_client_redirected_from_app_home_to_portal(self):
        _make_user("cli_home", User.Role.CLIENT)
        self.client.login(username="cli_home", password="pass12345")

        response = self.client.get(reverse("app-home"))
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("app-home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
