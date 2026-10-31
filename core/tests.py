from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.messages import get_messages
from django.test import Client as TestClient, RequestFactory, TestCase
from django.urls import reverse

from clients.models import Client
from core.context_processors import navigation
from .models import ActivityLog
from .services import log

User = get_user_model()


class ActivityLogHelperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="manager1", password="pass12345", role="manager")

    def test_log_creates_entry_with_expected_fields(self):
        entry = log(self.user, "validation", self.user, detail={"note": "ok"})

        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.action, "validation")
        self.assertEqual(entry.object_type, "User")
        self.assertEqual(entry.object_id, str(self.user.pk))
        self.assertEqual(entry.detail, {"note": "ok"})

    def test_log_without_detail_defaults_to_empty_dict(self):
        entry = log(self.user, "creation", self.user)
        self.assertEqual(entry.detail, {})

    def test_log_with_anonymous_user_stores_null_user(self):
        entry = log(AnonymousUser(), "creation", self.user)
        self.assertIsNone(entry.user)


class NavigationContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client_entity = Client.objects.create(nom="Banque Test", actif=True)

    def test_anonymous_user_has_no_navigation(self):
        req = self.factory.get("/")
        req.user = AnonymousUser()
        data = navigation(req)
        self.assertEqual(data["nav_items"], [])
        self.assertEqual(data["user_role_label"], "")

    def test_only_admin_sees_auditor_creation_in_navigation(self):
        admin = User.objects.create_superuser(username="admin_nav", password="password")
        req = self.factory.get(reverse("accounts:auditor-create"))
        req.user = admin
        item = next(item for item in navigation(req)["nav_items"] if item["label"] == "Auditeurs")
        self.assertEqual(item["url"], reverse("accounts:auditor-list"))
        self.assertTrue(item["is_active"])
        req.user = User.objects.create_user(username="manager_nav", role=User.Role.MANAGER)
        self.assertNotIn("Auditeurs", [item["label"] for item in navigation(req)["nav_items"]])

    def test_manager_without_special_permissions_sees_base_manager_menu(self):
        manager = User.objects.create_user(username="mgr_basic", password="password", role=User.Role.MANAGER)
        req = self.factory.get("/app/missions/")
        req.user = manager
        data = navigation(req)
        labels = [item["label"] for item in data["nav_items"]]

        self.assertIn("Accueil", labels)
        self.assertIn("Missions", labels)
        self.assertIn("Clients", labels)
        self.assertNotIn("Formulaires", labels)
        self.assertNotIn("Revue", labels)
        self.assertNotIn("Mes missions", labels)
        self.assertNotIn("Mes visites", labels)
        self.assertNotIn("Avancement", labels)
        self.assertNotIn("Visites", labels)

        # Vérifier élément actif
        missions_item = next(item for item in data["nav_items"] if item["label"] == "Missions")
        self.assertTrue(missions_item["is_active"])

    def test_manager_with_manage_forms_sees_formulaires(self):
        manager = User.objects.create_user(username="mgr_forms", password="password", role=User.Role.MANAGER)
        perm = Permission.objects.get(codename="manage_forms")
        manager.user_permissions.add(perm)

        req = self.factory.get("/app/formulaires/")
        req.user = manager
        data = navigation(req)
        labels = [item["label"] for item in data["nav_items"]]

        self.assertIn("Formulaires", labels)
        self.assertNotIn("Revue", labels)
        forms_item = next(item for item in data["nav_items"] if item["label"] == "Formulaires")
        self.assertTrue(forms_item["is_active"])

    def test_manager_with_validate_visits_sees_revue(self):
        manager = User.objects.create_user(username="mgr_revue", password="password", role=User.Role.MANAGER)
        perm = Permission.objects.get(codename="validate_visits")
        manager.user_permissions.add(perm)

        req = self.factory.get("/app/revue/")
        req.user = manager
        data = navigation(req)
        labels = [item["label"] for item in data["nav_items"]]

        self.assertIn("Revue", labels)
        self.assertNotIn("Formulaires", labels)
        revue_item = next(item for item in data["nav_items"] if item["label"] == "Revue")
        self.assertTrue(revue_item["is_active"])

    def test_superviseur_sees_only_superviseur_menu(self):
        sup = User.objects.create_user(username="sup_user", password="password", role=User.Role.SUPERVISEUR)
        req = self.factory.get("/app/missions/")
        req.user = sup
        data = navigation(req)
        labels = [item["label"] for item in data["nav_items"]]

        self.assertEqual(labels, ["Mes missions", "Mes visites"])
        self.assertNotIn("Accueil", labels)
        self.assertNotIn("Revue", labels)
        self.assertNotIn("Missions", labels)
        self.assertNotIn("Clients", labels)
        self.assertNotIn("Formulaires", labels)
        self.assertNotIn("Avancement", labels)
        self.assertNotIn("Visites", labels)

        missions_item = next(item for item in data["nav_items"] if item["label"] == "Mes missions")
        self.assertTrue(missions_item["is_active"])

    def test_client_sees_only_client_menu(self):
        cli_user = User.objects.create_user(
            username="cli_user", password="password", role=User.Role.CLIENT, client=self.client_entity
        )
        req = self.factory.get("/portail/")
        req.user = cli_user
        data = navigation(req)
        labels = [item["label"] for item in data["nav_items"]]

        self.assertEqual(labels, ["Avancement", "Visites", "Messages"])
        self.assertNotIn("Accueil", labels)
        self.assertNotIn("Revue", labels)
        self.assertNotIn("Missions", labels)
        self.assertNotIn("Clients", labels)
        self.assertNotIn("Formulaires", labels)
        self.assertNotIn("Mes missions", labels)
        self.assertNotIn("Mes visites", labels)

        avancement_item = next(item for item in data["nav_items"] if item["label"] == "Avancement")
        self.assertTrue(avancement_item["is_active"])


