import copy

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from clients.models import Client, Site

from .models import AttachedForm, FormTemplate
from .schema import validate_schema
from .services import attach_template_to_client, set_expected_visits, toggle_attached_form

VALID_SCHEMA = {
    "sections": [
        {
            "title": "Identification",
            "fields": [
                {"key": "nom", "label": "Nom", "type": "text", "required": True},
            ],
        }
    ]
}


class ValidateSchemaTests(TestCase):
    def test_schema_valide(self):
        self.assertEqual(validate_schema(VALID_SCHEMA), [])

    def test_schema_doit_etre_un_objet(self):
        self.assertTrue(validate_schema(["pas", "un", "objet"]))

    def test_sections_manquantes(self):
        self.assertTrue(validate_schema({}))

    def test_champ_sans_key(self):
        schema = {"sections": [{"title": "S", "fields": [{"label": "Nom", "type": "text"}]}]}
        errors = validate_schema(schema)
        self.assertTrue(any("key" in e for e in errors))

    def test_key_dupliquee(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [
                        {"key": "x", "label": "A", "type": "text"},
                        {"key": "x", "label": "B", "type": "text"},
                    ],
                }
            ]
        }
        errors = validate_schema(schema)
        self.assertTrue(any("dupliquée" in e for e in errors))

    def test_type_invalide(self):
        schema = {"sections": [{"title": "S", "fields": [{"key": "x", "label": "A", "type": "inconnu"}]}]}
        errors = validate_schema(schema)
        self.assertTrue(any("invalide" in e for e in errors))

    def test_choice_sans_options(self):
        schema = {"sections": [{"title": "S", "fields": [{"key": "x", "label": "A", "type": "choice"}]}]}
        errors = validate_schema(schema)
        self.assertTrue(any("options" in e for e in errors))

    def test_photo_sans_max_photos(self):
        schema = {"sections": [{"title": "S", "fields": [{"key": "x", "label": "A", "type": "photo"}]}]}
        errors = validate_schema(schema)
        self.assertTrue(any("max_photos" in e for e in errors))

    def test_photo_valide(self):
        schema = {
            "sections": [
                {"title": "S", "fields": [{"key": "x", "label": "A", "type": "photo", "max_photos": 2}]}
            ]
        }
        self.assertEqual(validate_schema(schema), [])

    def test_repeat_valide(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [
                        {
                            "key": "groupe",
                            "label": "Groupe",
                            "type": "repeat",
                            "fields": [{"key": "sous", "label": "Sous-champ", "type": "text"}],
                        }
                    ],
                }
            ]
        }
        self.assertEqual(validate_schema(schema), [])

    def test_repeat_sans_fields(self):
        schema = {
            "sections": [{"title": "S", "fields": [{"key": "groupe", "label": "Groupe", "type": "repeat"}]}]
        }
        errors = validate_schema(schema)
        self.assertTrue(any("fields" in e for e in errors))

    def test_repeat_imbrique_refuse(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [
                        {
                            "key": "groupe",
                            "label": "Groupe",
                            "type": "repeat",
                            "fields": [
                                {
                                    "key": "sous_groupe",
                                    "label": "Sous-groupe",
                                    "type": "repeat",
                                    "fields": [{"key": "a", "label": "A", "type": "text"}],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        errors = validate_schema(schema)
        self.assertTrue(any("imbriqué" in e for e in errors))


class AttachedFormCopyTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.client_obj = Client.objects.create(nom="Client A")
        self.template = FormTemplate.objects.create(
            nom="Rapport", schema=copy.deepcopy(VALID_SCHEMA), actif=True
        )

    def test_copie_figee_a_lattachement(self):
        attached = attach_template_to_client(self.manager, self.client_obj, self.template)
        self.assertEqual(attached.schema, VALID_SCHEMA)

    def test_modifier_le_template_ne_change_pas_la_copie(self):
        attached = attach_template_to_client(self.manager, self.client_obj, self.template)

        self.template.schema = {
            "sections": [
                {"title": "Autre", "fields": [{"key": "y", "label": "Y", "type": "number"}]}
            ]
        }
        self.template.save()

        attached.refresh_from_db()
        self.assertEqual(attached.schema, VALID_SCHEMA)

    def test_desactiver_attached_form(self):
        attached = attach_template_to_client(self.manager, self.client_obj, self.template)
        self.assertTrue(attached.actif)

        toggle_attached_form(self.manager, attached)
        attached.refresh_from_db()
        self.assertFalse(attached.actif)

        toggle_attached_form(self.manager, attached)
        attached.refresh_from_db()
        self.assertTrue(attached.actif)


class ExpectedVisitsTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.client_obj = Client.objects.create(nom="Client A")
        self.site = Site.objects.create(client=self.client_obj, code="S1", nom="Site 1")
        self.template = FormTemplate.objects.create(nom="Rapport", schema=copy.deepcopy(VALID_SCHEMA))
        self.attached = attach_template_to_client(self.manager, self.client_obj, self.template)

    def test_creation_prevision(self):
        expected = set_expected_visits(self.manager, self.attached, self.site, 3)
        self.assertEqual(expected.nombre_prevu, 3)

    def test_mise_a_jour_prevision(self):
        set_expected_visits(self.manager, self.attached, self.site, 3)
        expected = set_expected_visits(self.manager, self.attached, self.site, 5)
        self.assertEqual(expected.nombre_prevu, 5)
        self.assertEqual(self.attached.expected_visits.count(), 1)


class ManageFormsPermissionTests(TestCase):
    def setUp(self):
        self.manager_sans_droit = User.objects.create_user(
            username="manager1", password="x", role=User.Role.MANAGER
        )
        self.manager_avec_droit = User.objects.create_user(
            username="manager2", password="x", role=User.Role.MANAGER
        )
        permission = Permission.objects.get(codename="manage_forms")
        self.manager_avec_droit.user_permissions.add(permission)

    def test_manager_sans_permission_est_refuse(self):
        self.client.force_login(self.manager_sans_droit)
        response = self.client.get(reverse("forms_cms:list"))
        self.assertEqual(response.status_code, 403)

    def test_manager_avec_permission_voit_lecran(self):
        self.client.force_login(self.manager_avec_droit)
        response = self.client.get(reverse("forms_cms:list"))
        self.assertEqual(response.status_code, 200)

    def test_anonyme_redirige_vers_connexion(self):
        response = self.client.get(reverse("forms_cms:list"))
        self.assertEqual(response.status_code, 302)
