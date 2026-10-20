import base64
import os
import tempfile
import zipfile
from io import BytesIO

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clients.models import Client, Site
from core.models import ActivityLog
from forms_cms.models import AttachedForm, FormTemplate

from .models import Mission, Visit, VisitPhoto

SIMPLE_SCHEMA = {
    "sections": [
        {
            "title": "Identification",
            "fields": [
                {"key": "nom_technicien", "label": "Nom du technicien", "type": "text", "required": True},
                {"key": "observations", "label": "Observations", "type": "text", "required": False},
            ],
        },
        {
            "title": "Photos",
            "fields": [
                {"key": "photo_site", "label": "Photo du site", "type": "photo", "max_photos": 2, "required": False},
            ],
        },
    ]
}

# PNG 1x1 transparent, utilisé comme fausse signature dans les tests.
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScy8w"
    "AAAABJRU5ErkJggg=="
)
SIGNATURE_DATA_URL = "data:image/png;base64," + TINY_PNG_BASE64


def make_client_site_form():
    client_obj = Client.objects.create(nom="Client A")
    site = Site.objects.create(client=client_obj, code="S1", nom="Site 1")
    template = FormTemplate.objects.create(nom="Rapport", schema=SIMPLE_SCHEMA, actif=True)
    attached = AttachedForm.objects.create(
        client=client_obj, template=template, nom="Rapport", schema=SIMPLE_SCHEMA, actif=True
    )
    return client_obj, site, attached


class MissionVisibilityTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.sup1 = User.objects.create_user(username="sup1", password="x", role=User.Role.SUPERVISEUR)
        self.sup2 = User.objects.create_user(username="sup2", password="x", role=User.Role.SUPERVISEUR)
        _, site, attached = make_client_site_form()
        self.mission1 = Mission.objects.create(
            superviseur=self.sup1, site=site, attached_form=attached, created_by=self.manager
        )
        self.mission2 = Mission.objects.create(
            superviseur=self.sup2, site=site, attached_form=attached, created_by=self.manager
        )

    def test_superviseur_ne_voit_que_ses_missions(self):
        self.client.force_login(self.sup1)
        response = self.client.get(reverse("visits:mission-list"))
        missions = list(response.context["missions"])
        self.assertEqual(missions, [self.mission1])

    def test_manager_voit_toutes_les_missions(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("visits:mission-list"))
        missions = set(response.context["missions"])
        self.assertEqual(missions, {self.mission1, self.mission2})

    def test_superviseur_ne_peut_pas_demarrer_la_mission_dun_autre(self):
        self.client.force_login(self.sup1)
        response = self.client.get(reverse("visits:visit-start", args=[self.mission2.pk]))
        self.assertEqual(response.status_code, 404)


class MissionCreationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.sup = User.objects.create_user(username="sup", password="x", role=User.Role.SUPERVISEUR)
        self.client_obj, self.site, self.attached = make_client_site_form()
        self.client.force_login(self.manager)

    def test_creation_mission_valide(self):
        response = self.client.post(
            reverse("visits:mission-create"),
            {"superviseur": self.sup.pk, "site": self.site.pk, "attached_form": self.attached.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Mission.objects.count(), 1)

    def test_formulaire_dun_autre_client_refuse(self):
        autre_client = Client.objects.create(nom="Client B")
        autre_site = Site.objects.create(client=autre_client, code="S1", nom="Site B1")
        response = self.client.post(
            reverse("visits:mission-create"),
            {"superviseur": self.sup.pk, "site": autre_site.pk, "attached_form": self.attached.pk},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Mission.objects.count(), 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VisitSubmissionTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.sup = User.objects.create_user(username="sup", password="x", role=User.Role.SUPERVISEUR)
        _, self.site, self.attached = make_client_site_form()
        self.mission = Mission.objects.create(
            superviseur=self.sup, site=self.site, attached_form=self.attached, created_by=self.manager
        )
        self.client.force_login(self.sup)
        self.client.get(reverse("visits:visit-start", args=[self.mission.pk]))
        self.visit = Visit.objects.get(mission=self.mission)

    def test_soumission_sans_champ_obligatoire_est_refusee(self):
        response = self.client.post(
            reverse("visits:visit-submit", args=[self.visit.pk]),
            {"observations": "rien à signaler"},
        )
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.BROUILLON)

    def test_soumission_sans_signature_est_refusee(self):
        response = self.client.post(
            reverse("visits:visit-submit", args=[self.visit.pk]),
            {"nom_technicien": "Awa"},
        )
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.BROUILLON)

    def test_soumission_complete_valide(self):
        response = self.client.post(
            reverse("visits:visit-submit", args=[self.visit.pk]),
            {"nom_technicien": "Awa", "signature_superviseur_data": SIGNATURE_DATA_URL},
        )
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.SOUMISE)
        self.assertIsNotNone(self.visit.date_soumission)
        self.assertTrue(self.visit.signature_superviseur.name)

    def test_brouillon_enregistre_sans_validation_des_obligatoires(self):
        response = self.client.post(
            reverse("visits:visit-save", args=[self.visit.pk]),
            {"observations": "en cours"},
        )
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.BROUILLON)
        self.assertEqual(self.visit.reponses.get("observations"), "en cours")

    def test_un_autre_superviseur_ne_peut_pas_editer_la_visite(self):
        autre = User.objects.create_user(username="sup2", password="x", role=User.Role.SUPERVISEUR)
        self.client.force_login(autre)
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 404)


