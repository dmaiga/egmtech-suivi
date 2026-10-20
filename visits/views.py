from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from clients.models import Client, Site
from core.services import log
from forms_cms.models import AttachedForm

from .forms import MissionForm
from .models import Mission, Visit, VisitPhoto
from .schema_utils import (
    SEP,
    build_blank_row,
    build_render_model,
    find_missing_required,
    find_repeat_field,
    parse_responses,
    photo_label_for_field,
    photo_max_for_field,
    repeat_row_name,
)


def _is_manager(user):
    return user.is_superuser or user.is_manager()


@role_required(User.Role.MANAGER, User.Role.SUPERVISEUR)
def mission_list(request):
    if _is_manager(request.user):
        missions = Mission.objects.select_related(
            "superviseur", "site", "site__client", "attached_form"
        ).all()
        context = {
            "missions": missions,
            "is_manager_view": True,
            "form": MissionForm(),
            "clients": Client.objects.filter(actif=True),
        }
        return render(request, "visits/mission_list.html", context)

    missions = Mission.objects.filter(superviseur=request.user).select_related(
        "site", "site__client", "attached_form"
    )
    context = {"missions": missions, "is_manager_view": False}
    return render(request, "visits/mission_list.html", context)


@role_required(User.Role.MANAGER)
@require_POST
def mission_create(request):
    form = MissionForm(request.POST)
    if form.is_valid():
        mission = form.save(commit=False)
        mission.created_by = request.user
        mission.save()
        log(
            request.user,
            "creation_mission",
            mission,
            detail={"superviseur_id": mission.superviseur_id, "site_id": mission.site_id},
        )
        messages.success(request, "Mission créée.")
        return redirect("visits:mission-list")

    missions = Mission.objects.select_related(
        "superviseur", "site", "site__client", "attached_form"
    ).all()
    context = {
        "missions": missions,
        "is_manager_view": True,
        "form": form,
        "clients": Client.objects.filter(actif=True),
    }
    return render(request, "visits/mission_list.html", context, status=400)


@role_required(User.Role.MANAGER)
def mission_options(request):
    client_id = request.GET.get("client_id")
    sites = Site.objects.filter(client_id=client_id) if client_id else Site.objects.none()
    attached_forms = (
        AttachedForm.objects.filter(client_id=client_id, actif=True) if client_id else AttachedForm.objects.none()
    )
    return render(request, "visits/_mission_options.html", {"sites": sites, "attached_forms": attached_forms})


@role_required(User.Role.SUPERVISEUR)
def visit_start(request, mission_pk):
    mission = get_object_or_404(Mission, pk=mission_pk, superviseur=request.user)
    visit = (
        mission.visits.filter(statut__in=[Visit.Statut.BROUILLON, Visit.Statut.A_CORRIGER])
        .order_by("-date_debut")
        .first()
    )
    if visit is None:
        visit = Visit.objects.create(
            mission=mission, auteur=request.user, statut=Visit.Statut.BROUILLON, date_debut=timezone.now()
        )
        log(request.user, "debut_visite", visit, detail={"mission_id": mission.pk})
    return redirect("visits:visit-edit", pk=visit.pk)


def _visit_edit_context(visit, errors=None):
    schema = visit.mission.attached_form.schema
    photos_by_field = {}
    for photo in visit.photos.all():
        photos_by_field.setdefault(photo.field_key, []).append(photo)
    sections = build_render_model(schema, visit.reponses, photos_by_field)
    return {
        "visit": visit,
        "mission": visit.mission,
        "sections": sections,
        "max_photo_size_mb": settings.VISITS_MAX_PHOTO_SIZE_BYTES // (1024 * 1024),
        "errors": errors or [],
    }


def _render_visit_edit(request, visit, errors=None, status=200):
    return render(request, "visits/visit_edit.html", _visit_edit_context(visit, errors), status=status)


