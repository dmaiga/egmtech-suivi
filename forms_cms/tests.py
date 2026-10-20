import copy

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from clients.models import Client, Site

from .builder import apply_action, parse_builder_form
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


class BuilderFunctionsTests(TestCase):
    """L'éditeur (sans glisser-déposer) : reconstruction du POST et actions de mutation."""

    def test_parse_builder_form_reconstruit_le_schema(self):
        post = {
            "nom": "Mon formulaire",
            "description": "Une description",
            "template_pk": "",
            "section_count": "1",
            "section__0__title": "Identification",
            "field_count__0": "2",
            "field__0__0__key": "nom",
            "field__0__0__label": "Nom",
            "field__0__0__type": "text",
            "field__0__0__required": "on",
            "field__0__1__key": "etat",
            "field__0__1__label": "État",
            "field__0__1__type": "choice",
            "field__0__1__options": "Bon\nMauvais\n",
        }
        parsed = parse_builder_form(post)
        self.assertEqual(parsed["nom"], "Mon formulaire")
        self.assertEqual(
            parsed["schema"],
            {
                "sections": [
                    {
                        "title": "Identification",
                        "fields": [
                            {"key": "nom", "label": "Nom", "type": "text", "required": True},
                            {
                                "key": "etat",
                                "label": "État",
                                "type": "choice",
                                "required": False,
                                "options": ["Bon", "Mauvais"],
                            },
                        ],
                    }
                ]
            },
        )

    def test_parse_builder_form_groupe_repetable(self):
        post = {
            "nom": "F",
            "description": "",
            "template_pk": "",
            "section_count": "1",
            "section__0__title": "Caméras",
            "field_count__0": "1",
            "field__0__0__key": "cameras",
            "field__0__0__label": "Caméras",
            "field__0__0__type": "repeat",
            "sub_count__0__0": "1",
            "subfield__0__0__0__key": "marque",
            "subfield__0__0__0__label": "Marque",
            "subfield__0__0__0__type": "text",
            "subfield__0__0__0__required": "on",
        }
        parsed = parse_builder_form(post)
        field = parsed["schema"]["sections"][0]["fields"][0]
        self.assertEqual(field["type"], "repeat")
        self.assertEqual(
            field["fields"], [{"key": "marque", "label": "Marque", "type": "text", "required": True}]
        )

    def test_parse_builder_form_auto_generates_key_from_label_when_omitted(self):
        post = {
            "nom": "Formulaire sans clés manuelles",
            "section_count": "1",
            "section__0__title": "Mesures",
            "field_count__0": "3",
            "field__0__0__key": "",
            "field__0__0__label": "Tension d'alimentation (V)",
            "field__0__0__type": "number",
            "field__0__1__key": "",
            "field__0__1__label": "Tension d'alimentation (V)",
            "field__0__1__type": "number",
            "field__0__2__key": "",
            "field__0__2__label": "État du coffret",
            "field__0__2__type": "text",
        }
        parsed = parse_builder_form(post)
        fields = parsed["schema"]["sections"][0]["fields"]
        self.assertEqual(fields[0]["key"], "tension_dalimentation_v")
        self.assertEqual(fields[1]["key"], "tension_dalimentation_v_2")
        self.assertEqual(fields[2]["key"], "etat_du_coffret")

    def test_add_section(self):
        schema = {"sections": []}
        apply_action(schema, "add_section")
        self.assertEqual(len(schema["sections"]), 1)
        self.assertEqual(schema["sections"][0], {"title": "", "fields": []})

    def test_remove_section(self):
        schema = {"sections": [{"title": "A", "fields": []}, {"title": "B", "fields": []}]}
        apply_action(schema, "remove_section:0")
        self.assertEqual(schema["sections"], [{"title": "B", "fields": []}])

    def test_move_section_up(self):
        schema = {"sections": [{"title": "A", "fields": []}, {"title": "B", "fields": []}]}
        apply_action(schema, "move_section:1:up")
        self.assertEqual([s["title"] for s in schema["sections"]], ["B", "A"])

    def test_move_section_hors_limites_ne_fait_rien(self):
        schema = {"sections": [{"title": "A", "fields": []}]}
        apply_action(schema, "move_section:0:up")
        self.assertEqual([s["title"] for s in schema["sections"]], ["A"])

    def test_add_field_lit_le_type_depuis_le_post(self):
        schema = {"sections": [{"title": "S", "fields": []}]}
        apply_action(schema, "add_field:0", {"new_field_type__0": "number"})
        self.assertEqual(schema["sections"][0]["fields"][0]["type"], "number")

    def test_remove_field(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [
                        {"key": "a", "label": "A", "type": "text", "required": False},
                        {"key": "b", "label": "B", "type": "text", "required": False},
                    ],
                }
            ]
        }
        apply_action(schema, "remove_field:0:0")
        self.assertEqual([f["key"] for f in schema["sections"][0]["fields"]], ["b"])

    def test_move_field_down(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [
                        {"key": "a", "label": "A", "type": "text", "required": False},
                        {"key": "b", "label": "B", "type": "text", "required": False},
                    ],
                }
            ]
        }
        apply_action(schema, "move_field:0:0:down")
        self.assertEqual([f["key"] for f in schema["sections"][0]["fields"]], ["b", "a"])

    def test_add_subfield_et_remove_subfield(self):
        schema = {
            "sections": [
                {
                    "title": "S",
                    "fields": [{"key": "cameras", "label": "Caméras", "type": "repeat", "required": False, "fields": []}],
                }
            ]
        }
        apply_action(schema, "add_subfield:0:0", {"new_subfield_type__0__0": "photo"})
        self.assertEqual(len(schema["sections"][0]["fields"][0]["fields"]), 1)
        self.assertEqual(schema["sections"][0]["fields"][0]["fields"][0]["type"], "photo")

        apply_action(schema, "remove_subfield:0:0:0")
        self.assertEqual(schema["sections"][0]["fields"][0]["fields"], [])


class FormBuilderViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="x", role=User.Role.MANAGER)
        self.manager.user_permissions.add(Permission.objects.get(codename="manage_forms"))
        self.client.force_login(self.manager)

    def _base_post(self, **overrides):
        data = {
            "template_pk": "",
            "nom": "Rapport",
            "description": "",
            "section_count": "1",
            "section__0__title": "Identification",
            "field_count__0": "1",
            "field__0__0__key": "nom",
            "field__0__0__label": "Nom",
            "field__0__0__type": "text",
            "field__0__0__required": "on",
            "new_field_type__0": "text",
        }
        data.update(overrides)
        return data

    def test_sans_permission_lediteur_est_refuse(self):
        manager_sans_droit = User.objects.create_user(username="sans_droit", password="x", role=User.Role.MANAGER)
        self.client.force_login(manager_sans_droit)
        response = self.client.get(reverse("forms_cms:builder-new"))
        self.assertEqual(response.status_code, 403)

    def test_enregistrer_produit_un_schema_valide(self):
        response = self.client.post(
            reverse("forms_cms:builder-new"), self._base_post(action="save"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        template = FormTemplate.objects.get(nom="Rapport")
        self.assertEqual(validate_schema(template.schema), [])
        self.assertEqual(
            template.schema,
            {
                "sections": [
                    {
                        "title": "Identification",
                        "fields": [{"key": "nom", "label": "Nom", "type": "text", "required": True}],
                    }
                ]
            },
        )

    def test_enregistrer_sans_nom_est_refuse(self):
        response = self.client.post(reverse("forms_cms:builder-new"), self._base_post(nom="", action="save"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FormTemplate.objects.filter(nom="").exists())

    def test_enregistrer_un_schema_invalide_est_refuse(self):
        # Un champ "choice" sans options n'est pas un schéma valide.
        response = self.client.post(
            reverse("forms_cms:builder-new"),
            self._base_post(**{"field__0__0__type": "choice", "action": "save"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FormTemplate.objects.filter(nom="Rapport").exists())

    def test_apercu_naffecte_rien_en_base(self):
        self.client.post(reverse("forms_cms:builder-new"), self._base_post(action="preview"))
        self.assertFalse(FormTemplate.objects.filter(nom="Rapport").exists())

    def test_modification_dun_formulaire_naffecte_jamais_les_copies_attachees(self):
        template = FormTemplate.objects.create(
            nom="Rapport",
            schema={
                "sections": [
                    {"title": "Identification", "fields": [{"key": "nom", "label": "Nom", "type": "text", "required": True}]}
                ]
            },
            actif=True,
        )
        client_obj = Client.objects.create(nom="Client A")
        attached = attach_template_to_client(self.manager, client_obj, template)
        schema_au_moment_de_lattachement = copy.deepcopy(attached.schema)

        response = self.client.post(
            reverse("forms_cms:builder-edit", args=[template.pk]),
            self._base_post(
                template_pk=str(template.pk),
                **{"field__0__0__label": "Nom complet", "action": "save"},
            ),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        template.refresh_from_db()
        attached.refresh_from_db()
        self.assertEqual(template.schema["sections"][0]["fields"][0]["label"], "Nom complet")
        self.assertEqual(attached.schema, schema_au_moment_de_lattachement)
        self.assertNotEqual(attached.schema, template.schema)


class TemplatePreviewAndToggleTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="mgr_prev", password="pass", role=User.Role.MANAGER)
        self.perm_manage = Permission.objects.get(codename="manage_forms")
        self.manager.user_permissions.add(self.perm_manage)

        self.sup = User.objects.create_user(username="sup_prev", password="pass", role=User.Role.SUPERVISEUR)
        self.client_a = Client.objects.create(nom="Client Prev")
        self.client_user = User.objects.create_user(
            username="cli_prev", password="pass", role=User.Role.CLIENT, client=self.client_a
        )

        self.template = FormTemplate.objects.create(
            nom="Audit Sécurité",
            description="Audit complet des sites",
            schema={
                "sections": [
                    {
                        "title": "Infos Générales",
                        "fields": [
                            {"key": "site_resp", "label": "Responsable", "type": "texte_court", "required": True},
                            {"key": "alarme_ok", "label": "Alarme en service", "type": "case"},
                        ],
                    }
                ]
            },
            actif=True,
        )

    def test_manager_with_perm_can_view_preview(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("forms_cms:template-preview", args=[self.template.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit Sécurité")
        self.assertContains(response, "Infos Générales")
        self.assertContains(response, "Responsable")
        self.assertContains(response, "Mode aperçu")

    def test_superviseur_cannot_access_preview(self):
        self.client.force_login(self.sup)
        response = self.client.get(reverse("forms_cms:template-preview", args=[self.template.pk]))
        self.assertEqual(response.status_code, 403)

    def test_client_cannot_access_preview(self):
        self.client.force_login(self.client_user)
        response = self.client.get(reverse("forms_cms:template-preview", args=[self.template.pk]))
        self.assertEqual(response.status_code, 403)

    def test_toggle_deactivates_and_reactivates_with_messages(self):
        self.client.force_login(self.manager)

        # Toggle to inactive
        response = self.client.post(reverse("forms_cms:template-toggle", args=[self.template.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.template.refresh_from_db()
        self.assertFalse(self.template.actif)
        self.assertContains(response, "désactivé")

        # Toggle back to active
        response2 = self.client.post(reverse("forms_cms:template-toggle", args=[self.template.pk]), follow=True)
        self.assertEqual(response2.status_code, 200)
        self.template.refresh_from_db()
        self.assertTrue(self.template.actif)
        self.assertContains(response2, "activé")

    def test_template_list_renders_status_badge_and_preview_link(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("forms_cms:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit Sécurité")
        self.assertContains(response, "Actif")
        self.assertContains(response, reverse("forms_cms:template-preview", args=[self.template.pk]))
        self.assertContains(response, "Désactiver")
