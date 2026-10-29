import copy
import io
import json

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from clients.models import Client
from forms_cms.models import AttachedForm, FormTemplate


class BndaInstallationTests(TestCase):
    def test_command_creates_only_template_and_preserves_edits(self):
        self.assertFalse(Client.objects.filter(nom="BNDA").exists())
        call_command("installer_formulaire_bnda", stdout=io.StringIO())
        template = FormTemplate.objects.get(nom="Audit CCTV BNDA")
        self.assertFalse(Client.objects.filter(nom="BNDA").exists())
        self.assertFalse(AttachedForm.objects.filter(template=template).exists())
        template.description = "Modification EGMTECH"
        template.save()
        call_command("installer_formulaire_bnda", stdout=io.StringIO())
        template.refresh_from_db()
        self.assertEqual(template.description, "Modification EGMTECH")
        self.assertEqual(FormTemplate.objects.filter(nom="Audit CCTV BNDA").count(), 1)


class JsonEditorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin_editor", password="test-password-123")
        self.client.force_login(self.admin)
        call_command("installer_formulaire_bnda", stdout=io.StringIO())
        self.template = FormTemplate.objects.get(nom="Audit CCTV BNDA")

    def test_schema_round_trip_preserves_bnda_properties_and_attached_copy(self):
        client = Client.objects.create(nom="Banque")
        attached = AttachedForm.objects.create(client=client, template=self.template, nom=self.template.nom, schema=copy.deepcopy(self.template.schema))
        schema = copy.deepcopy(self.template.schema)
        schema["sections"][0]["title"] = "Identification du site"
        response = self.client.post(reverse("forms_cms:builder-edit", args=[self.template.pk]), {
            "nom": self.template.nom, "description": self.template.description,
            "action": "save", "schema_json": json.dumps(schema),
        })
        self.assertEqual(response.status_code, 302)
        self.template.refresh_from_db()
        attached.refresh_from_db()
        self.assertEqual(self.template.schema, schema)
        self.assertNotEqual(attached.schema["sections"][0]["title"], "Identification du site")
        fields = [f for section in schema["sections"] for f in section["fields"]]
        self.assertEqual(next(f for f in fields if f["key"] == "heure_audit")["type"], "time")
        self.assertEqual(next(f for f in fields if f["key"] == "photos_cameras")["min_photos"], 10)

    def test_invalid_json_is_rejected_without_modification(self):
        old = copy.deepcopy(self.template.schema)
        response = self.client.post(reverse("forms_cms:builder-edit", args=[self.template.pk]), {
            "nom": self.template.nom, "action": "save", "schema_json": "{invalid",
        })
        self.assertEqual(response.status_code, 200)
        self.template.refresh_from_db()
        self.assertEqual(self.template.schema, old)
        self.assertContains(response, "pas été enregistrées")
