"""Passe l'« Infrastructure CCTV » du formulaire BNDA à la version 2 (équipements en lignes).

Les formulaires attachés sont des copies figées : sans cette commande, les missions BNDA
existantes garderaient l'ancienne saisie (texte libre + photos à part). La commande met à
jour le modèle, chaque copie attachée encore en v1, et convertit les visites de ces copies
pour que rien ne soit perdu (ni texte, ni photo, y compris dans les PDF déjà validés) :

- « marques_cameras » + « photos_cameras »   -> ligne 1 du groupe « cameras »
- enregistreur (type, slots, photos, intérieur) -> ligne 1 du groupe « enregistreurs »
- « marque_stockage »                          -> ligne 1 du groupe « peripheriques »
- « zones_critiques » + « photos_zones »       -> « zones_critiques_presentes » + ligne 1

Seule la section CCTV est remplacée : les autres retouches faites au formulaire sont gardées.
Sans danger à relancer : ce qui est déjà en v2 n'est pas retouché.
"""

import copy

from django.core.management.base import BaseCommand
from django.db import transaction

from core.services import log
from forms_cms.bnda_schema import bnda_schema
from forms_cms.models import AttachedForm, FormTemplate
from visits.models import Visit, VisitPhoto
from visits.schema_utils import repeat_row_name

MARQUEUR_V1 = "marques_cameras"

# Ancienne clé photo -> (groupe, sous-champ) de la ligne 1.
PHOTOS = {
    "photos_cameras": ("cameras", "photos_camera"),
    "photos_enregistreur": ("enregistreurs", "photos_enregistreur"),
    "photo_interieur": ("enregistreurs", "photo_interieur"),
    "photos_zones": ("zones_critiques", "photos_zone"),
}


def _section_cctv_v2():
    return copy.deepcopy(next(s for s in bnda_schema()["sections"] if s["title"] == "Infrastructure CCTV"))


def est_v1(schema):
    return any(f.get("key") == MARQUEUR_V1 for s in schema.get("sections", []) for f in s.get("fields", []))


def convertir_schema(schema):
    """Remplace les champs de la section qui contient l'ancien champ « marques ». Rend un nouveau dict."""

    schema = copy.deepcopy(schema)
    for section in schema.get("sections", []):
        if any(f.get("key") == MARQUEUR_V1 for f in section.get("fields", [])):
            section["fields"] = _section_cctv_v2()["fields"]
    return schema


def _texte(valeur):
    return valeur.strip() if isinstance(valeur, str) else ("" if valeur is None else str(valeur))


def convertir_reponses(reponses, cles_photos):
    """Convertit les réponses v1 d'une visite. `cles_photos` : clés photo présentes pour cette visite."""

    r = dict(reponses or {})
    if "cameras" in r and MARQUEUR_V1 not in r:
        return r  # déjà converties

    marques = _texte(r.pop("marques_cameras", ""))
    r["cameras"] = (
        [{"_index": "0", "marque_camera": marques}] if marques or "photos_cameras" in cles_photos else []
    )

    type_enr = _texte(r.pop("type_enregistrement", ""))
    slots = r.pop("slots_disque", "")
    a_photos_enr = bool({"photos_enregistreur", "photo_interieur"} & cles_photos)
    r["enregistreurs"] = (
        [{"_index": "0", "type_enregistreur": type_enr, "slots_disque": slots}]
        if type_enr or _texte(slots) or a_photos_enr else []
    )

    marque_stockage = _texte(r.pop("marque_stockage", ""))
    r["peripheriques"] = [{"_index": "0", "marque_peripherique": marque_stockage}] if marque_stockage else []
    if marque_stockage and not r.get("stockage_externe"):
        r["stockage_externe"] = "Oui"

    zones = _texte(r.pop("zones_critiques", ""))
    signalees = bool(zones) and not zones.lower().startswith("aucun")
    if signalees or "photos_zones" in cles_photos:
        r["zones_critiques_presentes"] = "Oui"
        r["zones_critiques"] = [{"_index": "0", "description_zone": zones}]
    else:
        r["zones_critiques_presentes"] = "Non" if zones else ""
        r["zones_critiques"] = []
    return r


class Command(BaseCommand):
    help = "Met le formulaire BNDA (modèle, copies attachées, visites) en version 2 pour la section CCTV."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait fait, sans rien enregistrer.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        with transaction.atomic():
            modeles = 0
            for template in FormTemplate.objects.filter(nom="Audit CCTV BNDA"):
                if est_v1(template.schema):
                    template.schema = convertir_schema(template.schema)
                    template.full_clean()
                    template.save(update_fields=["schema", "updated_at"])
                    modeles += 1

            copies, visites, photos = 0, 0, 0
            attaches = AttachedForm.objects.filter(template__nom="Audit CCTV BNDA").select_related("client")
            for attached in attaches:
                if not est_v1(attached.schema):
                    continue
                attached.schema = convertir_schema(attached.schema)
                attached.save(update_fields=["schema"])
                log(None, "migration_formulaire_bnda_v2", attached, detail={"client_id": attached.client_id})
                copies += 1
                for visit in Visit.objects.filter(mission__attached_form=attached):
                    cles = set(visit.photos.values_list("field_key", flat=True))
                    visit.reponses = convertir_reponses(visit.reponses, cles)
                    visit.save(update_fields=["reponses"])
                    visites += 1
                    for ancienne, (groupe, sous_cle) in PHOTOS.items():
                        photos += VisitPhoto.objects.filter(visit=visit, field_key=ancienne).update(
                            field_key=repeat_row_name(groupe, "0", sous_cle)
                        )

            resume = (
                f"{modeles} modèle(s), {copies} formulaire(s) attaché(s), "
                f"{visites} visite(s) et {photos} photo(s) converti(e)s."
            )
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING(f"[simulation, rien enregistré] {resume}"))
            else:
                self.stdout.write(self.style.SUCCESS(resume))