class TemplateIntegrationAndLogoutTests(TestCase):
    def setUp(self):
        self.client_entity = Client.objects.create(nom="Client BNDA", actif=True)
        self.manager = User.objects.create_user(username="mgr_test", password="password123", role=User.Role.MANAGER)
        self.superviseur = User.objects.create_user(
            username="sup_test", password="password123", role=User.Role.SUPERVISEUR
        )
        self.client_user = User.objects.create_user(
            username="cli_test", password="password123", role=User.Role.CLIENT, client=self.client_entity
        )

    def test_logout_link_is_present_for_manager_and_only_manager_menu_visible(self):
        client = TestClient()
        client.login(username="mgr_test", password="password123")
        response = client.get(reverse("visits:mission-list"))
        self.assertEqual(response.status_code, 200)

        # Vérifier formulaire de déconnexion en POST
        self.assertContains(response, reverse("accounts:logout"))
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "Se déconnecter")

        # Vérifier entrées de menu manager
        self.assertContains(response, "Accueil")
        self.assertContains(response, "Missions")
        self.assertContains(response, "Clients")

        # Vérifier exclusion des menus des autres rôles
        self.assertNotContains(response, "Mes missions")
        self.assertNotContains(response, "Mes visites")
        self.assertNotContains(response, "Avancement")
        self.assertNotContains(response, "Visites")

    def test_logout_link_is_present_for_superviseur_and_only_superviseur_menu_visible(self):
        client = TestClient()
        client.login(username="sup_test", password="password123")
        response = client.get(reverse("visits:mission-list"))
        self.assertEqual(response.status_code, 200)

        # Vérifier formulaire de déconnexion en POST
        self.assertContains(response, reverse("accounts:logout"))
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "Se déconnecter")

        # Vérifier entrées de menu superviseur
        self.assertContains(response, "Mes missions")
        self.assertContains(response, "Mes visites")

        # Vérifier exclusion des menus manager et client
        self.assertNotContains(response, "Accueil")
        self.assertNotContains(response, "Revue")
        self.assertNotContains(response, "Formulaires")
        self.assertNotContains(response, "Clients")
        self.assertNotContains(response, "Avancement")

    def test_logout_link_is_present_for_client_and_only_client_menu_visible(self):
        client = TestClient()
        client.login(username="cli_test", password="password123")
        response = client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)

        # Vérifier formulaire de déconnexion en POST
        self.assertContains(response, reverse("accounts:logout"))
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "Se déconnecter")

        # Vérifier entrées de menu client
        self.assertContains(response, "Avancement")
        self.assertContains(response, "Visites")

        # Vérifier exclusion des menus manager et superviseur
        self.assertNotContains(response, "Accueil")
        self.assertNotContains(response, "Revue")
        self.assertNotContains(response, "Missions")
        self.assertNotContains(response, "Clients")
        self.assertNotContains(response, "Formulaires")
        self.assertNotContains(response, "Mes missions")
        self.assertNotContains(response, "Mes visites")

    def test_logout_post_redirects_to_login_with_message(self):
        client = TestClient()
        client.login(username="mgr_test", password="password123")
        response = client.post(reverse("accounts:logout"), follow=True)

        self.assertRedirects(response, reverse("accounts:login"))
        messages_list = list(get_messages(response.wsgi_request))
        self.assertTrue(len(messages_list) > 0)
        self.assertIn("déconnecté", messages_list[0].message.lower())
        self.assertContains(response, "déconnecté")


