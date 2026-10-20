"""Éditeur de schéma sans glisser-déposer : reconstruction + mutation pures,
testables indépendamment de la vue. Convention de nommage des champs POST :

- "section_count", puis pour chaque section i : "section__{i}__title" et
  "field_count__{i}".
- Pour chaque champ j de la section i, préfixe "field__{i}__{j}__" : key,
  label, type, required, options (une par ligne), max_photos.
- Si ce champ est un groupe répétable : "sub_count__{i}__{j}" puis, pour
  chaque sous-champ k, préfixe "subfield__{i}__{j}__{k}__" (mêmes attributs,
  jamais de type "repeat").
"""

import re
from django.utils.text import slugify

FIELD_TYPE_LABELS = {
    "text": "Texte",
    "number": "Nombre",
    "choice": "Choix unique",
    "multichoice": "Choix multiple",
    "checkbox": "Case à cocher",
    "date": "Date",
    "gps": "Position GPS",
    "photo": "Photo",
    "signature": "Signature",
    "repeat": "Groupe répétable",
}

# Un sous-champ de groupe répétable ne peut pas être lui-même un groupe répétable.
SUBFIELD_TYPE_LABELS = {k: v for k, v in FIELD_TYPE_LABELS.items() if k != "repeat"}

TYPES_WITH_OPTIONS = {"choice", "multichoice"}
TYPES_WITH_MAX_PHOTOS = {"photo"}


def _get_int(data, name, default=0):
    try:
        return int(data.get(name, default))
    except (TypeError, ValueError):
        return default


def _parse_simple_field(data, prefix):
    ftype = data.get(f"{prefix}__type", "text")
    field = {
        "key": data.get(f"{prefix}__key", "").strip(),
        "label": data.get(f"{prefix}__label", "").strip(),
        "type": ftype,
        "required": f"{prefix}__required" in data,
    }
    if ftype in TYPES_WITH_OPTIONS:
        raw = data.get(f"{prefix}__options", "")
        field["options"] = [line.strip() for line in raw.splitlines() if line.strip()]
    if ftype in TYPES_WITH_MAX_PHOTOS:
        raw_max = data.get(f"{prefix}__max_photos", "").strip()
        if raw_max:
            try:
                field["max_photos"] = int(raw_max)
            except ValueError:
                field["max_photos"] = raw_max
        else:
            field["max_photos"] = raw_max
    return field


def generate_key_from_label(label, existing_keys=None, fallback_prefix="champ"):
    """Génère un identifiant technique 'key' valide et unique à partir du libellé."""
    if existing_keys is None:
        existing_keys = set()

    slug = slugify(label or "", allow_unicode=False).replace("-", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug).strip("_")
    if not slug:
        slug = fallback_prefix

    slug = slug[:40].rstrip("_") or fallback_prefix
    candidate = slug
    counter = 2
    while candidate in existing_keys:
        candidate = f"{slug}_{counter}"
        counter += 1

    existing_keys.add(candidate)
    return candidate


def parse_builder_form(post_data):
    """Reconstruit l'état complet du formulaire (nom, description, schéma) depuis un POST.
    Si la clé d'un champ est vide ou omise par l'utilisateur, elle est générée automatiquement
    depuis son libellé en backend."""

    section_count = _get_int(post_data, "section_count", 0)
    sections = []
    seen_keys = set()
    for i in range(section_count):
        title = post_data.get(f"section__{i}__title", "").strip()
        field_count = _get_int(post_data, f"field_count__{i}", 0)
        fields = []
        for j in range(field_count):
            field = _parse_simple_field(post_data, f"field__{i}__{j}")
            if not field["key"] and field["label"]:
                field["key"] = generate_key_from_label(
                    field["label"], seen_keys, fallback_prefix=f"champ_{i + 1}_{j + 1}"
                )
            if field["key"]:
                seen_keys.add(field["key"])

            if field["type"] == "repeat":
                sub_count = _get_int(post_data, f"sub_count__{i}__{j}", 0)
                sub_fields = []
                sub_seen_keys = set()
                for k in range(sub_count):
                    sub = _parse_simple_field(post_data, f"subfield__{i}__{j}__{k}")
                    if not sub["key"] and sub["label"]:
                        sub["key"] = generate_key_from_label(
                            sub["label"], sub_seen_keys, fallback_prefix=f"sous_champ_{k + 1}"
                        )
                    if sub["key"]:
                        sub_seen_keys.add(sub["key"])
                    sub_fields.append(sub)
                field["fields"] = sub_fields
            fields.append(field)
        sections.append({"title": title, "fields": fields})

    return {
        "nom": post_data.get("nom", "").strip(),
        "description": post_data.get("description", "").strip(),
        "template_pk": post_data.get("template_pk", "").strip(),
        "schema": {"sections": sections},
    }