@override_settings(VISITS_MAX_PHOTO_SIZE_BYTES=100, MEDIA_ROOT=tempfile.mkdtemp())
class PhotoSizeLimitTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.sup = User.objects.create_user(username="sup", password="x", role=User.Role.SUPERVISEUR)
        _, self.site, self.attached = make_client_site_form()
        self.mission = Mission.objects.create(
            superviseur=self.sup, site=self.site, attached_form=self.attached, created_by=self.manager
        )
        self.client.force_login(self.sup)
        self.client.get(reverse("visits:visit-start", args=[self.mission.pk]))
        self.visit = Visit.objects.get(mission=self.mission)

    def test_photo_trop_lourde_est_rejetee(self):
        gros_fichier = SimpleUploadedFile("photo.jpg", b"x" * 200, content_type="image/jpeg")
        response = self.client.post(
            reverse("visits:visit-save", args=[self.visit.pk]),
            {"photo_site": gros_fichier},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(VisitPhoto.objects.count(), 0)

    def test_photo_dans_la_limite_est_acceptee(self):
        petit_fichier = SimpleUploadedFile("photo.jpg", b"x" * 50, content_type="image/jpeg")
        response = self.client.post(
            reverse("visits:visit-save", args=[self.visit.pk]),
            {"photo_site": petit_fichier},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VisitPhoto.objects.count(), 1)

    def test_depassement_du_nombre_max_de_photos(self):
        for _ in range(2):
            self.client.post(
                reverse("visits:visit-save", args=[self.visit.pk]),
                {"photo_site": SimpleUploadedFile("photo.jpg", b"x" * 50, content_type="image/jpeg")},
            )
        response = self.client.post(
            reverse("visits:visit-save", args=[self.visit.pk]),
            {"photo_site": SimpleUploadedFile("photo.jpg", b"x" * 50, content_type="image/jpeg")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(VisitPhoto.objects.count(), 2)


class RevueTests(TestCase):
    def setUp(self):
        self.permission = Permission.objects.get(codename="validate_visits")

        self.manager_sans_droit = User.objects.create_user(
            username="manager1", password="x", role=User.Role.MANAGER
        )
        self.validateur = User.objects.create_user(username="manager2", password="x", role=User.Role.MANAGER)
        self.validateur.user_permissions.add(self.permission)

        self.sup = User.objects.create_user(username="sup", password="x", role=User.Role.SUPERVISEUR)
        _, self.site, self.attached = make_client_site_form()
        self.mission = Mission.objects.create(
            superviseur=self.sup, site=self.site, attached_form=self.attached, created_by=self.validateur
        )
        self.visit = Visit.objects.create(
            mission=self.mission,
            auteur=self.sup,
            statut=Visit.Statut.SOUMISE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
            reponses={"nom_technicien": "Awa"},
        )

    def test_sans_permission_la_revue_est_refusee(self):
        self.client.force_login(self.manager_sans_droit)
        response = self.client.get(reverse("revue:list"))
        self.assertEqual(response.status_code, 403)

    def test_avec_permission_la_liste_affiche_la_visite(self):
        self.client.force_login(self.validateur)
        response = self.client.get(reverse("revue:list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.visit, response.context["visits"])

    def test_auto_validation_refusee(self):
        self.sup.user_permissions.add(self.permission)
        self.client.force_login(self.sup)
        response = self.client.post(reverse("revue:validate", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 403)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.SOUMISE)

    def test_auto_rejet_refuse(self):
        self.sup.user_permissions.add(self.permission)
        self.client.force_login(self.sup)
        response = self.client.post(
            reverse("revue:reject", args=[self.visit.pk]), {"commentaire": "à revoir"}
        )
        self.assertEqual(response.status_code, 403)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.SOUMISE)

    def test_validation_par_un_autre_utilisateur(self):
        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:validate", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.VALIDEE)
        self.assertEqual(self.visit.decision_par, self.validateur)
        self.assertIsNotNone(self.visit.decision_le)
        self.assertTrue(ActivityLog.objects.filter(action="validation_visite").exists())

    def test_rejet_sans_commentaire_est_refuse(self):
        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:reject", args=[self.visit.pk]), {"commentaire": "  "})
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.SOUMISE)
        self.assertFalse(ActivityLog.objects.filter(action="rejet_visite").exists())

    def test_rejet_avec_commentaire_renvoie_a_corriger(self):
        self.client.force_login(self.validateur)
        response = self.client.post(
            reverse("revue:reject", args=[self.visit.pk]), {"commentaire": "Photo manquante"}
        )
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.A_CORRIGER)
        self.assertEqual(self.visit.commentaire_rejet, "Photo manquante")
        self.assertTrue(ActivityLog.objects.filter(action="rejet_visite").exists())

    def test_superviseur_peut_reprendre_une_visite_a_corriger(self):
        self.visit.statut = Visit.Statut.A_CORRIGER
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.sup)
        self.client.get(reverse("visits:visit-start", args=[self.mission.pk]))

        self.assertEqual(Visit.objects.filter(mission=self.mission).count(), 1)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses, {"nom_technicien": "Awa"})

    def test_impossible_de_valider_une_visite_non_soumise(self):
        self.visit.statut = Visit.Statut.BROUILLON
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:validate", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 404)

    def test_visite_verrouillee_apres_validation(self):
        self.visit.statut = Visit.Statut.VALIDEE
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.sup)
        response = self.client.post(
            reverse("visits:visit-save", args=[self.visit.pk]), {"observations": "modif interdite"}
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["locked"])

    def test_publication_depuis_validee(self):
        self.visit.statut = Visit.Statut.VALIDEE
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:publish", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.PUBLIEE)

    def test_depublication_garde_la_visite_en_base(self):
        self.visit.statut = Visit.Statut.PUBLIEE
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:unpublish", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.DEPUBLIEE)
        self.assertTrue(Visit.objects.filter(pk=self.visit.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action="depublication_visite").exists())

    def test_republication_depuis_depubliee(self):
        self.visit.statut = Visit.Statut.DEPUBLIEE
        self.visit.save(update_fields=["statut"])

        self.client.force_login(self.validateur)
        response = self.client.post(reverse("revue:publish", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.statut, Visit.Statut.PUBLIEE)

    def test_publication_et_depublication_ne_touchent_pas_lauteur_de_validation(self):
        self.client.force_login(self.validateur)
        self.client.post(reverse("revue:validate", args=[self.visit.pk]))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.decision_par, self.validateur)
        valide_le = self.visit.decision_le

        self.client.post(reverse("revue:publish", args=[self.visit.pk]))
        self.client.post(reverse("revue:unpublish", args=[self.visit.pk]))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.decision_par, self.validateur)
        self.assertEqual(self.visit.decision_le, valide_le)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(dir=os.path.join(settings.BASE_DIR, "media")))
class ManagerPdfExportTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.sup = User.objects.create_user(username="sup", password="x", role=User.Role.SUPERVISEUR)
        self.client_obj, self.site, self.attached = make_client_site_form()
        self.mission = Mission.objects.create(
            superviseur=self.sup, site=self.site, attached_form=self.attached, created_by=self.manager
        )
        self.visit = Visit.objects.create(
            mission=self.mission,
            auteur=self.sup,
            statut=Visit.Statut.PUBLIEE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
            reponses={"nom_technicien": "Awa"},
        )
        self.client.force_login(self.manager)

    def test_pdf_dune_visite_publiee(self):
        response = self.client.get(reverse("visits:visit-pdf", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_refuse_pour_une_visite_non_publiee(self):
        self.visit.statut = Visit.Statut.BROUILLON
        self.visit.save(update_fields=["statut"])
        response = self.client.get(reverse("visits:visit-pdf", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 404)

    def test_export_site(self):
        response = self.client.get(reverse("visits:site-export", args=[self.client_obj.pk, self.site.pk]))
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(archive.namelist()), 1)

    def test_export_client(self):
        response = self.client.get(reverse("visits:client-export", args=[self.client_obj.pk]))
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(archive.namelist()), 1)

    def test_superviseur_ne_peut_pas_exporter(self):
        self.client.force_login(self.sup)
        response = self.client.get(reverse("visits:client-export", args=[self.client_obj.pk]))
        self.assertEqual(response.status_code, 403)


class VisitDetailTemplateAndPrivacyTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(nom="Client BNDA", actif=True)
        self.site = Site.objects.create(
            client=self.client_obj,
            code="BNDA-TEST",
            nom="Agence Test",
            ville="Bamako",
            quartier="ACI 2000",
            latitude="12.600000",
            longitude="-8.000000",
        )
        self.manager = User.objects.create_user(
            username="mgr_detail", password="x", role=User.Role.MANAGER
        )
        self.perm_validate = Permission.objects.get(codename="validate_visits")
        self.manager.user_permissions.add(self.perm_validate)

        self.sup = User.objects.create_user(
            username="sup_detail", password="x", role=User.Role.SUPERVISEUR
        )
        self.client_user = User.objects.create_user(
            username="cli_detail", password="x", role=User.Role.CLIENT, client=self.client_obj
        )

        # Schéma contenant tous les types de champs du seed (text, date, number, gps, photo, repeat, choice, signature, checkbox, multichoice)
        self.schema = {
            "sections": [
                {
                    "title": "Général",
                    "fields": [
                        {"key": "tech_nom", "label": "Nom du technicien", "type": "text", "required": True},
                        {"key": "date_visite", "label": "Date de la visite", "type": "date", "required": True},
                        {"key": "nb_equipements", "label": "Nombre d'équipements", "type": "number", "required": True},
                        {"key": "conforme", "label": "Installation conforme", "type": "checkbox", "required": False},
                        {"key": "options", "label": "Options installées", "type": "multichoice", "required": False},
                        {"key": "type_site", "label": "Type de site", "type": "choice", "options": ["Agence", "Guichet"], "required": True},
                        {"key": "champ_vide", "label": "Champ vide optionnel", "type": "text", "required": False},
                        {"key": "champ_manquant", "label": "Champ obligatoire manquant", "type": "text", "required": True},
                        {"key": "position_gps", "label": "Position GPS", "type": "gps", "required": True},
                        {"key": "photo_facade", "label": "Photo façade", "type": "photo", "max_photos": 2, "required": True},
                        {"key": "signature_tech", "label": "Signature technicien", "type": "signature", "required": False},
                    ],
                },
                {
                    "title": "Équipements",
                    "fields": [
                        {
                            "key": "cameras",
                            "label": "Liste des caméras",
                            "type": "repeat",
                            "required": True,
                            "fields": [
                                {"key": "marque", "label": "Marque", "type": "text", "required": True},
                                {"key": "etat", "label": "État", "type": "choice", "options": ["OK", "KO"], "required": True},
                                {"key": "photo_cam", "label": "Photo caméra", "type": "photo", "max_photos": 1, "required": False},
                            ],
                        }
                    ],
                },
            ]
        }

        self.template = FormTemplate.objects.create(
            nom="Formulaire Test Complet",
            schema=self.schema,
            actif=True,
        )
        self.attached = AttachedForm.objects.create(
            client=self.client_obj,
            template=self.template,
            nom="Formulaire Test Complet",
            schema=self.schema,
        )
        self.mission = Mission.objects.create(
            superviseur=self.sup,
            site=self.site,
            attached_form=self.attached,
            created_by=self.manager,
        )

    def test_visit_detail_renders_all_seed_field_types_and_repeat_table(self):
        # Création d'une visite avec coordonnées GPS à plus de 500m du site (ex. 12.610000 vs 12.600000 ~ 1.1 km)
        visit = Visit.objects.create(
            mission=self.mission,
            auteur=self.sup,
            statut=Visit.Statut.SOUMISE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
            gps_latitude="12.610000",
            gps_longitude="-8.000000",
            reponses={
                "tech_nom": "Amadou Traoré",
                "date_visite": "2026-10-20",
                "nb_equipements": 4,
                "conforme": True,
                "options": ["Alarme", "Onduleur"],
                "type_site": "Agence",
                "position_gps": {"lat": "12.610000", "lng": "-8.000000"},
                "signature_tech": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "cameras": [
                    {"_index": "0", "marque": "Hikvision", "etat": "OK"},
                    {"_index": "1", "marque": "Dahua", "etat": "KO"},
                ],
            },
            responsable_absent=True,
            motif_absence_responsable="En réunion externe",
            commentaire_rejet="Motif rejet interne confidentiel",
        )

        # Ajout d'une photo pour photo_facade
        from django.core.files.uploadedfile import SimpleUploadedFile
        tiny_gif = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04"
            b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        VisitPhoto.objects.create(
            visit=visit,
            field_key="photo_facade",
            image=SimpleUploadedFile("facade.gif", tiny_gif, content_type="image/gif"),
            legende="Vue de face",
        )

        # Ajout d'un ActivityLog
        from core.models import ActivityLog
        ActivityLog.objects.create(
            user=self.manager,
            action="rejet_visite",
            object_type="Visit",
            object_id=str(visit.pk),
            detail={"commentaire": "Motif rejet interne confidentiel"},
        )

        self.client.force_login(self.manager)
        response = self.client.get(reverse("revue:detail", args=[visit.pk]))
        self.assertEqual(response.status_code, 200)

        # Vérification en-tête et métadonnées
        self.assertContains(response, "Formulaire Test Complet")
        self.assertContains(response, "Agence Test")
        self.assertContains(response, "BNDA-TEST")
        self.assertContains(response, "ACI 2000")
        self.assertContains(response, "sup_detail")

        # Vérification types de champs simples
        self.assertContains(response, "Amadou Traoré") # text
        self.assertContains(response, "2026-10-20") # date
        self.assertContains(response, "4") # number
        self.assertContains(response, "Oui") # checkbox conforme
        self.assertContains(response, "Alarme") # multichoice
        self.assertContains(response, "Onduleur")
        self.assertContains(response, "Agence") # choice

        # Vérification GPS et lien carte
        self.assertContains(response, "12.610000, -8.000000")
        self.assertContains(response, "Voir sur la carte")

        # Vérification écart GPS > 500m
        self.assertContains(response, "Écart site")

        # Vérification champ vide affiché Non renseigné et obligatoire manquant signalé
        self.assertContains(response, "Non renseigné")
        self.assertContains(response, "Obligatoire manquant")

        # Vérification photo et légende
        self.assertContains(response, "Vue de face")

        # Vérification tableau du groupe répétable
        self.assertContains(response, "<table")
        self.assertContains(response, "Hikvision")
        self.assertContains(response, "Dahua")
        self.assertContains(response, "Marque")
        self.assertContains(response, "État")

        # Vérification signatures (responsable absent avec motif)
        self.assertContains(response, "Responsable absent")
        self.assertContains(response, "En réunion externe")

        # Vérification affichage historique interne pour le manager
        self.assertContains(response, "Historique interne")
        self.assertContains(response, "Motif rejet interne confidentiel")

    def test_client_never_sees_internal_history_or_rejection_comments(self):
        # Visite publiée pour consultation côté portail client
        visit = Visit.objects.create(
            mission=self.mission,
            auteur=self.sup,
            statut=Visit.Statut.PUBLIEE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
            reponses={"tech_nom": "Moussa Keita"},
            commentaire_rejet="Raison interne de rejet strictement confidentielle",
        )
        from core.models import ActivityLog
        ActivityLog.objects.create(
            user=self.manager,
            action="rejet_visite",
            object_type="Visit",
            object_id=str(visit.pk),
            detail={"commentaire": "Raison interne de rejet strictement confidentielle"},
        )
        ActivityLog.objects.create(
            user=self.manager,
            action="validation_visite",
            object_type="Visit",
            object_id=str(visit.pk),
            detail={"mission_id": self.mission.pk},
        )

        self.client.force_login(self.client_user)
        response = self.client.get(reverse("portal:visit-detail", args=[visit.pk]))
        self.assertEqual(response.status_code, 200)

        # Le client voit le contenu métier
        self.assertContains(response, "Moussa Keita")
        self.assertContains(response, "Formulaire Test Complet")

        # Le client ne doit JAMAIS voir l'historique interne ni les motifs de rejet
        self.assertNotContains(response, "Historique interne")
        self.assertNotContains(response, "Raison interne de rejet strictement confidentielle")
        self.assertNotContains(response, "rejet_visite")
        self.assertNotContains(response, "validation_visite")

    def test_manager_revue_htmx_detail_and_actions(self):
        visit = Visit.objects.create(
            mission=self.mission,
            auteur=self.sup,
            statut=Visit.Statut.SOUMISE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
            reponses={"tech_nom": "Issa"},
        )

        self.client.force_login(self.manager)

        # Requête HTMX : retourne le fragment _visit_detail.html
        response = self.client.get(
            reverse("revue:detail", args=[visit.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "visit-detail-container")
        self.assertContains(response, "Valider")
        self.assertContains(response, "Rejeter")
        self.assertNotContains(response, "<!DOCTYPE html>")

        # Requête normale : vue complète de revue
        response_full = self.client.get(reverse("revue:list"))
        self.assertEqual(response_full.status_code, 200)
        self.assertContains(response_full, "Revue des visites")
        self.assertContains(response_full, "revue-list-item")
        self.assertContains(response_full, "revue-detail")


class MissionFilteringAndPaginationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="mgr_mf", password="pass", role=User.Role.MANAGER)
        self.sup1 = User.objects.create_user(username="sup_mf1", password="pass", role=User.Role.SUPERVISEUR)
        self.sup2 = User.objects.create_user(username="sup_mf2", password="pass", role=User.Role.SUPERVISEUR)

        self.client_a = Client.objects.create(nom="Client Alpha")
        self.client_b = Client.objects.create(nom="Client Beta")

        self.site_a = Site.objects.create(client=self.client_a, code="S-A", nom="Site Alpha 1")
        self.site_b = Site.objects.create(client=self.client_b, code="S-B", nom="Site Beta 1")

        self.template = FormTemplate.objects.create(
            nom="Form Alpha",
            schema={"sections": [{"title": "S1", "fields": [{"key": "f1", "label": "Champ", "type": "text"}]}]},
            actif=True,
        )
        self.attached_a = AttachedForm.objects.create(
            client=self.client_a, template=self.template, nom="Form A", schema=self.template.schema, actif=True
        )
        self.attached_b = AttachedForm.objects.create(
            client=self.client_b, template=self.template, nom="Form B", schema=self.template.schema, actif=True
        )

        self.mission1 = Mission.objects.create(
            superviseur=self.sup1, site=self.site_a, attached_form=self.attached_a, created_by=self.manager
        )
        self.mission2 = Mission.objects.create(
            superviseur=self.sup2, site=self.site_b, attached_form=self.attached_b, created_by=self.manager
        )

    def test_filter_by_superviseur(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("visits:mission-list"), {"superviseur": self.sup1.pk})
        self.assertEqual(response.status_code, 200)
        missions = list(response.context["missions"])
        self.assertEqual(missions, [self.mission1])

    def test_filter_by_client(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("visits:mission-list"), {"client": self.client_b.pk})
        self.assertEqual(response.status_code, 200)
        missions = list(response.context["missions"])
        self.assertEqual(missions, [self.mission2])

    def test_filter_by_site(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("visits:mission-list"), {"site": self.site_a.pk})
        self.assertEqual(response.status_code, 200)
        missions = list(response.context["missions"])
        self.assertEqual(missions, [self.mission1])

    def test_filter_by_statut(self):
        self.client.force_login(self.manager)
        # mission1 has a submitted visit
        Visit.objects.create(
            mission=self.mission1,
            auteur=self.sup1,
            statut=Visit.Statut.SOUMISE,
            date_debut=timezone.now(),
            date_soumission=timezone.now(),
        )
        # Filter by statut=soumise
        response = self.client.get(reverse("visits:mission-list"), {"statut": "soumise"})
        self.assertEqual(response.status_code, 200)
        missions = list(response.context["missions"])
        self.assertEqual(missions, [self.mission1])

        # Filter by statut=non_commencee
        response_nc = self.client.get(reverse("visits:mission-list"), {"statut": "non_commencee"})
        self.assertEqual(response_nc.status_code, 200)
        missions_nc = list(response_nc.context["missions"])
        self.assertEqual(missions_nc, [self.mission2])

    def test_pagination_missions(self):
        self.client.force_login(self.manager)
        # Create additional missions to exceed 10
        for i in range(12):
            site = Site.objects.create(client=self.client_a, code=f"S-P{i}", nom=f"Site P{i}")
            Mission.objects.create(
                superviseur=self.sup1, site=site, attached_form=self.attached_a, created_by=self.manager
            )

        response = self.client.get(reverse("visits:mission-list"))
        self.assertEqual(response.status_code, 200)
        page_obj = response.context["missions"]
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertTrue(page_obj.has_next())

        # Page 2
        response_p2 = self.client.get(reverse("visits:mission-list"), {"page": 2})
        self.assertEqual(response_p2.status_code, 200)
        page_obj_p2 = response_p2.context["missions"]
        self.assertEqual(len(page_obj_p2.object_list), 4)
        self.assertFalse(page_obj_p2.has_next())
