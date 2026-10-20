import os
import tempfile
import zipfile
from io import BytesIO

from django.conf import settings
from django.test import TestCase, override_settings
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


_unique_counter = iter(range(1, 100000))


def make_mission_and_visit(client_obj, statut, ville="Bamako"):
    suffix = next(_unique_counter)
    site = Site.objects.create(
        client=client_obj, code=f"S{client_obj.pk}-{suffix}", nom=f"Site {client_obj.pk}-{suffix}", ville=ville
    )
    template = FormTemplate.objects.create(nom="Rapport", schema=SCHEMA, actif=True)
    attached = AttachedForm.objects.create(client=client_obj, template=template, nom="Rapport", schema=SCHEMA)
    manager = User.objects.create_user(username=f"mgr{suffix}", password="x", role=User.Role.MANAGER)
    sup = User.objects.create_user(username=f"sup{suffix}", password="x", role=User.Role.SUPERVISEUR)
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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(dir=os.path.join(settings.BASE_DIR, "media")))
class PortalExportTests(TestCase):
    def setUp(self):
        self.client_a, self.user_a = make_client_user("Client A", "client_a")
        self.client_b, self.user_b = make_client_user("Client B", "client_b")
        self.site_a, _, _, self.visit_a = make_mission_and_visit(self.client_a, Visit.Statut.PUBLIEE)
        self.site_b, _, _, self.visit_b = make_mission_and_visit(self.client_b, Visit.Statut.PUBLIEE)
        # Visite non publiée côté client A : ne doit jamais apparaître dans un export.
        _, _, _, self.visit_a_brouillon = make_mission_and_visit(self.client_a, Visit.Statut.BROUILLON)

    def test_pdf_dune_visite_publiee(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:visit-pdf", args=[self.visit_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_dune_visite_dun_autre_client_est_introuvable(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:visit-pdf", args=[self.visit_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_export_site_ne_contient_que_les_visites_publiees_du_site(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:site-export", args=[self.site_a.pk]))
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(archive.namelist()), 1)

    def test_export_site_dun_autre_client_est_introuvable(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:site-export", args=[self.site_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_export_client_ne_contient_que_son_propre_perimetre(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("portal:client-export"))
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(BytesIO(response.content))
        # Une seule visite publiée pour Client A (la visite brouillon est exclue).
        self.assertEqual(len(archive.namelist()), 1)

        self.client.force_login(self.user_b)
        response_b = self.client.get(reverse("portal:client-export"))
        archive_b = zipfile.ZipFile(BytesIO(response_b.content))
        self.assertEqual(len(archive_b.namelist()), 1)
        self.assertNotEqual(archive.namelist(), archive_b.namelist())


class PortalSobrietyAndVocabularyTests(TestCase):
    def setUp(self):
        self.client_obj, self.user = make_client_user("Banque Atlantique", "user_ba")
        self.site, self.attached, self.mission, self.visit_publiee = make_mission_and_visit(
            self.client_obj, Visit.Statut.PUBLIEE, ville="Bamako"
        )
        self.visit_publiee.commentaire_rejet = "CONFIDENTIEL: motif de rejet interne rejet_visite"
        self.visit_publiee.save()

        # Visite brouillon sur le même site
        self.visit_brouillon = Visit.objects.create(
            mission=self.mission,
            auteur=self.mission.superviseur,
            statut=Visit.Statut.BROUILLON,
            date_debut=timezone.now(),
            reponses={"nom": "SecretBrouillon"},
        )
        # Visite à corriger sur le même site
        self.visit_a_corriger = Visit.objects.create(
            mission=self.mission,
            auteur=self.mission.superviseur,
            statut=Visit.Statut.A_CORRIGER,
            date_debut=timezone.now(),
            commentaire_rejet="SECRET_REJET_INTERNE_NE_PAS_DIFFUSER",
            reponses={"nom": "SecretACorriger"},
        )

        ActivityLog.objects.create(
            user=self.mission.created_by,
            action="rejet_visite",
            object_type="Visit",
            object_id=str(self.visit_publiee.pk),
            detail={"commentaire": "HISTORIQUE_INTERNE_ACTION_LOG"},
        )

    def test_dashboard_sans_vocabulaire_interne_ni_visites_non_publiees(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)

        # Les 3 chiffres clés et la barre de progression sont présents
        self.assertContains(response, "Sites sous contrat")
        self.assertContains(response, "Visites réalisées")
        self.assertContains(response, "Visites planifiées")
        self.assertContains(response, "Progression globale des interventions")
        self.assertContains(response, "Exporter tout (ZIP)")

        # Les visites non publiées ne doivent pas apparaître dans le HTML
        self.assertNotContains(response, "SecretBrouillon")
        self.assertNotContains(response, "SecretACorriger")
        self.assertNotContains(response, "brouillon")
        self.assertNotContains(response, "a_corriger")
        self.assertNotContains(response, "SECRET_REJET_INTERNE_NE_PAS_DIFFUSER")
        self.assertNotContains(response, "CONFIDENTIEL: motif de rejet")

    def test_site_detail_chronologie_sans_vocabulaire_interne_avec_rappel_a_faire(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:site-detail", args=[self.site.pk]))
        self.assertEqual(response.status_code, 200)

        # Fiche site et export ZIP
        self.assertContains(response, self.site.nom)
        self.assertContains(response, "Exporter ce site (ZIP)")

        # Rappel de ce qui reste à faire
        self.assertContains(response, "Rappel des interventions prévues")

        # Chronologie des visites publiées
        self.assertContains(response, "Chronologie des interventions publiées")
        self.assertContains(response, "Voir le détail")
        self.assertContains(response, "PDF")

        # Les visites non publiées et le vocabulaire interne sont absents
        self.assertNotContains(response, "SecretBrouillon")
        self.assertNotContains(response, "SecretACorriger")
        self.assertNotContains(response, "SECRET_REJET_INTERNE_NE_PAS_DIFFUSER")
        self.assertNotContains(response, "CONFIDENTIEL: motif de rejet")
        self.assertNotContains(response, "rejet_visite")

    def test_visit_detail_sans_historique_interne_avec_bouton_pdf(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:visit-detail", args=[self.visit_publiee.pk]))
        self.assertEqual(response.status_code, 200)

        # Le détail métier s'affiche avec le bouton de téléchargement PDF
        self.assertContains(response, "Awa")
        self.assertContains(response, "Télécharger le PDF")

        # Aucun historique interne ni motif de rejet ne doit fuiter
        self.assertNotContains(response, "Historique interne")
        self.assertNotContains(response, "Dernier motif de rejet")
        self.assertNotContains(response, "CONFIDENTIEL: motif de rejet interne")
        self.assertNotContains(response, "HISTORIQUE_INTERNE_ACTION_LOG")
        self.assertNotContains(response, "rejet_visite")

    def test_recherche_par_nom_et_code_site(self):
        site2 = Site.objects.create(
            client=self.client_obj, code="SG-SPECIAL-CODE", nom="Agence Spéciale", ville="Sikasso"
        )
        self.client.force_login(self.user)

        # Recherche par code
        response_code = self.client.get(reverse("portal:dashboard"), {"q": "SPECIAL-CODE"})
        self.assertEqual(response_code.status_code, 200)
        self.assertContains(response_code, "Agence Spéciale")
        self.assertNotContains(response_code, self.site.nom)

        # Recherche par nom
        response_nom = self.client.get(reverse("portal:dashboard"), {"q": "Spéciale"})
        self.assertEqual(response_nom.status_code, 200)
        self.assertContains(response_nom, "Agence Spéciale")
        self.assertNotContains(response_nom, self.site.nom)

    def test_visit_list_affiche_uniquement_les_visites_publiees_du_client(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:visit-list"))
        self.assertEqual(response.status_code, 200)

        # La visite publiée du client est visible
        self.assertContains(response, self.site.nom)
        self.assertContains(response, self.attached.nom)
        self.assertContains(response, "Publiée")
        self.assertContains(response, "Exporter tout (ZIP)")

        # Les visites non publiées sont exclues
        self.assertNotContains(response, "SecretBrouillon")
        self.assertNotContains(response, "SecretACorriger")
        self.assertNotContains(response, "brouillon")
        self.assertNotContains(response, "a_corriger")

        # La visite d'un autre client est strictement exclue
        other_client = Client.objects.create(nom="Autre Client Inc")
        other_site = Site.objects.create(client=other_client, nom="Site Etranger", code="SE-01")
        other_mission = Mission.objects.create(
            site=other_site,
            superviseur=self.mission.superviseur,
            attached_form=self.attached,
            created_by=self.mission.created_by,
        )
        other_visit = Visit.objects.create(mission=other_mission, auteur=self.mission.superviseur, statut=Visit.Statut.PUBLIEE)

        resp2 = self.client.get(reverse("portal:visit-list"))
        self.assertNotContains(resp2, "Site Etranger")

    def test_visit_list_filtres_et_recherche(self):
        self.client.force_login(self.user)

        # Recherche par code
        res_code = self.client.get(reverse("portal:visit-list"), {"q": self.site.code})
        self.assertEqual(res_code.status_code, 200)
        self.assertContains(res_code, self.site.nom)

        # Recherche introuvable
        res_none = self.client.get(reverse("portal:visit-list"), {"q": "CODE-INEXISTANT-XYZ"})
        self.assertEqual(res_none.status_code, 200)
        self.assertContains(res_none, "Aucun rapport de visite trouvé")

        # Filtre par site
        res_site = self.client.get(reverse("portal:visit-list"), {"site": self.site.pk})
        self.assertEqual(res_site.status_code, 200)
        self.assertContains(res_site, self.site.nom)

    def test_visit_list_sans_vocabulaire_interne(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal:visit-list"))
        self.assertEqual(response.status_code, 200)

        self.assertNotContains(response, "CONFIDENTIEL: motif de rejet")
        self.assertNotContains(response, "SECRET_REJET_INTERNE_NE_PAS_DIFFUSER")
        self.assertNotContains(response, "HISTORIQUE_INTERNE_ACTION_LOG")
        self.assertNotContains(response, "rejet_visite")

    def test_visit_list_interdite_aux_superviseurs(self):
        self.client.force_login(self.mission.superviseur)
        response = self.client.get(reverse("portal:visit-list"))
        # Les non-clients doivent être redirigés ou interdits (role_required)
        self.assertIn(response.status_code, [302, 403])
