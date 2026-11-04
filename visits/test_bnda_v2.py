import copy
import io
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from clients.models import Client, Site
from forms_cms.bnda_schema import bnda_schema, bnda_schema_v1
from forms_cms.models import AttachedForm, FormTemplate
from forms_cms.schema import validate_schema
from visits.models import Mission, Visit, VisitPhoto
from visits.schema_utils import find_missing_required, parse_responses

from .test_bnda_form import JPEG


def _schema_conditionnel(**condition):
    return {"sections": [{"title": "S", "fields": [
        {"key": "present", "label": "Présent ?", "type": "choice", "required": True, "options": ["Oui", "Non"]},
        {"key": "details", "label": "Détails", "type": "repeat", "required": True,
         "visible_si": condition or {"champ": "present", "valeur": "Oui"},
         "fields": [{"key": "marque", "label": "Marque", "type": "text", "required": True}]},
    ]}]}


class VisibleSiTests(SimpleTestCase):
    def test_schema_valide(self):
        self.assertEqual(validate_schema(_schema_conditionnel()), [])
        self.assertEqual(validate_schema(bnda_schema()), [])

    def test_condition_invalide_refusee(self):
        self.assertTrue(validate_schema(_schema_conditionnel(champ="inconnu", valeur="Oui")))
        self.assertTrue(validate_schema(_schema_conditionnel(champ="present", valeur="Peut-être")))
        schema = _schema_conditionnel()
        schema["sections"][0]["fields"].reverse()  # condition placée avant le champ visé
        self.assertTrue(validate_schema(schema))
        schema = _schema_conditionnel()
        schema["sections"][0]["fields"][1]["fields"][0]["visible_si"] = {"champ": "present", "valeur": "Oui"}
        self.assertTrue(validate_schema(schema))

    def test_champ_masque_ni_exige_ni_conserve(self):
        schema = _schema_conditionnel()
        self.assertEqual(find_missing_required(schema, {"present": "Non"}, {}), [])
        self.assertEqual(find_missing_required(schema, {"present": "Oui"}, {}), ["Détails"])
        post = QueryDict(mutable=True)
        post.update({"present": "Non", "details__indices": "0", "details__0__marque": "X"})
        self.assertEqual(parse_responses(post, schema)["details"], [])
        post["present"] = "Oui"
        self.assertEqual(parse_responses(post, schema)["details"], [{"_index": "0", "marque": "X"}])


