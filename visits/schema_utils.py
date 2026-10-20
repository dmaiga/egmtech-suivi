"""Aide à la correspondance entre le schéma JSON d'un formulaire attaché et les
champs POST d'une visite. Fonctions pures, sans dépendance à la requête HTTP.

Convention de nommage des champs POST :
- champ de premier niveau : son `key` directement, ex. "observations".
- champ dans un groupe répétable (ligne `index`) : "<group_key>__<index>__<sub_key>",
  ex. "cameras__0__marque". Un groupe répétable n'est jamais imbriqué (interdit par
  le validateur de schéma), donc deux niveaux suffisent toujours.
"""

SEP = "__"


def repeat_row_name(group_key, index, sub_key):
    return f"{group_key}{SEP}{index}{SEP}{sub_key}"


def find_top_field(schema, key):
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if field.get("key") == key:
                return field
    return None


def find_repeat_field(schema, group_key):
    field = find_top_field(schema, group_key)
    return field if field and field.get("type") == "repeat" else None


def parse_responses(post_data, schema):
    """Construit le dict de réponses (hors photos) à partir d'un POST, selon le schéma."""

    reponses = {}
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            key = field["key"]
            ftype = field["type"]

            if ftype == "photo":
                continue

            if ftype == "repeat":
                indices = post_data.getlist(f"{key}{SEP}indices")
                rows = []
                for idx in indices:
                    row = {"_index": idx}
                    for sub in field.get("fields", []):
                        skey = sub["key"]
                        stype = sub["type"]
                        if stype == "photo":
                            continue
                        name = repeat_row_name(key, idx, skey)
                        row[skey] = _read_value(post_data, name, stype)
                    rows.append(row)
                reponses[key] = rows
            else:
                reponses[key] = _read_value(post_data, key, ftype)
    return reponses


def _read_value(post_data, name, ftype):
    if ftype == "multichoice":
        return post_data.getlist(name)
    if ftype == "checkbox":
        return name in post_data
    if ftype == "gps":
        return {"lat": post_data.get(f"{name}{SEP}lat", ""), "lng": post_data.get(f"{name}{SEP}lng", "")}
    if ftype == "signature":
        return post_data.get(name, "")
    return post_data.get(name, "")


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, dict):
        return not any(str(v).strip() for v in value.values())
    return False


def find_missing_required(schema, reponses, photo_counts):
    """Retourne la liste des libellés de champs obligatoires non remplis.

    `photo_counts` : dict field_key -> nombre de photos déjà associées, avec le
    même format de clé que VisitPhoto.field_key (voir module docstring).
    """

    missing = []
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            key = field["key"]
            ftype = field["type"]
            required = field.get("required", False)

            if ftype == "repeat":
                rows = reponses.get(key) or []
                if required and not rows:
                    missing.append(field["label"])
                    continue
                for row in rows:
                    row_index = row.get("_index")
                    for sub in field.get("fields", []):
                        if not sub.get("required"):
                            continue
                        skey = sub["key"]
                        if sub["type"] == "photo":
                            name = repeat_row_name(key, row_index, skey)
                            if photo_counts.get(name, 0) < 1:
                                missing.append(f"{field['label']} / {sub['label']}")
                        elif _is_empty(row.get(skey)):
                            missing.append(f"{field['label']} / {sub['label']}")
                continue

            if not required:
                continue

            if ftype == "photo":
                if photo_counts.get(key, 0) < 1:
                    missing.append(field["label"])
            elif _is_empty(reponses.get(key)):
                missing.append(field["label"])

    return missing


def photo_max_for_field(schema, field_key):
    parts = field_key.split(SEP)
    if len(parts) == 1:
        field = find_top_field(schema, parts[0])
        if field and field.get("type") == "photo":
            return field.get("max_photos")
        return None
    if len(parts) == 3:
        group_key, _idx, subkey = parts
        group = find_repeat_field(schema, group_key)
        if not group:
            return None
        for sub in group.get("fields", []):
            if sub["key"] == subkey and sub["type"] == "photo":
                return sub.get("max_photos")
    return None


def build_render_model(schema, reponses, photos_by_field=None):
    """Transforme le schéma + les réponses en structure prête à être itérée par le template.

    `photos_by_field` : dict field_key -> liste de VisitPhoto, attachée aux entrées photo.
    """

    photos_by_field = photos_by_field or {}
    sections = []
    for section in schema.get("sections", []):
        entries = []
        for field in section.get("fields", []):
            key = field["key"]
            if field["type"] == "repeat":
                rows = []
                for row in reponses.get(key) or []:
                    idx = row.get("_index")
                    rows.append(_build_row_entry(field, idx, row, photos_by_field))
                entries.append({"kind": "repeat", "field": field, "name": key, "rows": rows})
            else:
                entry = {
                    "kind": "field",
                    "field": field,
                    "name": key,
                    "value": _default_value(field, reponses.get(key)),
                }
                if field["type"] == "photo":
                    entry["photos"] = photos_by_field.get(key, [])
                entries.append(entry)
        sections.append({"title": section.get("title"), "entries": entries})
    return sections


def _default_value(field, value):
    if value is not None:
        return value
    if field["type"] == "multichoice":
        return []
    if field["type"] == "gps":
        return {}
    return value


def _build_row_entry(field, index, row, photos_by_field):
    subentries = []
    for sub in field.get("fields", []):
        skey = sub["key"]
        name = repeat_row_name(field["key"], index, skey)
        value = _default_value(sub, row.get(skey) if row else None)
        subentry = {"field": sub, "name": name, "value": value}
        if sub["type"] == "photo":
            subentry["photos"] = photos_by_field.get(name, [])
        subentries.append(subentry)
    return {"index": index, "subentries": subentries}


def build_blank_row(field, index, photos_by_field=None):
    return _build_row_entry(field, index, None, photos_by_field or {})


def photo_label_for_field(schema, field_key):
    parts = field_key.split(SEP)
    if len(parts) == 1:
        field = find_top_field(schema, parts[0])
        return field["label"] if field else field_key
    if len(parts) == 3:
        group_key, _idx, subkey = parts
        group = find_repeat_field(schema, group_key)
        if group:
            for sub in group.get("fields", []):
                if sub["key"] == subkey:
                    return sub["label"]
    return field_key
