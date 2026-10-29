"""Validation pure du schéma JSON d'un formulaire.

Schéma attendu :
    {"sections": [{"title": str, "fields": [field, ...]}, ...]}

Un champ est un objet avec au moins "key", "label", "type", "required".
Types supportés : text, number, choice, multichoice, checkbox, date, gps,
photo (label imposé + max_photos), signature, repeat (fields imbriqués,
non récursif).
"""

FIELD_TYPES = {
    "text",
    "number",
    "choice",
    "multichoice",
    "checkbox",
    "date",
    "time",
    "gps",
    "photo",
    "signature",
    "repeat",
}


def validate_schema(schema):
    """Retourne la liste des erreurs trouvées dans `schema` (vide si valide)."""

    if not isinstance(schema, dict):
        return ["Le schéma doit être un objet JSON."]

    sections = schema.get("sections")
    if not isinstance(sections, list) or not sections:
        return ["Le schéma doit contenir une liste 'sections' non vide."]

    errors = []
    seen_keys = set()
    for i, section in enumerate(sections):
        prefix = f"Section {i + 1}"
        if not isinstance(section, dict):
            errors.append(f"{prefix} : doit être un objet.")
            continue
        if not section.get("title") or not isinstance(section["title"], str):
            errors.append(f"{prefix} : 'title' requis.")

        fields = section.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"{prefix} : 'fields' doit être une liste non vide.")
            continue

        for j, field in enumerate(fields):
            errors.extend(
                _validate_field(field, f"{prefix} / champ {j + 1}", seen_keys, allow_repeat=True)
            )

    return errors


def _validate_field(field, label, seen_keys, allow_repeat):
    if not isinstance(field, dict):
        return [f"{label} : doit être un objet."]

    errors = []

    key = field.get("key")
    if not key or not isinstance(key, str):
        errors.append(f"{label} : 'key' requis.")
    elif key in seen_keys:
        errors.append(f"{label} : clé '{key}' dupliquée.")
    else:
        seen_keys.add(key)

    if not field.get("label") or not isinstance(field["label"], str):
        errors.append(f"{label} : 'label' requis.")

    if "required" in field and not isinstance(field["required"], bool):
        errors.append(f"{label} : 'required' doit être un booléen.")

    field_type = field.get("type")
    if not isinstance(field_type, str) or field_type not in FIELD_TYPES:
        errors.append(f"{label} : type '{field_type}' invalide.")
        return errors

    if field_type in ("choice", "multichoice"):
        options = field.get("options")
        if not isinstance(options, list) or not options:
            errors.append(f"{label} : 'options' requis pour un champ {field_type}.")

    if field_type == "photo":
        max_photos = field.get("max_photos")
        if not isinstance(max_photos, int) or isinstance(max_photos, bool) or max_photos < 1:
            errors.append(f"{label} : 'max_photos' doit être un entier >= 1.")
        minimum = field.get("min_photos", 1)
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
            errors.append(f"{label} : 'min_photos' doit être un entier >= 1.")
        elif isinstance(max_photos, int) and not isinstance(max_photos, bool) and minimum > max_photos:
            errors.append(f"{label} : 'min_photos' ne peut dépasser 'max_photos'.")

    if field_type == "repeat":
        if not allow_repeat:
            errors.append(f"{label} : un groupe répétable ne peut pas être imbriqué.")
        sub_fields = field.get("fields")
        if not isinstance(sub_fields, list) or not sub_fields:
            errors.append(f"{label} : un groupe répétable doit avoir 'fields'.")
        else:
            for k, sub in enumerate(sub_fields):
                errors.extend(
                    _validate_field(sub, f"{label} / sous-champ {k + 1}", seen_keys, allow_repeat=False)
                )

    return errors