class BndaV2VisitTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(dir=settings.BASE_DIR)
        self.addCleanup(storage.cleanup)
        override = override_settings(MEDIA_ROOT=storage.name)
        override.enable()
        self.addCleanup(override.disable)
        call_command("installer_formulaire_bnda", verbosity=0)
        template = FormTemplate.objects.get(nom="Audit CCTV BNDA")
        bank = Client.objects.create(nom="BNDA")
        form = AttachedForm.objects.create(client=bank, template=template, nom=template.nom, schema=template.schema)
        User = get_user_model()
        manager = User.objects.create_user("manager-v2", role="manager")
        self.auditor = User.objects.create_user("auditor-v2", role="superviseur")
        site = Site.objects.create(client=bank, code="T", nom="Test")
        mission = Mission.objects.create(site=site, superviseur=self.auditor, attached_form=form, created_by=manager)
        self.visit = Visit.objects.create(mission=mission, auteur=self.auditor)
        self.schema = form.schema
        self.client.force_login(self.auditor)

    def _manquants(self, reponses, photos):
        return [m for m in find_missing_required(self.schema, reponses, photos) if "Caméras" in m or "Périph" in m or "Zones critiques" in m]

    def test_trois_photos_minimum_par_camera(self):
        reponses = {"cameras": [{"_index": "0", "marque_camera": "Hikvision"}, {"_index": "1", "marque_camera": "Dahua"}],
                    "stockage_externe": "Non", "zones_critiques_presentes": "Non"}
        photos = {"cameras__0__photos_camera": 3, "cameras__1__photos_camera": 2}
        self.assertEqual(self._manquants(reponses, photos), ["Caméras du site (une ligne par marque) / Photos des caméras et de leurs étiquettes (minimum 3)"])
        photos["cameras__1__photos_camera"] = 3
        self.assertEqual(self._manquants(reponses, photos), [])

    def test_peripherique_et_zones_exiges_seulement_si_oui(self):
        base = {"cameras": [{"_index": "0", "marque_camera": "H"}]}
        photos = {"cameras__0__photos_camera": 3}
        self.assertEqual(self._manquants({**base, "stockage_externe": "Non", "zones_critiques_presentes": "Non"}, photos), [])
        manquants = self._manquants({**base, "stockage_externe": "Oui", "zones_critiques_presentes": "Oui"}, photos)
        self.assertEqual(manquants, ["Périphériques de stockage externe", "Zones critiques hors du champ des caméras"])
        # Photo du périphérique facultative, marque obligatoire.
        reponses = {**base, "stockage_externe": "Oui", "zones_critiques_presentes": "Non",
                    "peripheriques": [{"_index": "0", "marque_peripherique": "WD"}]}
        self.assertEqual(self._manquants(reponses, photos), [])

    def test_page_de_saisie_masque_les_blocs_conditionnels(self):
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertContains(response, 'class="js-conditional hidden" data-champ="stockage_externe" data-valeur="Oui"')
        self.assertContains(response, "visits/conditions.js")
        self.visit.reponses = {"stockage_externe": "Oui"}
        self.visit.save()
        response = self.client.get(reverse("visits:visit-edit", args=[self.visit.pk]))
        self.assertContains(response, 'class="js-conditional" data-champ="stockage_externe"')

    def test_photo_propre_a_chaque_peripherique(self):
        response = self.client.post(reverse("visits:visit-save", args=[self.visit.pk]), {
            "stockage_externe": "Oui", "peripheriques__indices": ["0", "1"],
            "peripheriques__0__marque_peripherique": "WD", "peripheriques__1__marque_peripherique": "Seagate",
            "peripheriques__1__photo_peripherique": SimpleUploadedFile("p.jpg", JPEG, content_type="image/jpeg"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.visit.photos.values_list("field_key", flat=True)), ["peripheriques__1__photo_peripherique"])


def _reponses_v1():
    return {
        "nombre_cameras": "12", "marques_cameras": "Hikvision, Dahua",
        "type_enregistrement": "NVR Hikvision", "slots_disque": "2",
        "stockage_externe": "Oui", "marque_stockage": "WD",
        "zones_surveillees": "Hall", "zones_critiques": "Arrière-cour", "observation_globale": "RAS",
    }


class MigrationBndaV2Tests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(dir=settings.BASE_DIR)
        self.addCleanup(storage.cleanup)
        override = override_settings(MEDIA_ROOT=storage.name)
        override.enable()
        self.addCleanup(override.disable)
        # État de la prod avant déploiement : modèle et copie attachée en v1.
        self.template = FormTemplate.objects.create(nom="Audit CCTV BNDA", schema=bnda_schema_v1())
        self.bank = Client.objects.create(nom="BNDA")
        schema_v1 = copy.deepcopy(bnda_schema_v1())
        schema_v1["sections"][0]["title"] = "Identification (retouchée)"
        self.form = AttachedForm.objects.create(client=self.bank, template=self.template, nom="Audit CCTV BNDA", schema=schema_v1)
        User = get_user_model()
        manager = User.objects.create_user("m", role="manager")
        self.auditor = User.objects.create_user("a", role="superviseur")
        site = Site.objects.create(client=self.bank, code="S", nom="Agence")
        self.mission = Mission.objects.create(site=site, superviseur=self.auditor, attached_form=self.form, created_by=manager)
        self.visit = Visit.objects.create(mission=self.mission, auteur=self.auditor, statut=Visit.Statut.VALIDEE, reponses=_reponses_v1())
        for key, n in (("photos_cameras", 10), ("photos_enregistreur", 3), ("photo_interieur", 1), ("photos_zones", 5), ("photos_baie", 1)):
            for i in range(n):
                VisitPhoto.objects.create(visit=self.visit, field_key=key, image=SimpleUploadedFile(f"{key}{i}.jpg", JPEG))
        # Un autre client avec un autre formulaire : ne doit pas bouger.
        autre = Client.objects.create(nom="Autre banque")
        autre_tpl = FormTemplate.objects.create(nom="Audit autre", schema=bnda_schema_v1())
        self.autre_form = AttachedForm.objects.create(client=autre, template=autre_tpl, nom="Audit autre", schema=bnda_schema_v1())
        autre_site = Site.objects.create(client=autre, code="X", nom="X")
        autre_mission = Mission.objects.create(site=autre_site, superviseur=self.auditor, attached_form=self.autre_form, created_by=manager)
        self.autre_visit = Visit.objects.create(mission=autre_mission, auteur=self.auditor, reponses=_reponses_v1())
        VisitPhoto.objects.create(visit=self.autre_visit, field_key="photos_cameras", image=SimpleUploadedFile("o.jpg", JPEG))

    def _run(self, *args):
        out = io.StringIO()
        call_command("migrer_bnda_v2", *args, stdout=out)
        return out.getvalue()

    def test_conversion_complete(self):
        out = self._run()
        self.assertIn("1 modèle(s), 1 formulaire(s) attaché(s), 1 visite(s) et 19 photo(s)", out)
        self.template.refresh_from_db()
        self.form.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.template.schema, bnda_schema())
        self.assertEqual(validate_schema(self.form.schema), [])
        self.assertEqual(self.form.schema["sections"][0]["title"], "Identification (retouchée)")
        r = self.visit.reponses
        self.assertEqual(r["cameras"], [{"_index": "0", "marque_camera": "Hikvision, Dahua"}])
        self.assertEqual(r["enregistreurs"], [{"_index": "0", "type_enregistreur": "NVR Hikvision", "slots_disque": "2"}])
        self.assertEqual(r["peripheriques"], [{"_index": "0", "marque_peripherique": "WD"}])
        self.assertEqual(r["zones_critiques_presentes"], "Oui")
        self.assertEqual(r["zones_critiques"], [{"_index": "0", "description_zone": "Arrière-cour"}])
        self.assertNotIn("marques_cameras", r)
        self.assertEqual(r["observation_globale"], "RAS")
        keys = {k: self.visit.photos.filter(field_key=k).count() for k in self.visit.photos.values_list("field_key", flat=True)}
        self.assertEqual(keys, {
            "cameras__0__photos_camera": 10, "enregistreurs__0__photos_enregistreur": 3,
            "enregistreurs__0__photo_interieur": 1, "zones_critiques__0__photos_zone": 5, "photos_baie": 1,
        })
        manquants = find_missing_required(self.form.schema, r, keys)
        self.assertFalse([m for m in manquants if "Caméras" in m or "Enregistreurs" in m or "Zones critiques" in m])

    def test_autre_client_intact(self):
        self._run()
        self.autre_form.refresh_from_db()
        self.autre_visit.refresh_from_db()
        self.assertEqual(self.autre_form.schema, bnda_schema_v1())
        self.assertEqual(self.autre_visit.reponses, _reponses_v1())
        self.assertTrue(self.autre_visit.photos.filter(field_key="photos_cameras").exists())

    def test_relancer_ne_change_rien(self):
        self._run()
        self.visit.refresh_from_db()
        avant = copy.deepcopy(self.visit.reponses)
        out = self._run()
        self.assertIn("0 modèle(s), 0 formulaire(s) attaché(s), 0 visite(s) et 0 photo(s)", out)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses, avant)

    def test_simulation_ne_modifie_rien(self):
        out = self._run("--dry-run")
        self.assertIn("simulation", out)
        self.form.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.form.schema["sections"][1]["fields"][1]["key"], "marques_cameras")
        self.assertEqual(self.visit.reponses, _reponses_v1())
        self.assertTrue(self.visit.photos.filter(field_key="photos_cameras").exists())

    def test_zones_aucune_sans_photo_devient_non(self):
        VisitPhoto.objects.filter(visit=self.visit, field_key="photos_zones").delete()
        self.visit.reponses = {**_reponses_v1(), "zones_critiques": "Aucune"}
        self.visit.save()
        self._run()
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.reponses["zones_critiques_presentes"], "Non")
        self.assertEqual(self.visit.reponses["zones_critiques"], [])

    def test_detail_et_pdf_apres_conversion(self):
        import io as _io
        from pypdf import PdfReader
        from visits.pdf import render_visit_pdf
        self._run()
        self.visit.refresh_from_db()
        text = "".join(p.extract_text() for p in PdfReader(_io.BytesIO(render_visit_pdf(self.visit))).pages)
        self.assertIn("Hikvision, Dahua", text)
        self.assertIn("NVR Hikvision", text)
        self.assertIn("Arrière-cour", text)