class SeedAccountsNavigationAndLayoutTests(TestCase):
    """Vérifie par le client de test, pour chaque compte du seed, que chaque
    page répond, étend bien base.html, contient le lien de déconnexion et
    n'affiche aucune entrée de menu interdite."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_demo")

    def _verify_account_pages(self, username, allowed_pages, forbidden_menu_labels, forbidden_urls=None):
        client = TestClient()
        logged_in = client.login(username=username, password="demo1234")
        self.assertTrue(logged_in, f"Impossible de connecter {username}")

        for url in allowed_pages:
            with self.subTest(username=username, url=url):
                response = client.get(url)
                self.assertEqual(
                    response.status_code, 200,
                    f"La page {url} pour {username} a retourné {response.status_code}"
                )
                html = response.content.decode("utf-8")
                # Vérifier extension de base.html
                self.assertIn("<html", html)
                self.assertIn("Suivi Terrain", html)

                # Vérifier présence de la déconnexion en POST
                self.assertIn(reverse("accounts:logout"), html)
                self.assertIn("Se déconnecter", html)

                # Vérifier exclusion stricte des éléments de menu interdits
                nav_items = response.context.get("nav_items", [])
                rendered_labels = [item["label"] for item in nav_items]
                for forbidden in forbidden_menu_labels:
                    self.assertNotIn(
                        forbidden, rendered_labels,
                        f"Menu interdit '{forbidden}' présent dans la navigation pour {username} sur {url}"
                    )

        # Vérifier que les URL interdites renvoient 403 ou redirection
        if forbidden_urls:
            for bad_url in forbidden_urls:
                with self.subTest(username=username, bad_url=bad_url):
                    bad_res = client.get(bad_url)
                    self.assertIn(
                        bad_res.status_code, [302, 403, 404],
                        f"{username} a pu accéder à l'URL interdite {bad_url} (HTTP {bad_res.status_code})"
                    )

    def test_admin_account_navigation_and_pages(self):
        pages = [
            reverse("app-home"),
            reverse("clients:list"),
            reverse("forms_cms:list"),
            reverse("visits:mission-list"),
            reverse("revue:list"),
        ]
        forbidden = ["Mes missions", "Mes visites", "Avancement", "Visites"]
        self._verify_account_pages("admin", pages, forbidden)

    def test_manager1_account_navigation_and_pages(self):
        # manager1 : toutes permissions (manage_forms, validate_visits)
        pages = [
            reverse("app-home"),
            reverse("clients:list"),
            reverse("forms_cms:list"),
            reverse("visits:mission-list"),
            reverse("revue:list"),
        ]
        forbidden = ["Mes missions", "Mes visites", "Avancement", "Visites"]
        forbidden_urls = [reverse("my-visits"), reverse("portal:visit-list")]
        self._verify_account_pages("manager1", pages, forbidden, forbidden_urls)

    def test_manager2_account_navigation_and_pages(self):
        # manager2 : validate_visits uniquement, pas manage_forms
        pages = [
            reverse("app-home"),
            reverse("clients:list"),
            reverse("visits:mission-list"),
            reverse("revue:list"),
        ]
        forbidden_menu = ["Formulaires", "Mes missions", "Mes visites", "Avancement", "Visites"]
        forbidden_urls = [reverse("forms_cms:list"), reverse("my-visits"), reverse("portal:visit-list")]
        self._verify_account_pages("manager2", pages, forbidden_menu, forbidden_urls)

    def test_superviseurs_navigation_and_pages(self):
        for sup in ["sup1", "sup2", "sup3", "sup4"]:
            with self.subTest(supervisor=sup):
                pages = [reverse("visits:mission-list"), reverse("my-visits")]
                forbidden_menu = ["Accueil", "Revue", "Clients", "Formulaires", "Avancement", "Visites"]
                forbidden_urls = [
                    reverse("app-home"),
                    reverse("clients:list"),
                    reverse("forms_cms:list"),
                    reverse("revue:list"),
                    reverse("portal:dashboard"),
                    reverse("portal:visit-list"),
                ]
                self._verify_account_pages(sup, pages, forbidden_menu, forbidden_urls)

    def test_clients_navigation_and_pages(self):
        for cli in ["client_bnda", "client_exemple"]:
            with self.subTest(client=cli):
                pages = [reverse("portal:dashboard"), reverse("portal:visit-list")]
                forbidden_menu = ["Accueil", "Revue", "Missions", "Mes missions", "Mes visites", "Clients", "Formulaires"]
                forbidden_urls = [
                    reverse("app-home"),
                    reverse("clients:list"),
                    reverse("forms_cms:list"),
                    reverse("visits:mission-list"),
                    reverse("revue:list"),
                    reverse("my-visits"),
                ]
                self._verify_account_pages(cli, pages, forbidden_menu, forbidden_urls)