@role_required(User.Role.SUPERVISEUR)
def visit_edit(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    return render(request, "visits/visit_edit.html", _visit_edit_context(visit))


def _decode_data_url(data_url):
    if not data_url or "," not in data_url:
        return None
    header, _, b64 = data_url.partition(",")
    import base64

    try:
        raw = base64.b64decode(b64)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    ext = "png" if "png" in header else "jpg"
    return ContentFile(raw, name=f"signature.{ext}")


def _photo_field_names_in_post(schema, post_data):
    names = set()
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if field["type"] == "photo":
                names.add(field["key"])
            elif field["type"] == "repeat":
                for idx in post_data.getlist(f"{field['key']}{SEP}indices"):
                    for sub in field.get("fields", []):
                        if sub["type"] == "photo":
                            names.add(repeat_row_name(field["key"], idx, sub["key"]))
    return names


def _apply_submission(request, visit):
    """Applique le POST à la visite (réponses, photos, GPS, signatures).

    Retourne la liste des erreurs de fichiers (taille, quota) ; si non vide,
    rien n'a été enregistré.
    """

    schema = visit.mission.attached_form.schema
    reponses = parse_responses(request.POST, schema)

    existing_counts = Counter(visit.photos.values_list("field_key", flat=True))
    errors = []
    new_photos = []

    for field_key in _photo_field_names_in_post(schema, request.POST):
        files = request.FILES.getlist(field_key)
        if not files:
            continue

        max_photos = photo_max_for_field(schema, field_key)
        already = existing_counts.get(field_key, 0)
        if max_photos is not None and already + len(files) > max_photos:
            errors.append(
                f"Trop de photos pour « {photo_label_for_field(schema, field_key)} » (max {max_photos})."
            )
            continue

        for f in files:
            if f.size > settings.VISITS_MAX_PHOTO_SIZE_BYTES:
                max_mb = settings.VISITS_MAX_PHOTO_SIZE_BYTES // (1024 * 1024)
                errors.append(f"« {f.name} » dépasse la taille maximale de {max_mb} Mo.")
                continue
            new_photos.append((field_key, f))

    if errors:
        return errors

    visit.reponses = reponses

    lat = request.POST.get("gps_device_lat")
    lng = request.POST.get("gps_device_lng")
    if lat:
        visit.gps_latitude = lat
    if lng:
        visit.gps_longitude = lng

    signature_sup = _decode_data_url(request.POST.get("signature_superviseur_data", ""))
    if signature_sup:
        visit.signature_superviseur = signature_sup

    visit.responsable_absent = "responsable_absent" in request.POST
    visit.motif_absence_responsable = request.POST.get("motif_absence_responsable", "")
    if not visit.responsable_absent:
        signature_resp = _decode_data_url(request.POST.get("signature_responsable_data", ""))
        if signature_resp:
            visit.signature_responsable = signature_resp

    visit.save()

    for field_key, f in new_photos:
        VisitPhoto.objects.create(
            visit=visit,
            field_key=field_key,
            legende=photo_label_for_field(schema, field_key),
            image=f,
        )

    return []


@role_required(User.Role.SUPERVISEUR)
@require_POST
def visit_save(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    if not visit.peut_etre_modifiee():
        raise PermissionDenied

    errors = _apply_submission(request, visit)
    if errors:
        return _render_visit_edit(request, visit, errors=errors, status=400)

    messages.success(request, "Brouillon enregistré.")
    return redirect("visits:visit-edit", pk=visit.pk)


@role_required(User.Role.SUPERVISEUR)
@require_POST
def visit_submit(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    if not visit.peut_etre_modifiee():
        raise PermissionDenied

    errors = _apply_submission(request, visit)
    if errors:
        return _render_visit_edit(request, visit, errors=errors, status=400)

    schema = visit.mission.attached_form.schema
    photo_counts = Counter(visit.photos.values_list("field_key", flat=True))
    missing = find_missing_required(schema, visit.reponses, photo_counts)
    if not visit.signature_superviseur:
        missing.append("Signature du superviseur")

    if missing:
        errors = [f"Champ obligatoire manquant : {label}" for label in missing]
        return _render_visit_edit(request, visit, errors=errors, status=400)

    visit.statut = Visit.Statut.SOUMISE
    visit.date_soumission = timezone.now()
    visit.save(update_fields=["statut", "date_soumission"])
    log(request.user, "soumission_visite", visit, detail={"mission_id": visit.mission_id})
    messages.success(request, "Visite soumise.")
    return redirect("visits:mission-list")


@role_required(User.Role.SUPERVISEUR)
def repeat_row_add(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    schema = visit.mission.attached_form.schema
    group_key = request.GET.get("group")
    field = find_repeat_field(schema, group_key)
    if field is None:
        return render(request, "visits/_repeat_row.html", {"group_key": group_key, "row": None}, status=400)

    index = request.GET.get("index", "0")
    row = build_blank_row(field, index)
    return render(request, "visits/_repeat_row.html", {"group_key": group_key, "row": row})


@role_required(User.Role.SUPERVISEUR)
@require_POST
def repeat_row_remove(request):
    return render(request, "visits/_empty.html")


@role_required(User.Role.SUPERVISEUR)
@require_POST
def photo_delete(request, pk):
    photo = get_object_or_404(VisitPhoto, pk=pk, visit__auteur=request.user)
    if not photo.visit.peut_etre_modifiee():
        raise PermissionDenied
    visit_pk = photo.visit_id
    photo.delete()
    return redirect("visits:visit-edit", pk=visit_pk)