def _blank_field(ftype):
    field = {"key": "", "label": "", "type": ftype, "required": False}
    if ftype in TYPES_WITH_OPTIONS:
        field["options"] = []
    if ftype in TYPES_WITH_MAX_PHOTOS:
        field["max_photos"] = 1
    if ftype == "repeat":
        field["fields"] = []
    return field


def _move(items, index, direction):
    target = index - 1 if direction == "up" else index + 1
    if 0 <= index < len(items) and 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]


def apply_action(schema, action, post_data=None):
    """Mute `schema["sections"]` selon l'action (chaîne "verbe:arg1:arg2:..."). Pas d'effet pour
    une action inconnue, absente ou de type "save"/"preview" (déjà traitées par l'appelant).

    `post_data` : le POST complet, utilisé pour lire le type choisi dans les sélecteurs
    "new_field_type__{i}" / "new_subfield_type__{i}__{j}" lors d'un ajout (évite d'avoir à
    encoder ce choix dans l'action elle-même, donc aucun JavaScript n'est nécessaire côté
    gabarit pour "Ajouter un champ")."""

    post_data = post_data or {}
    sections = schema["sections"]
    parts = action.split(":")
    verb = parts[0]

    if verb == "add_section":
        sections.append({"title": "", "fields": []})
    elif verb == "remove_section":
        i = int(parts[1])
        if 0 <= i < len(sections):
            del sections[i]
    elif verb == "move_section":
        _move(sections, int(parts[1]), parts[2])
    elif verb == "add_field":
        i = int(parts[1])
        ftype = post_data.get(f"new_field_type__{i}", "text")
        if 0 <= i < len(sections):
            sections[i]["fields"].append(_blank_field(ftype))
    elif verb == "remove_field":
        i, j = int(parts[1]), int(parts[2])
        if 0 <= i < len(sections) and 0 <= j < len(sections[i]["fields"]):
            del sections[i]["fields"][j]
    elif verb == "move_field":
        i, j, direction = int(parts[1]), int(parts[2]), parts[3]
        if 0 <= i < len(sections):
            _move(sections[i]["fields"], j, direction)
    elif verb == "add_subfield":
        i, j = int(parts[1]), int(parts[2])
        ftype = post_data.get(f"new_subfield_type__{i}__{j}", "text")
        if 0 <= i < len(sections) and 0 <= j < len(sections[i]["fields"]):
            sections[i]["fields"][j].setdefault("fields", []).append(_blank_field(ftype))
    elif verb == "remove_subfield":
        i, j, k = int(parts[1]), int(parts[2]), int(parts[3])
        if 0 <= i < len(sections) and 0 <= j < len(sections[i]["fields"]):
            sub_fields = sections[i]["fields"][j].get("fields", [])
            if 0 <= k < len(sub_fields):
                del sub_fields[k]
    elif verb == "move_subfield":
        i, j, k, direction = int(parts[1]), int(parts[2]), int(parts[3]), parts[4]
        if 0 <= i < len(sections) and 0 <= j < len(sections[i]["fields"]):
            _move(sections[i]["fields"][j].get("fields", []), k, direction)


def annotate_for_render(schema):
    """Décore le schéma d'index de position, pour que le template puisse construire les noms
    de champs et les actions monter/descendre/supprimer sans logique en plus."""

    sections = []
    for i, section in enumerate(schema["sections"]):
        fields = []
        for j, field in enumerate(section["fields"]):
            entry = {
                "index": j,
                "field": field,
                "options_text": "\n".join(field.get("options", [])),
                "is_last": j == len(section["fields"]) - 1,
            }
            if field["type"] == "repeat":
                sub_fields = field.get("fields", [])
                entry["subfields"] = [
                    {
                        "index": k,
                        "field": sub,
                        "options_text": "\n".join(sub.get("options", [])),
                        "is_last": k == len(sub_fields) - 1,
                    }
                    for k, sub in enumerate(sub_fields)
                ]
            fields.append(entry)
        sections.append(
            {
                "index": i,
                "title": section["title"],
                "fields": fields,
                "is_last": i == len(schema["sections"]) - 1,
            }
        )
    return sections
