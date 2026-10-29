import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from clients.models import Client, Site
from forms_cms.models import AttachedForm, FormTemplate
from visits.models import Mission, Visit, VisitPhoto


class PrivateMediaTests(TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.storage.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        users = get_user_model()
        self.manager = users.objects.create_user("manager", role="manager")
        self.auditor = users.objects.create_user("auditor", role="superviseur")
        self.other_auditor = users.objects.create_user("other", role="superviseur")
        client = Client.objects.create(nom="Banque test")
        other_client = Client.objects.create(nom="Autre banque")
        self.client_user = users.objects.create_user("client", role="client", client=client)
        self.other_user = users.objects.create_user("other_client", role="client", client=other_client)
        site = Site.objects.create(client=client, code="1", nom="Site")
        template = FormTemplate.objects.create(nom="Test", schema={})
        attached = AttachedForm.objects.create(client=client, template=template, nom="Test", schema={})
        mission = Mission.objects.create(site=site, attached_form=attached, superviseur=self.auditor, created_by=self.manager)
        self.visit = Visit.objects.create(mission=mission, auteur=self.auditor)
        self.photo = VisitPhoto.objects.create(visit=self.visit, field_key="photo", image=SimpleUploadedFile("photo.jpg", b"test", content_type="image/jpeg"))

    def test_access_respects_visit_owner_client_and_publication(self):
        url = self.photo.image.url
        self.assertEqual(self.client.get(url).status_code, 302)
        for user, status in [(self.manager, 200), (self.auditor, 200), (self.other_auditor, 404), (self.client_user, 404), (self.other_user, 404)]:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, status)
            response.close()
        self.visit.statut = Visit.Statut.PUBLIEE
        self.visit.save()
        self.client.force_login(self.client_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(url).status_code, 404)
