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
        self.assertCountEqual(visible_clients(self.manager), Client.objects.all())
        self.assertIn(self.client_a, visible_clients(self.manager))
        self.assertIn(self.client_b, visible_clients(self.manager))

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
        self.assertEqual(response.headers["HX-Redirect"], reverse("clients:detail", args=[self.client_a.pk]))

    def test_duplicate_site_code_shows_a_form_error(self):
        Site.objects.create(client=self.client_a, code="S1", nom="Site existant")
        response = self.client.post(reverse("clients:site-create", args=[self.client_a.pk]),
                                    {"code": "S1", "nom": "Autre site", "ville": "Bamako"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Ce code est déjà utilisé", status_code=400)
        self.assertEqual(Site.objects.filter(client=self.client_a, code="S1").count(), 1)

    def test_site_create_without_htmx_redirects_to_client(self):
        response = self.client.post(reverse("clients:site-create", args=[self.client_a.pk]), {"nom": "Site 2", "ville": "Bamako"})
        self.assertRedirects(response, reverse("clients:detail", args=[self.client_a.pk]))

    def test_site_create_invalid_returns_400_without_creating(self):
        response = self.client.post(
            reverse("clients:site-create", args=[self.client_a.pk]),
            {"code": "", "nom": "", "ville": "", "quartier": "", "latitude": "", "longitude": "", "responsable_local": ""},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Site.objects.count(), 0)

    def test_site_requires_city_and_preserves_name(self):
        response = self.client.post(reverse("clients:site-create", args=[self.client_a.pk]),
                                    {"nom": "Agence centrale", "ville": ""}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Agence centrale", status_code=400)
        self.assertTrue(response.context["site_form"].errors.get("ville"))

    def test_client_page_provides_add_dialogs(self):
        response = self.client.get(reverse("clients:detail", args=[self.client_a.pk]))
        self.assertContains(response, 'id="site-dialog"')
        self.assertContains(response, 'id="account-dialog"')
        self.assertLess(response.content.index(b'id="id_nom"'), response.content.index(b'id="id_ville"'))


class ClientUserAccountTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.manager = _make_user("manager4", User.Role.MANAGER)
        self.client.login(username="manager4", password="pass12345")

    def test_manager_creates_client_user(self):
        response = self.client.post(
            reverse("clients:user-create", args=[self.client_a.pk]),
            {
                "first_name": "Awa", "last_name": "Diallo", "poste": "Directrice",
                "email": "awa@example.com",
                "password1": "UnMotDePasse123!",
                "password2": "UnMotDePasse123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(email="awa@example.com")
        self.assertEqual(created.role, User.Role.CLIENT)
        self.assertEqual(created.client, self.client_a)
        self.assertTrue(self.client_class().login(username="awa@example.com", password="UnMotDePasse123!"))

    def test_create_client_with_access_and_duplicate_email_is_atomic(self):
        payload = {"nom": "Nouvelle banque", "actif": "on", "create_account": "on",
                   "account-first_name": "Awa", "account-last_name": "Diallo", "account-email": "awa@example.com",
                   "account-poste": "Direction", "account-password1": "UnMotDePasse123!", "account-password2": "UnMotDePasse123!"}
        response = self.client.post(reverse("clients:create"), payload)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="awa@example.com")
        self.assertEqual(user.client.nom, "Nouvelle banque")
        self.assertTrue(self.client_class().login(username="AWA@example.com", password="UnMotDePasse123!"))
        payload["nom"] = "Autre banque"
        response = self.client.post(reverse("clients:create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Client.objects.filter(nom="Autre banque").exists())

    def test_multiple_sites_can_have_no_code(self):
        url = reverse("clients:site-create", args=[self.client_a.pk])
        for name in ["Agence A", "Agence B"]:
            response = self.client.post(url, {"nom": name, "code": "", "ville": "Bamako"}, HTTP_HX_REQUEST="true")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Site.objects.filter(client=self.client_a, code__isnull=True).count(), 2)

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


class ClientListViewTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(nom="Client A")
        self.site_a = Site.objects.create(client=self.client_a, code="S1", nom="Site 1")
        self.manager = _make_user("manager_cl", User.Role.MANAGER)
        self.sup = _make_user("sup_cl", User.Role.SUPERVISEUR)
        self.client_user = _make_user("client_cl", User.Role.CLIENT, client=self.client_a)

    def test_manager_sees_clients_with_progress_summary(self):
        self.client.login(username="manager_cl", password="pass12345")
        response = self.client.get(reverse("clients:list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("total_prevu", response.context)
        self.assertIn("total_fait", response.context)
        self.assertIn("total_sites", response.context)
        self.assertIn("pourcentage_avancement", response.context)
        self.assertContains(response, "Client A")

    def test_superviseur_cannot_access_client_list(self):
        self.client.login(username="sup_cl", password="pass12345")
        response = self.client.get(reverse("clients:list"))
        self.assertEqual(response.status_code, 403)

    def test_client_cannot_access_client_list(self):
        self.client.login(username="client_cl", password="pass12345")
        response = self.client.get(reverse("clients:list"))
        self.assertEqual(response.status_code, 403)
