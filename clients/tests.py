from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Client, Site
from .services import visible_clients, visible_sites

User = get_user_model()


def _make_user(username, role, client=None, is_superuser=False):
    user = User.objects.create_user(username=username, password="pass12345")
    user.role = role
    user.client = client
    user.is_superuser = is_superuser
    user.is_staff = is_superuser
    user.save()
    return user


class UserClientConstraintTests(TestCase):
    def test_client_role_without_client_fails_validation(self):
        user = User(username="orphan", role=User.Role.CLIENT)
        user.set_password("pass12345")
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_client_role_without_client_fails_db_constraint(self):
        user = User(username="orphan2", role=User.Role.CLIENT)
        user.set_password("pass12345")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user.save()

    def test_manager_without_client_is_valid(self):
        user = User(username="manager_ok", role=User.Role.MANAGER)
        user.set_password("pass12345")
        user.full_clean()
        user.save()


class VisibleClientsServiceTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.client_b = Client.objects.create(nom="Client B")
        self.site_a = Site.objects.create(client=self.client_a, code="S1", nom="Site A1")
        self.site_b = Site.objects.create(client=self.client_b, code="S1", nom="Site B1")
        self.manager = _make_user("manager1", User.Role.MANAGER)
        self.client_user_a = _make_user("clientA", User.Role.CLIENT, client=self.client_a)

    def test_manager_sees_all_clients(self):
        self.assertCountEqual(visible_clients(self.manager), [self.client_a, self.client_b])

    def test_client_user_sees_only_own_client(self):
        self.assertCountEqual(visible_clients(self.client_user_a), [self.client_a])

    def test_client_user_sees_only_own_sites(self):
        self.assertCountEqual(visible_sites(self.client_user_a), [self.site_a])

    def test_client_user_never_sees_other_client(self):
        self.assertNotIn(self.client_b, visible_clients(self.client_user_a))
        self.assertNotIn(self.site_b, visible_sites(self.client_user_a))


class ManagerScreensAccessTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.manager = _make_user("manager2", User.Role.MANAGER)
        self.client_user = _make_user("clientB", User.Role.CLIENT, client=self.client_a)

    def test_client_role_cannot_list_clients(self):
        self.client.login(username="clientB", password="pass12345")
        response = self.client.get(reverse("clients:list"))
        self.assertEqual(response.status_code, 403)

    def test_client_role_cannot_view_client_detail(self):
        self.client.login(username="clientB", password="pass12345")
        response = self.client.get(reverse("clients:detail", args=[self.client_a.pk]))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_list_clients(self):
        self.client.login(username="manager2", password="pass12345")
        response = self.client.get(reverse("clients:list"))
        self.assertEqual(response.status_code, 200)

    def test_manager_can_create_client(self):
        self.client.login(username="manager2", password="pass12345")
        response = self.client.post(reverse("clients:create"), {"nom": "Nouveau client", "actif": "on"})
        self.assertEqual(Client.objects.filter(nom="Nouveau client").count(), 1)
        self.assertEqual(response.status_code, 302)


class SiteCreationTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.manager = _make_user("manager3", User.Role.MANAGER)
        self.client.login(username="manager3", password="pass12345")

    def test_htmx_site_create_adds_site_to_client(self):
        response = self.client.post(
            reverse("clients:site-create", args=[self.client_a.pk]),
            {
                "code": "S1",
                "nom": "Site 1",
                "ville": "Bamako",
                "quartier": "",
                "latitude": "",
                "longitude": "",
                "responsable_local": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Site.objects.filter(client=self.client_a, code="S1").exists())

    def test_site_create_invalid_returns_400_without_creating(self):
        response = self.client.post(
            reverse("clients:site-create", args=[self.client_a.pk]),
            {"code": "", "nom": "", "ville": "", "quartier": "", "latitude": "", "longitude": "", "responsable_local": ""},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Site.objects.count(), 0)


class ClientUserAccountTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.manager = _make_user("manager4", User.Role.MANAGER)
        self.client.login(username="manager4", password="pass12345")

    def test_manager_creates_client_user(self):
        response = self.client.post(
            reverse("clients:user-create", args=[self.client_a.pk]),
            {
                "username": "nouveau_client",
                "email": "",
                "password1": "UnMotDePasse123!",
                "password2": "UnMotDePasse123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="nouveau_client")
        self.assertEqual(created.role, User.Role.CLIENT)
        self.assertEqual(created.client, self.client_a)

    def test_revoke_disables_account_and_logs(self):
        from core.models import ActivityLog

        target = _make_user("client_to_revoke", User.Role.CLIENT, client=self.client_a)
        response = self.client.post(reverse("clients:user-revoke", args=[self.client_a.pk, target.pk]))

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertTrue(ActivityLog.objects.filter(action="revocation_compte", object_id=str(target.pk)).exists())

    def test_revoked_user_cannot_login(self):
        target = _make_user("client_revoked2", User.Role.CLIENT, client=self.client_a)
        self.client.post(reverse("clients:user-revoke", args=[self.client_a.pk, target.pk]))

        logged_out_client = self.client_class()
        can_login = logged_out_client.login(username="client_revoked2", password="pass12345")
        self.assertFalse(can_login)
