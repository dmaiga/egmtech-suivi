import os
import tempfile
import zipfile
from io import BytesIO

from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clients.models import Client, Site
from core.models import ActivityLog
from forms_cms.models import AttachedForm, FormTemplate
from visits import echanges as echanges_service
from visits.models import Echange, EchangeFichier, Mission, Visit

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


class EchangeTests(TestCase):
    def setUp(self):
        self.client_a, self.user_a = make_client_user("Client A", "client_a")
        self.client_b, self.user_b = make_client_user("Client B", "client_b")
        _, _, _, self.visit = make_mission_and_visit(self.client_a, Visit.Statut.PUBLIEE)
        _, _, _, self.visit_validee = make_mission_and_visit(self.client_a, Visit.Statut.VALIDEE)
        self.nouveau = reverse("portal:echange-nouveau")
        self.manager = User.objects.create_user(username="mgr_rep", password="x", role=User.Role.MANAGER)
        self.manager.user_permissions.add(Permission.objects.get(codename="validate_visits"))

    def _client_ecrit_sur_rapport(self, texte="Question 1"):
        self.client.force_login(self.user_a)
        self.client.post(self.nouveau, {"visite": self.visit.pk, "sujet": "Rapport", "texte": texte})
        return Echange.objects.get(visit=self.visit)

    def test_fil_depuis_rapport_et_non_lus(self):
        echange = self._client_ecrit_sur_rapport()
        self.assertEqual(echanges_service.nb_non_lus_manager(), 1)
        mgr_url = reverse("revue:echange", args=[echange.pk])
        self.client.force_login(self.manager)
        self.client.get(mgr_url)
        self.assertEqual(echanges_service.nb_non_lus_manager(), 0)
        self.client.post(mgr_url, {"texte": "Réponse 1"})
        self.assertEqual(echanges_service.nb_non_lus_client(self.client_a), 1)
        self.client.force_login(self.user_a)
        res = self.client.get(reverse("portal:echange-detail", args=[echange.pk]))
        self.assertContains(res, "Réponse 1")
        self.assertEqual(echanges_service.nb_non_lus_client(self.client_a), 0)

    def test_client_demarre_discussion_sans_rapport(self):
        self.client.force_login(self.user_a)
        res = self.client.post(self.nouveau, {"sujet": "Question générale", "texte": "Bonjour"})
        echange = Echange.objects.get()
        self.assertIsNone(echange.visit)
        self.assertEqual(echange.client, self.client_a)
        self.assertRedirects(res, reverse("portal:echange-detail", args=[echange.pk]))
        self.assertContains(self.client.get(reverse("portal:echange-list")), "Question générale")
        # sujet ou message vide => rien créé
        self.client.post(self.nouveau, {"sujet": "", "texte": "x"})
        self.assertEqual(Echange.objects.count(), 1)

    def test_manager_demarre_message_sans_reponse(self):
        self.client.force_login(self.manager)
        url = reverse("revue:echange-nouveau")
        res = self.client.post(url, {"client": self.client_a.pk, "sujet": "Information", "texte": "Bonjour client"})
        echange = Echange.objects.get()
        self.assertRedirects(res, reverse("revue:echange", args=[echange.pk]))
        self.assertEqual(echanges_service.nb_non_lus_client(self.client_a), 1)
        self.assertEqual(echanges_service.nb_non_lus_client(self.client_b), 0)
        self.client.force_login(self.user_a)
        self.assertContains(self.client.get(reverse("portal:echange-detail", args=[echange.pk])), "Bonjour client")
        self.client.force_login(self.user_b)
        self.assertEqual(self.client.get(reverse("portal:echange-detail", args=[echange.pk])).status_code, 404)

    def test_inbox_filtres_et_statut(self):
        echange = self._client_ecrit_sur_rapport("Bonjour")
        self.client.force_login(self.manager)
        inbox = reverse("revue:inbox")
        self.assertContains(self.client.get(inbox), self.client_a.nom)
        self.assertContains(self.client.get(inbox, {"client": self.client_b.pk}), "Aucun échange")
        self.assertContains(self.client.get(inbox, {"non_lus": "1"}), "1 nouveau")
        self.client.post(reverse("revue:echange-statut", args=[echange.pk]))
        self.assertContains(self.client.get(inbox), "Aucun échange")
        self.assertContains(self.client.get(inbox, {"statut": "clos"}), self.client_a.nom)
        self.client.force_login(self.user_a)
        self.client.post(reverse("portal:echange-detail", args=[echange.pk]), {"texte": "Encore"})
        echange.refresh_from_db()
        self.assertEqual(echange.statut, "ouvert")

    def test_cloisonnement_client(self):
        echange = self._client_ecrit_sur_rapport("SECRET_FIL")
        self.client.force_login(self.user_b)
        res = self.client.get(reverse("portal:echange-list"))
        self.assertNotContains(res, "SECRET_FIL")
        self.assertNotContains(res, "Rapport")
        detail = reverse("portal:echange-detail", args=[echange.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.post(detail, {"texte": "Intrus"}).status_code, 404)
        # ne peut pas ouvrir une discussion sur le rapport d'un autre client
        res = self.client.post(self.nouveau, {"visite": self.visit.pk, "sujet": "s", "texte": "t"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(echange.messages.count(), 1)

    def test_visite_non_publiee_refusee(self):
        self.client.force_login(self.user_a)
        res = self.client.post(self.nouveau, {"visite": self.visit_validee.pk, "sujet": "s", "texte": "t"})
        self.assertEqual(res.status_code, 404)
        self.client.force_login(self.manager)
        res = self.client.post(
            reverse("revue:echange-nouveau"), {"visite": self.visit_validee.pk, "sujet": "s", "texte": "t"}
        )
        self.assertEqual(res.status_code, 404)

    def test_depublication_masque_et_bloque(self):
        echange = self._client_ecrit_sur_rapport()
        self.visit.statut = Visit.Statut.DEPUBLIEE
        self.visit.save()
        self.client.force_login(self.user_a)
        self.assertEqual(self.client.get(reverse("portal:echange-detail", args=[echange.pk])).status_code, 404)
        self.assertEqual(echanges_service.nb_non_lus_client(self.client_a), 0)
        self.client.force_login(self.manager)
        mgr_url = reverse("revue:echange", args=[echange.pk])
        self.assertEqual(self.client.get(mgr_url).status_code, 200)
        self.assertEqual(self.client.post(mgr_url, {"texte": "x"}).status_code, 403)

    def test_roles_non_autorises(self):
        echange = self._client_ecrit_sur_rapport()
        n = echange.messages.count()
        self.client.force_login(self.visit.mission.superviseur)
        self.assertEqual(self.client.get(reverse("revue:inbox")).status_code, 403)
        self.assertIn(self.client.get(self.nouveau).status_code, [302, 403])
        self.client.force_login(self.user_a)
        for name, args in [("revue:inbox", []), ("revue:echange", [echange.pk]), ("revue:echange-nouveau", [])]:
            self.assertEqual(self.client.post(reverse(name, args=args), {"texte": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("revue:echange-statut", args=[echange.pk])).status_code, 403)
        self.assertEqual(echange.messages.count(), n)

    def test_boutons_menu_et_dashboard(self):
        self.client.force_login(self.user_a)
        res = self.client.get(reverse("portal:visit-detail", args=[self.visit.pk]))
        self.assertContains(res, self.nouveau + f"?visite={self.visit.pk}")
        self.assertContains(res, reverse("portal:echange-list"))
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("app-home")), "Messages des clients")

    def test_menu_revue_pas_actif_sur_messages(self):
        self.client.force_login(self.manager)
        res = self.client.get(reverse("revue:inbox"))
        actifs = [i["label"] for i in res.context["nav_items"] if i["is_active"]]
        self.assertEqual(actifs, ["Messages"])
        res = self.client.get(reverse("revue:list"))
        actifs = [i["label"] for i in res.context["nav_items"] if i["is_active"]]
        self.assertEqual(actifs, ["Revue"])


def _gros_png(largeur=4000, hauteur=3000):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.effect_noise((largeur, hauteur), 80).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


class PiecesJointesTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client_a, self.user_a = make_client_user("Client A", "client_a")
        self.client_b, self.user_b = make_client_user("Client B", "client_b")
        self.manager = User.objects.create_user(username="mgr_pj", password="x", role=User.Role.MANAGER)
        self.manager.user_permissions.add(Permission.objects.get(codename="validate_visits"))
        self.url = reverse("portal:echange-nouveau")

    def _envoyer(self, *fichiers, texte="Voir pièce"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.user_a)
        return self.client.post(
            self.url,
            {"sujet": "Photo", "texte": texte, "fichiers": [SimpleUploadedFile(n, c) for n, c in fichiers]},
        )

    def test_image_compressee_avec_miniature(self):
        from PIL import Image

        brut = _gros_png()
        self._envoyer(("grande.png", brut))
        pj = EchangeFichier.objects.get()
        self.assertTrue(pj.est_image)
        self.assertLess(pj.fichier.size, len(brut) / 3)
        with Image.open(pj.fichier.path) as img:
            self.assertLessEqual(max(img.size), 1920)
        with Image.open(pj.miniature.path) as img:
            self.assertLessEqual(max(img.size), 320)
        self.assertNotIn("grande", pj.fichier.name)
        self.assertEqual(pj.nom_original, "grande.png")

    def test_document_accepte_et_fichiers_dangereux_refuses(self):
        self._envoyer(("rapport.pdf", b"%PDF-1.4 test"))
        self.assertEqual(EchangeFichier.objects.filter(est_image=False).count(), 1)
        n = Echange.objects.count()
        self._envoyer(("evil.html", b"<script>"))
        self._envoyer(("faux.png", b"pas une image"))
        self.assertEqual(Echange.objects.count(), n)
        self.assertEqual(EchangeFichier.objects.count(), 1)

    def test_message_avec_pj_seule_et_limite_nombre(self):
        self._envoyer(("a.txt", b"x"), texte="")
        self.assertEqual(EchangeFichier.objects.count(), 1)
        n = Echange.objects.count()
        self._envoyer(*[(f"{i}.txt", b"x") for i in range(6)])
        self.assertEqual(Echange.objects.count(), n)

    def test_acces_pj_cloisonne(self):
        self._envoyer(("grande.png", _gros_png(800, 600)))
        pj = EchangeFichier.objects.get()
        for user, statut in [(self.user_a, 200), (self.manager, 200), (self.user_b, 404)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(pj.fichier.url).status_code, statut)
            self.assertEqual(self.client.get(pj.miniature.url).status_code, statut)
        self.client.logout()
        self.assertEqual(self.client.get(pj.fichier.url).status_code, 302)

    def test_document_servi_en_telechargement(self):
        self._envoyer(("rapport.pdf", b"%PDF-1.4 test"))
        pj = EchangeFichier.objects.get()
        self.client.force_login(self.user_a)
        res = self.client.get(pj.fichier.url)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("rapport.pdf", res["Content-Disposition"])
