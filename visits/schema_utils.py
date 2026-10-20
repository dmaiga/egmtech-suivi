"""Aide à la correspondance entre le schéma JSON d'un formulaire attaché et les
champs POST d'une visite. Fonctions pures, sans dépendance à la requête HTTP.

Convention de nommage des champs POST :
- champ de premier niveau : son `key` directement, ex. "observations".
- champ dans un groupe répétable (ligne `index`) : "<group_key>__<index>__<sub_key>",
  ex. "cameras__0__marque". Un groupe répétable n'est jamais imbriqué (interdit par
  le validateur de schéma), donc deux niveaux suffisent toujours.
"""

import math
from django.urls import reverse

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
                is_empty = len(rows) == 0
                is_missing = field.get("required", False) and is_empty
                entries.append({
                    "kind": "repeat",
                    "field": field,
                    "name": key,
                    "rows": rows,
                    "is_empty": is_empty,
                    "is_missing": is_missing,
                })
            else:
                raw_val = reponses.get(key)
                val = _default_value(field, raw_val)
                entry = {
                    "kind": "field",
                    "field": field,
                    "name": key,
                    "value": val,
                }
                if field["type"] == "photo":
                    photos = photos_by_field.get(key, [])
                    entry["photos"] = photos
                    entry["is_empty"] = len(photos) == 0
                    entry["is_missing"] = field.get("required", False) and len(photos) == 0
                else:
                    entry["is_empty"] = _is_empty(raw_val)
                    entry["is_missing"] = field.get("required", False) and entry["is_empty"]
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
        raw_val = row.get(skey) if row else None
        value = _default_value(sub, raw_val)
        subentry = {"field": sub, "name": name, "value": value}
        if sub["type"] == "photo":
            photos = photos_by_field.get(name, [])
            subentry["photos"] = photos
            subentry["is_empty"] = len(photos) == 0
            subentry["is_missing"] = sub.get("required", False) and len(photos) == 0
        else:
            subentry["is_empty"] = _is_empty(raw_val)
            subentry["is_missing"] = sub.get("required", False) and subentry["is_empty"]
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


def haversine_distance(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux coordonnées GPS selon la formule de Haversine."""
    try:
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return None
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    r = 6371000  # Rayon terrestre en mètres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def get_visit_detail_context(visit, user=None, is_portal=False, show_revue_actions=False):
    """Prépare le contexte complet pour le template visits/_visit_detail.html."""
    mission = visit.mission
    site = mission.site
    client = site.client
    attached_form = mission.attached_form
    schema = attached_form.schema

    photos_by_field = {}
    photo_counts = {}
    for photo in visit.photos.all():
        photos_by_field.setdefault(photo.field_key, []).append(photo)
        photo_counts[photo.field_key] = photo_counts.get(photo.field_key, 0) + 1

    sections = build_render_model(schema, visit.reponses, photos_by_field)
    missing_required = find_missing_required(schema, visit.reponses, photo_counts)

    # Calcul d'écart GPS
    gps_distance = haversine_distance(
        visit.gps_latitude, visit.gps_longitude, site.latitude, site.longitude
    )
    gps_distance_warning = gps_distance is not None and gps_distance > 500
    gps_distance_display = ""
    if gps_distance is not None:
        if gps_distance >= 1000:
            gps_distance_display = f"{gps_distance / 1000:.1f} km"
        else:
            gps_distance_display = f"{int(round(gps_distance))} m"

    # Journal d'activité (historique interne)
    from core.models import ActivityLog
    activity_logs = (
        ActivityLog.objects.filter(object_type="Visit", object_id=str(visit.pk))
        .select_related("user")
        .order_by("created_at")
    )

    is_client_user = is_portal or (user and getattr(user, "is_client", lambda: False)())
    show_internal_history = not is_client_user

    can_download_pdf = False
    pdf_url = ""
    if visit.statut == "publiee":
        can_download_pdf = True
        try:
            if is_portal:
                pdf_url = reverse("portal:visit-pdf", args=[visit.pk])
            else:
                pdf_url = reverse("visits:visit-pdf", args=[visit.pk])
        except Exception:
            pdf_url = ""

    return {
        "visit": visit,
        "mission": mission,
        "site": site,
        "client": client,
        "attached_form": attached_form,
        "sections": sections,
        "missing_required": missing_required,
        "gps_distance": gps_distance,
        "gps_distance_warning": gps_distance_warning,
        "gps_distance_display": gps_distance_display,
        "activity_logs": activity_logs,
        "show_internal_history": show_internal_history,
        "can_download_pdf": can_download_pdf,
        "pdf_url": pdf_url,
        "is_portal": is_portal,
        "show_revue_actions": show_revue_actions,
    }

