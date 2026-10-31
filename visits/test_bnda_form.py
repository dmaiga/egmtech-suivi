from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.core.management import call_command
import tempfile
from django.test import override_settings
from django.conf import settings

from clients.models import Client, Site
from forms_cms.models import AttachedForm, FormTemplate
from forms_cms.schema import validate_schema
from visits.models import Mission, Visit
from visits.schema_utils import find_missing_required



def _jpeg_minuscule():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (8, 8), "gray").save(buf, "JPEG")
    return buf.getvalue()


JPEG = _jpeg_minuscule()

class PhotoMinimumTests(SimpleTestCase):
    def test_minimum_is_checked_when_submitting(self):
        schema = {"sections": [{"title": "Photos", "fields": [
            {"key": "photos", "label": "Photos", "type": "photo", "required": True,
             "min_photos": 3, "max_photos": 6},
        ]}]}
        self.assertEqual(validate_schema(schema), [])
        self.assertEqual(find_missing_required(schema, {}, {"photos": 2}), ["Photos"])
        self.assertEqual(find_missing_required(schema, {}, {"photos": 3}), [])

    def test_minimum_must_not_exceed_maximum(self):
        schema = {"sections": [{"title": "Photos", "fields": [
            {"key": "photos", "label": "Photos", "type": "photo",
             "min_photos": 4, "max_photos": 3},
        ]}]}
        self.assertTrue(validate_schema(schema))


class BndaVisitFlowTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(dir=settings.BASE_DIR)
        self.addCleanup(storage.cleanup)
        override = override_settings(MEDIA_ROOT=storage.name)
        override.enable()
        self.addCleanup(override.disable)
        call_command("installer_formulaire_bnda", verbosity=0)
        self.bank = Client.objects.create(nom="BNDA")
        template = FormTemplate.objects.get(nom="Audit CCTV BNDA")
        self.form = AttachedForm.objects.create(client=self.bank, template=template, nom=template.nom, schema=template.schema)
        self.manager = get_user_model().objects.create_user("manager-bnda", role="manager")
        self.auditor = get_user_model().objects.create_user("auditor-bnda", role="superviseur")
        self.site = Site.objects.create(client=self.bank, code="TEST", nom="Test")
        self.mission = Mission.objects.create(site=self.site, superviseur=self.auditor, attached_form=self.form, created_by=self.manager)
        self.client.force_login(self.auditor)
        self.client.get(reverse("visits:visit-start", args=[self.mission.pk]))
        self.visit = Visit.objects.get(mission=self.mission)

    def test_first_view_is_neutral_and_hour_has_time_control(self):
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertNotContains(response, "Ce champ obligatoire doit être renseigné.")
        self.assertContains(response, 'type="time" id="id_heure_audit"')
        self.assertEqual(self.visit.created_by, self.auditor)
        self.assertIsNotNone(self.visit.created_at)

    def test_failed_submission_preserves_responses_and_valid_photos(self):
        files = [SimpleUploadedFile(f"photo{i}.jpg", JPEG, content_type="image/jpeg") for i in range(7)]
        response = self.client.post(reverse("visits:visit-submit", args=[self.visit.pk]), {
            "auditeur": "Auditeur terrain", "heure_audit": "14:35", "photos_enregistreur": files,
        })
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses["auditeur"], "Auditeur terrain")
        self.assertEqual(self.visit.reponses["heure_audit"], "14:35")
        self.assertEqual(self.visit.photos.filter(field_key="photos_enregistreur").count(), 7)
        self.assertContains(response, "Ce champ obligatoire doit être renseigné.", status_code=400)

    def test_file_error_does_not_discard_text(self):
        with override_settings(VISITS_MAX_PHOTO_SIZE_BYTES=2):
            response = self.client.post(reverse("visits:visit-save", args=[self.visit.pk]), {
                "auditeur": "Texte conservé", "photos_enregistreur": SimpleUploadedFile("photo.jpg", JPEG),
            })
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses["auditeur"], "Texte conservé")

    def test_wizard_step_saves_draft_without_required_fields(self):
        response = self.client.post(reverse("visits:visit-save", args=[self.visit.pk]), {"auditeur": "Awa", "wizard_step": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("step=1", response.url)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses["auditeur"], "Awa")
        self.assertEqual(self.visit.statut, Visit.Statut.BROUILLON)

    @override_settings(VISITS_MAX_PHOTOS_PER_VISIT=2)
    def test_photo_limit_is_shared_across_all_fields(self):
        url = reverse("visits:visit-save", args=[self.visit.pk])
        response = self.client.post(url, {
            "auditeur": "Awa",
            "photos_cameras": SimpleUploadedFile("camera.jpg", JPEG, content_type="image/jpeg"),
            "photos_baie": SimpleUploadedFile("baie.jpg", JPEG, content_type="image/jpeg"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.visit.photos.count(), 2)
        response = self.client.post(url, {
            "auditeur": "Awa Diallo",
            "photos_enregistreur": SimpleUploadedFile("enregistreur.jpg", JPEG, content_type="image/jpeg"),
        })
        self.assertContains(response, "plus de 2 photos au total", status_code=400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.photos.count(), 2)
        self.assertEqual(self.visit.reponses["auditeur"], "Awa Diallo")

    def test_photo_counter_is_global_not_repeated_for_each_field(self):
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertContains(response, "Photos enregistrées pour cette visite", count=1)
        self.assertNotContains(response, "js-photo-counter")

    def test_camera_and_gallery_are_available_and_multiple_photos_are_saved(self):
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertContains(response, 'capture="environment"')
        self.assertContains(response, "js-photo-camera")
        self.assertContains(response, "Choisir dans la galerie")
        files = [SimpleUploadedFile("camera1.jpg", JPEG, content_type="image/jpeg"),
                 SimpleUploadedFile("camera2.jpg", JPEG, content_type="image/jpeg")]
        response = self.client.post(reverse("visits:visit-save", args=[self.visit.pk]), {"photos_cameras": files})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.visit.photos.filter(field_key="photos_cameras").count(), 2)

    def test_pdf_with_multiple_photos_is_generated(self):
        import io
        from PIL import Image
        from pypdf import PdfReader
        from visits.pdf import render_visit_pdf
        from visits.models import VisitPhoto
        data = io.BytesIO()
        Image.new("RGB", (100, 80), "blue").save(data, format="JPEG")
        for index in range(7):
            VisitPhoto.objects.create(visit=self.visit, field_key="photos_cameras", legende=f"Caméra {index}",
                                      image=SimpleUploadedFile(f"photo{index}.jpg", data.getvalue(), content_type="image/jpeg"))
        pdf = render_visit_pdf(self.visit)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertGreaterEqual(len(reader.pages), 2)
        self.assertIn("Caméra 0", "".join(page.extract_text() for page in reader.pages))
        self.assertTrue(any(len(page.images) for page in reader.pages))
