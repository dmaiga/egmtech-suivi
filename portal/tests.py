from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clients.models import Client, Site
from core.models import ActivityLog
from forms_cms.models import AttachedForm, FormTemplate
from visits.models import Mission, Visit

SCHEMA = {
    "sections": [
        {
            "title": "Identification",
            "fields": [{"key": "nom", "label": "Nom", "type": "text", "required": True}],
        }
    ]
}


def make_client_user(nom="Client A", username="client_a"):
    client_obj = Client.objects.create(nom=nom)
    user = User.objects.create_user(username=username, password="x", role=User.Role.CLIENT, client=client_obj)
    return client_obj, user


def make_mission_and_visit(client_obj, statut, ville="Bamako"):
    site = Site.objects.create(client=client_obj, code=f"S{client_obj.pk}", nom=f"Site {client_obj.pk}", ville=ville)
    template = FormTemplate.objects.create(nom="Rapport", schema=SCHEMA, actif=True)
    attached = AttachedForm.objects.create(client=client_obj, template=template, nom="Rapport", schema=SCHEMA)
    manager = User.objects.create_user(username=f"mgr{client_obj.pk}", password="x", role=User.Role.MANAGER)
    sup = User.objects.create_user(username=f"sup{client_obj.pk}", password="x", role=User.Role.SUPERVISEUR)
    mission = Mission.objects.create(superviseur=sup, site=site, attached_form=attached, created_by=manager)
    visit = Visit.objects.create(
        mission=mission,
        auteur=sup,
        statut=statut,
        date_debut=timezone.now(),
        date_soumission=timezone.now(),
        reponses={"nom": "Awa"},
    )
    return site, attached, mission, visit


class PortalCloisonnementTests(TestCase):
    def setUp(self):
        self.client_a, self.user_a = make_client_user("Client A", "client_a")
        self.client_b, self.user_b = make_client_user("Client B", "client_b")
        self.site_a, self.attached_a, self.mission_a, self.visit_a = make_mission_and_visit(
            self.client_a, Visit.Statut.PUBLIEE
        )
        self.site_b, self.attached_b, self.mission_b, self.visit_b = make_mission_and_visit(
            self.client_b, Visit.Statut.PUBLIEE
        )

    def test_dashboard_ne_montre_que_les_sites_du_client(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:dashboard"))
        sites = [row["site"] for row in response.context["table"]]
        self.assertEqual(sites, [self.site_a])

    def test_fiche_site_dun_autre_client_est_introuvable(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:site-detail", args=[self.site_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_visite_dun_autre_client_est_introuvable_meme_en_devinant_lurl(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:visit-detail", args=[self.visit_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_fiche_de_son_propre_site_est_accessible(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:site-detail", args=[self.site_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.visit_a, list(response.context["visits"]))

    def test_manager_ne_peut_pas_acceder_au_portail(self):
        manager = User.objects.create_user(username="mgr_portail", password="x", role=User.Role.MANAGER)
        self.client.force_login(manager)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_anonyme_redirige_vers_connexion(self):
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 302)


class PortalVisibilitePublicationTests(TestCase):
    def setUp(self):
        self.client_obj, self.user = make_client_user("Client A", "client_a")

    def test_visite_non_publiee_absente_de_lhistorique(self):
        site, _, _, visit_brouillon = make_mission_and_visit(self.client_obj, Visit.Statut.BROUILLON)
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:site-detail", args=[site.pk]))
        self.assertNotIn(visit_brouillon, list(response.context["visits"]))

    def test_visite_validee_non_publiee_est_introuvable_en_detail(self):
        _, _, _, visit = make_mission_and_visit(self.client_obj, Visit.Statut.VALIDEE)
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:visit-detail", args=[visit.pk]))
        self.assertEqual(response.status_code, 404)

    def test_visite_depubliee_nest_plus_visible(self):
        site, _, _, visit = make_mission_and_visit(self.client_obj, Visit.Statut.DEPUBLIEE)
        self.client.force_login(self.user)

        response_detail = self.client.get(reverse("portal:visit-detail", args=[visit.pk]))
        self.assertEqual(response_detail.status_code, 404)

        response_list = self.client.get(reverse("portal:site-detail", args=[site.pk]))
        self.assertNotIn(visit, list(response_list.context["visits"]))

    def test_visite_publiee_visible_et_journalisee(self):
        _, _, _, visit = make_mission_and_visit(self.client_obj, Visit.Statut.PUBLIEE)
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:visit-detail", args=[visit.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ActivityLog.objects.filter(
                action="consultation_visite_portail", user=self.user, object_id=str(visit.pk)
            ).exists()
        )


class PortalFiltersTests(TestCase):
    def setUp(self):
        self.client_obj, self.user = make_client_user("Client A", "client_a")
        self.site1, self.attached1, _, _ = make_mission_and_visit(
            self.client_obj, Visit.Statut.PUBLIEE, ville="Bamako"
        )
        self.site2 = Site.objects.create(client=self.client_obj, code="S2", nom="Site 2", ville="Sikasso")

    def test_filtre_par_ville(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:dashboard"), {"ville": "Sikasso"})
        sites = [row["site"] for row in response.context["table"]]
        self.assertEqual(sites, [self.site2])

    def test_filtre_par_formulaire(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:dashboard"), {"formulaire": self.attached1.pk})
        for row in response.context["table"]:
            forms = [entry["attached_form"].pk for entry in row["entries"]]
            self.assertEqual(forms, [self.attached1.pk])
