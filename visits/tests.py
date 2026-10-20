import base64
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from clients.models import Client, Site
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
