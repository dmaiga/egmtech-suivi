from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from clients.models import Client, Site
from core.images import optimiser_image
from core.services import log
from forms_cms.models import AttachedForm

from .decorators import validate_visits_required
from .forms import MissionForm
from . import echanges as echanges_service
from .models import Echange, Mission, Visit, VisitPhoto
from .pdf import (
    build_visits_zip,
    render_visit_pdf,
    visit_pdf_filename,
    zip_filename_for_client,
    zip_filename_for_site,
)
from .schema_utils import (
    SEP,
    build_blank_row,
    build_render_model,
    find_missing_required,
    find_repeat_field,
    get_visit_detail_context,
    parse_responses,
    photo_label_for_field,
    photo_max_for_field,
    repeat_row_name,
)


def _is_manager(user):
    return user.is_superuser or user.is_manager()


@role_required(User.Role.MANAGER, User.Role.SUPERVISEUR)
def mission_list(request):
    is_manager = _is_manager(request.user)
    if is_manager:
        missions_qs = Mission.objects.select_related(
            "superviseur", "site", "site__client", "attached_form"
        )
    else:
        missions_qs = Mission.objects.filter(superviseur=request.user).select_related(
            "site", "site__client", "attached_form"
        )

    superviseur_id = request.GET.get("superviseur")
    client_id = request.GET.get("client")
    site_id = request.GET.get("site")
    statut = request.GET.get("statut")

    if superviseur_id and is_manager:
        missions_qs = missions_qs.filter(superviseur_id=superviseur_id)
    if client_id:
        missions_qs = missions_qs.filter(site__client_id=client_id)
    if site_id:
        missions_qs = missions_qs.filter(site_id=site_id)
    if statut:
        if statut == "non_commencee":
            missions_qs = missions_qs.filter(visits__isnull=True)
        elif statut in [s[0] for s in Visit.Statut.choices]:
            missions_qs = missions_qs.filter(visits__statut=statut)

    if not is_manager:
        has_a_corriger = Exists(
            Visit.objects.filter(mission=OuterRef("pk"), statut=Visit.Statut.A_CORRIGER)
        )
        missions_qs = missions_qs.annotate(has_a_corriger=has_a_corriger).order_by(
            "-has_a_corriger", "-created_at"
        )
        tri = "-created_at"
    else:
        tri = request.GET.get("tri", "-created_at")
        tri_map = {
            "-created_at": ["-created_at"],
            "created_at": ["created_at"],
            "superviseur": ["superviseur__last_name", "superviseur__first_name", "superviseur__username"],
            "-superviseur": ["-superviseur__last_name", "-superviseur__first_name", "-superviseur__username"],
            "client": ["site__client__nom", "site__nom"],
            "-client": ["-site__client__nom", "-site__nom"],
            "site": ["site__nom"],
            "-site": ["-site__nom"],
            "formulaire": ["attached_form__nom"],
            "-formulaire": ["-attached_form__nom"],
        }
        order_fields = tri_map.get(tri, ["-created_at"])
        missions_qs = missions_qs.order_by(*order_fields)

    missions_qs = missions_qs.distinct().prefetch_related(
        Prefetch(
            "visits",
            queryset=Visit.objects.order_by("-date_debut", "-id"),
            to_attr="ordered_visits",
        )
    )

    paginator = Paginator(missions_qs, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    for m in page_obj.object_list:
        m.latest_visit = m.ordered_visits[0] if getattr(m, "ordered_visits", None) else None

    context = {
        "missions": page_obj,
        "page_obj": page_obj,
        "is_manager_view": is_manager,
        "current_tri": tri,
        "filter_superviseur": superviseur_id or "",
        "filter_client": client_id or "",
        "filter_site": site_id or "",
        "filter_statut": statut or "",
        "statut_choices": Visit.Statut.choices,
        "clients_filter": Client.objects.filter(actif=True) if is_manager else Client.objects.filter(sites__missions__superviseur=request.user).distinct(),
        "sites_filter": Site.objects.all() if is_manager else Site.objects.filter(missions__superviseur=request.user).distinct(),
    }

    if is_manager:
        context["superviseurs"] = User.objects.filter(role=User.Role.SUPERVISEUR, is_active=True)
        context["form"] = MissionForm()
        context["clients"] = Client.objects.filter(actif=True)
    else:
        missions_a_corriger = []
        missions_a_faire = []
        missions_soumises = []
        for m in page_obj.object_list:
            lv = m.latest_visit
            if lv and lv.statut == Visit.Statut.A_CORRIGER:
                missions_a_corriger.append(m)
            elif not lv or lv.statut == Visit.Statut.BROUILLON:
                missions_a_faire.append(m)
            else:
                missions_soumises.append(m)
        context["missions_a_corriger"] = missions_a_corriger
        context["missions_a_faire"] = missions_a_faire
        context["missions_soumises"] = missions_soumises

    return render(request, "visits/mission_list.html", context)


@role_required(User.Role.MANAGER)
def mission_create(request):
    if request.method == "POST":
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
            messages.success(request, "Mission créée avec succès.")
            return redirect("visits:mission-list")
        status_code = 400
    else:
        form = MissionForm()
        status_code = 200

    selected_client_id = request.POST.get("client_id") if request.method == "POST" else None
    if selected_client_id:
        sites = Site.objects.filter(client_id=selected_client_id)
        attached_forms = AttachedForm.objects.filter(client_id=selected_client_id, actif=True)
    elif form.is_bound and form.data.get("site"):
        site_obj = Site.objects.filter(pk=form.data.get("site")).first()
        if site_obj:
            selected_client_id = str(site_obj.client_id)
            sites = Site.objects.filter(client_id=site_obj.client_id)
            attached_forms = AttachedForm.objects.filter(client_id=site_obj.client_id, actif=True)
        else:
            sites = Site.objects.none()
            attached_forms = AttachedForm.objects.none()
    else:
        sites = Site.objects.none()
        attached_forms = AttachedForm.objects.none()

    context = {
        "form": form,
        "superviseurs": User.objects.filter(role=User.Role.SUPERVISEUR, is_active=True),
        "clients": Client.objects.filter(actif=True),
        "selected_client_id": selected_client_id,
        "sites": sites,
        "attached_forms": attached_forms,
    }
    return render(request, "visits/mission_form.html", context, status=status_code)


@role_required(User.Role.MANAGER)
def mission_options(request):
    client_id = request.GET.get("client_id")
    sites = Site.objects.filter(client_id=client_id) if client_id else Site.objects.none()
    attached_forms = (
        AttachedForm.objects.filter(client_id=client_id, actif=True) if client_id else AttachedForm.objects.none()
    )
    return render(request, "visits/_mission_options.html", {"sites": sites, "attached_forms": attached_forms})


@role_required(User.Role.MANAGER)
def mission_form_detail(request, pk):
    attached = get_object_or_404(AttachedForm.objects.select_related("client"), pk=pk)
    return render(request, "visits/attached_form_detail.html", {"attached": attached, "sections": attached.schema.get("sections", [])})


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
            mission=mission, auteur=request.user, created_by=request.user, statut=Visit.Statut.BROUILLON, date_debut=timezone.now()
        )
        log(request.user, "debut_visite", visit, detail={"mission_id": mission.pk})
    return redirect("visits:visit-edit", pk=visit.pk)


def _visit_edit_context(visit, errors=None, user=None, show_validation_errors=False):
    ctx = get_visit_detail_context(visit, user=user)

    sections = ctx.get("sections", [])
    total_sections = len(sections)
    completed_sections = 0
    for section in sections:
        entries = section.get("entries", [])
        has_missing = any(entry.get("is_missing") for entry in entries)
        has_any_filled = any(not entry.get("is_empty") for entry in entries)
        is_comp = (not has_missing) and (has_any_filled or len(entries) == 0)
        section["is_completed"] = is_comp
        if is_comp:
            completed_sections += 1

    progress_percent = int(round((completed_sections / total_sections) * 100)) if total_sections > 0 else 0
    ctx.update({
        "max_photo_size_mb": settings.VISITS_MAX_PHOTO_SIZE_BYTES // (1024 * 1024),
        "photo_total": visit.photos.count(),
        "max_photos_per_visit": settings.VISITS_MAX_PHOTOS_PER_VISIT,
        "errors": errors or [],
        "show_validation_errors": show_validation_errors,
        "locked": not visit.peut_etre_modifiee(),
        "total_sections_count": total_sections,
        "completed_sections_count": completed_sections,
        "progress_percent": progress_percent,
    })
    return ctx


def _render_visit_edit(request, visit, errors=None, status=200, show_validation_errors=False):
    return render(request, "visits/visit_edit.html", _visit_edit_context(visit, errors, user=request.user, show_validation_errors=show_validation_errors), status=status)


@role_required(User.Role.SUPERVISEUR)
def visit_edit(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    return render(request, "visits/visit_edit.html", _visit_edit_context(visit, user=request.user))


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

    Enregistre les réponses et fichiers valides, puis retourne les erreurs de fichiers.
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

    if sum(existing_counts.values()) + len(new_photos) > settings.VISITS_MAX_PHOTOS_PER_VISIT:
        errors.append(
            f"La visite ne peut pas contenir plus de {settings.VISITS_MAX_PHOTOS_PER_VISIT} photos au total. "
            "Les nouvelles photos n'ont pas été ajoutées ; sélectionnez-en moins puis réessayez."
        )
        new_photos = []

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
        try:
            image, miniature = optimiser_image(f)
        except ValueError:
            errors.append(f"« {f.name} » n'est pas une image valide.")
            continue
        VisitPhoto.objects.create(
            visit=visit,
            field_key=field_key,
            legende=photo_label_for_field(schema, field_key),
            image=image,
            miniature=miniature,
        )

    return errors


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
    step = request.POST.get("wizard_step", "")
    suffix = f"&step={int(step)}" if step.isdigit() else ""
    return redirect(f"{reverse('visits:visit-edit', args=[visit.pk])}?saved=1{suffix}")


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
        return _render_visit_edit(request, visit, errors=errors, status=400, show_validation_errors=True)

    visit.statut = Visit.Statut.SOUMISE
    visit.date_soumission = timezone.now()
    visit.save(update_fields=["statut", "date_soumission"])
    log(request.user, "soumission_visite", visit, detail={"mission_id": visit.mission_id})
    messages.success(request, "Visite soumise avec succès.")
    return redirect("visits:visit-confirmation", pk=visit.pk)


@role_required(User.Role.SUPERVISEUR)
def visit_confirmation(request, pk):
    visit = get_object_or_404(Visit, pk=pk, auteur=request.user)
    ctx = get_visit_detail_context(visit, user=request.user)
    return render(request, "visits/visit_confirmation.html", ctx)


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
def my_visits(request):
    base_qs = Visit.objects.filter(auteur=request.user).select_related(
        "mission",
        "mission__site",
        "mission__site__client",
        "mission__attached_form",
        "auteur",
        "decision_par",
    )

    # Compteurs en tête cliquables (brouillons, à corriger, soumises, validées)
    counts = {
        "brouillon": base_qs.filter(statut=Visit.Statut.BROUILLON).count(),
        "a_corriger": base_qs.filter(statut=Visit.Statut.A_CORRIGER).count(),
        "soumise": base_qs.filter(statut=Visit.Statut.SOUMISE).count(),
        "validee": base_qs.filter(statut=Visit.Statut.VALIDEE).count(),
        "total": base_qs.count(),
    }

    # Données pour les listes déroulantes de filtres
    clients_filter = Client.objects.filter(
        sites__missions__visits__auteur=request.user
    ).distinct().order_by("nom")

    sites_filter = Site.objects.filter(
        missions__visits__auteur=request.user
    ).distinct().select_related("client").order_by("nom")

    visits_qs = base_qs.order_by("-date_debut", "-id")

    statut = request.GET.get("statut", "").strip()
    client_id = request.GET.get("client", "").strip()
    site_id = request.GET.get("site", "").strip()
    date_min = request.GET.get("date_min", "").strip()
    date_max = request.GET.get("date_max", "").strip()
    search_q = request.GET.get("q", "").strip()

    if statut:
        visits_qs = visits_qs.filter(statut=statut)
    if client_id:
        visits_qs = visits_qs.filter(mission__site__client_id=client_id)
    if site_id:
        visits_qs = visits_qs.filter(mission__site_id=site_id)
    if date_min:
        try:
            visits_qs = visits_qs.filter(date_debut__date__gte=date_min)
        except Exception:
            pass
    if date_max:
        try:
            visits_qs = visits_qs.filter(date_debut__date__lte=date_max)
        except Exception:
            pass
    if search_q:
        visits_qs = visits_qs.filter(
            Q(mission__site__nom__icontains=search_q) | Q(mission__site__code__icontains=search_q)
        )

    paginator = Paginator(visits_qs, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    statut_choices = [
        (Visit.Statut.BROUILLON, "Brouillon"),
        (Visit.Statut.A_CORRIGER, "À corriger"),
        (Visit.Statut.SOUMISE, "Soumise"),
        (Visit.Statut.VALIDEE, "Validée"),
        (Visit.Statut.PUBLIEE, "Publiée"),
        (Visit.Statut.DEPUBLIEE, "Retirée"),
    ]

    context = {
        "visits": page_obj,
        "page_obj": page_obj,
        "counts": counts,
        "clients_filter": clients_filter,
        "sites_filter": sites_filter,
        "statut_choices": statut_choices,
        "filter_statut": statut,
        "filter_client": client_id,
        "filter_site": site_id,
        "filter_date_min": date_min,
        "filter_date_max": date_max,
        "search_q": search_q,
    }
    return render(request, "visits/my_visits.html", context)


@role_required(User.Role.SUPERVISEUR)
def my_visit_detail(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related(
            "mission",
            "mission__site",
            "mission__site__client",
            "mission__attached_form",
            "auteur",
            "decision_par",
        ),
        pk=pk,
        auteur=request.user,
    )

    # Les brouillons et les visites à corriger ouvrent directement l'écran de saisie ("Reprendre")
    if visit.peut_etre_modifiee():
        return redirect("visits:visit-edit", pk=visit.pk)

    context = get_visit_detail_context(visit, user=request.user)
    return render(request, "visits/my_visit_detail.html", context)


@validate_visits_required
def revue_list(request):
    tri = request.GET.get("tri", "-date")
    visits = (
        Visit.objects.filter(
            statut__in=[
                Visit.Statut.SOUMISE,
                Visit.Statut.VALIDEE,
                Visit.Statut.PUBLIEE,
                Visit.Statut.DEPUBLIEE,
            ]
        )
        .select_related(
            "mission",
            "mission__site",
            "mission__site__client",
            "mission__attached_form",
            "auteur",
            "decision_par",
        )
    )

    if tri == "date":
        visits = visits.order_by("date_debut")
    elif tri == "client":
        visits = visits.order_by("mission__site__client__nom", "-date_debut")
    elif tri == "-client":
        visits = visits.order_by("-mission__site__client__nom", "-date_debut")
    elif tri == "statut":
        visits = visits.order_by("statut", "-date_debut")
    else:
        visits = visits.order_by("-date_debut")

    selected_visit = None
    detail_context = {}
    selected_pk = request.GET.get("visit_pk")
    if selected_pk:
        selected_visit = visits.filter(pk=selected_pk).first()
    if not selected_visit and visits.exists():
        selected_visit = visits.first()

    if selected_visit:
        detail_context = get_visit_detail_context(
            selected_visit, user=request.user, show_revue_actions=True
        )

    context = {
        "visits": visits,
        "selected_visit": selected_visit,
        "current_tri": tri,
        **detail_context,
    }
    return render(request, "visits/revue_list.html", context)


@validate_visits_required
def revue_detail(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related(
            "mission",
            "mission__site",
            "mission__site__client",
            "mission__attached_form",
            "auteur",
            "decision_par",
        ),
        pk=pk,
    )
    context = get_visit_detail_context(visit, user=request.user, show_revue_actions=True)

    if request.headers.get("HX-Request"):
        return render(request, "visits/_visit_detail.html", context)
    return render(request, "visits/revue_detail.html", context)


@validate_visits_required
def echange_inbox(request):
    statut = request.GET.get("statut", Echange.Statut.OUVERT)
    client_id = request.GET.get("client", "").strip()
    non_lus = request.GET.get("non_lus") == "1"

    qs = echanges_service.echanges_manager()
    if statut in Echange.Statut.values:
        qs = qs.filter(statut=statut)
    if client_id.isdigit():
        qs = qs.filter(client_id=client_id)
    if non_lus:
        qs = qs.filter(non_lus__gt=0)

    context = {
        "echanges": qs,
        "clients": Client.objects.order_by("nom"),
        "filter_statut": statut,
        "filter_client": client_id,
        "filter_non_lus": non_lus,
    }
    return render(request, "echanges/inbox.html", context)


@validate_visits_required
def echange_nouveau(request):
    visit = None
    visite_id = request.GET.get("visite") or request.POST.get("visite")
    if visite_id and str(visite_id).isdigit():
        visit = get_object_or_404(
            Visit.objects.select_related("mission__site__client", "mission__attached_form"),
            pk=visite_id,
            statut=Visit.Statut.PUBLIEE,
        )
        if hasattr(visit, "echange"):
            return redirect("revue:echange", pk=visit.echange.pk)

    clients = Client.objects.order_by("nom")
    erreur = ""
    if request.method == "POST":
        sujet = request.POST.get("sujet", "").strip()[:200]
        texte = request.POST.get("texte", "").strip()
        client = visit.mission.site.client if visit else clients.filter(pk=request.POST.get("client") or 0).first()
        fichiers, erreurs = echanges_service.preparer_fichiers(request.FILES.getlist("fichiers"))
        if not (client and sujet and (texte or fichiers)):
            erreur = "Client, sujet et message sont obligatoires."
        elif erreurs:
            erreur = " ".join(erreurs)
        else:
            echange = echanges_service.creer_echange(client, request.user, sujet, texte, visit=visit, fichiers=fichiers)
            log(request.user, "message_manager", echange, detail={"client_id": client.pk})
            return redirect("revue:echange", pk=echange.pk)

    context = {
        "visit": visit,
        "clients": clients,
        "erreur": erreur,
        "is_portal": False,
        "back_url": reverse("revue:inbox"),
        "sujet": request.POST.get("sujet") or (echanges_service.sujet_par_defaut(visit) if visit else ""),
        "texte": request.POST.get("texte", ""),
        "selected_client": request.POST.get("client", ""),
    }
    return render(request, "echanges/new.html", context)


@validate_visits_required
def echange_detail(request, pk):
    echange = get_object_or_404(
        Echange.objects.select_related("client", "visit__mission__site", "visit__mission__attached_form"),
        pk=pk,
    )
    can_post = echanges_service.echange_accessible(echange)
    erreur = ""
    texte_saisi = ""
    if request.method == "POST":
        if not can_post:
            raise PermissionDenied("La visite n'est pas publiée.")
        texte_saisi = request.POST.get("texte", "").strip()
        fichiers, erreurs = echanges_service.preparer_fichiers(request.FILES.getlist("fichiers"))
        if erreurs:
            erreur = " ".join(erreurs)
        elif texte_saisi or fichiers:
            echanges_service.envoyer_message(echange, request.user, texte_saisi, fichiers)
            log(request.user, "message_manager", echange, detail={"client_id": echange.client_id})
            return redirect("revue:echange", pk=echange.pk)
    echanges_service.marquer_lus(echange, cote_client=False)
    context = {
        "erreur": erreur,
        "texte_saisi": texte_saisi,
        "echange": echange,
        "visit": echange.visit,
        "messages_echange": echange.messages.select_related("auteur").prefetch_related("fichiers"),
        "can_post": can_post,
        "post_url": reverse("revue:echange", args=[echange.pk]),
        "statut_url": reverse("revue:echange-statut", args=[echange.pk]),
        "visit_url": reverse("revue:detail", args=[echange.visit_id]) if echange.visit_id else "",
        "back_url": reverse("revue:inbox"),
        "is_portal": False,
    }
    return render(request, "echanges/thread.html", context)


@validate_visits_required
@require_POST
def echange_statut(request, pk):
    echange = get_object_or_404(Echange, pk=pk)
    echange.statut = (
        Echange.Statut.OUVERT if echange.statut == Echange.Statut.CLOS else Echange.Statut.CLOS
    )
    echange.save(update_fields=["statut"])
    return redirect("revue:echange", pk=pk)


@validate_visits_required
@require_POST
def visit_validate(request, pk):
    visit = get_object_or_404(Visit, pk=pk, statut=Visit.Statut.SOUMISE)
    if visit.auteur_id == request.user.id:
        raise PermissionDenied("Un validateur ne peut pas valider sa propre visite.")

    visit.statut = Visit.Statut.VALIDEE
    visit.decision_par = request.user
    visit.decision_le = timezone.now()
    visit.commentaire_rejet = ""
    visit.save(update_fields=["statut", "decision_par", "decision_le", "commentaire_rejet"])
    log(request.user, "validation_visite", visit, detail={"mission_id": visit.mission_id})
    messages.success(request, "Visite validée.")
    return redirect("revue:list")


@validate_visits_required
@require_POST
def visit_reject(request, pk):
    visit = get_object_or_404(Visit, pk=pk, statut=Visit.Statut.SOUMISE)
    if visit.auteur_id == request.user.id:
        raise PermissionDenied("Un validateur ne peut pas rejeter sa propre visite.")

    commentaire = request.POST.get("commentaire", "").strip()
    if not commentaire:
        messages.error(request, "Un commentaire est obligatoire pour rejeter une visite.")
        return redirect("revue:list")

    visit.statut = Visit.Statut.A_CORRIGER
    visit.decision_par = request.user
    visit.decision_le = timezone.now()
    visit.commentaire_rejet = commentaire
    visit.save(update_fields=["statut", "decision_par", "decision_le", "commentaire_rejet"])
    log(request.user, "rejet_visite", visit, detail={"mission_id": visit.mission_id, "commentaire": commentaire})
    messages.success(request, "Visite renvoyée pour correction.")
    return redirect("revue:list")


@validate_visits_required
@require_POST
def visit_publish(request, pk):
    visit = get_object_or_404(Visit, pk=pk, statut__in=[Visit.Statut.VALIDEE, Visit.Statut.DEPUBLIEE])
    visit.statut = Visit.Statut.PUBLIEE
    visit.save(update_fields=["statut"])
    log(request.user, "publication_visite", visit, detail={"mission_id": visit.mission_id})
    messages.success(request, "Visite publiée au client.")
    return redirect("revue:list")


@validate_visits_required
@require_POST
def visit_unpublish(request, pk):
    visit = get_object_or_404(Visit, pk=pk, statut=Visit.Statut.PUBLIEE)
    visit.statut = Visit.Statut.DEPUBLIEE
    visit.save(update_fields=["statut"])
    log(request.user, "depublication_visite", visit, detail={"mission_id": visit.mission_id})
    messages.success(request, "Visite dépubliée (toujours en base, masquée côté client).")
    return redirect("revue:list")


@role_required(User.Role.SUPERVISEUR)
@require_POST
def photo_delete(request, pk):
    photo = get_object_or_404(VisitPhoto, pk=pk, visit__auteur=request.user)
    if not photo.visit.peut_etre_modifiee():
        raise PermissionDenied
    visit_pk = photo.visit_id
    photo.delete()
    return redirect("visits:visit-edit", pk=visit_pk)


def _pdf_response(content, filename):
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _zip_response(content, filename):
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@role_required(User.Role.MANAGER, User.Role.SUPERVISEUR)
def visit_pdf(request, pk):
    if request.user.role == User.Role.SUPERVISEUR:
        visit = get_object_or_404(
            Visit,
            pk=pk,
            auteur=request.user,
            statut__in=[Visit.Statut.VALIDEE, Visit.Statut.PUBLIEE],
        )
    else:
        visit = get_object_or_404(Visit, pk=pk, statut=Visit.Statut.PUBLIEE)
    return _pdf_response(render_visit_pdf(visit), visit_pdf_filename(visit))


@role_required(User.Role.MANAGER)
def site_export(request, client_pk, site_pk):
    site = get_object_or_404(Site, pk=site_pk, client_id=client_pk)
    visits = Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site=site)
    log(request.user, "export_pdf_site", site, detail={"client_id": client_pk, "nombre_visites": visits.count()})
    return _zip_response(build_visits_zip(visits), zip_filename_for_site(site))


@role_required(User.Role.MANAGER)
def client_export(request, client_pk):
    client_obj = get_object_or_404(Client, pk=client_pk)
    visits = Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site__client=client_obj)
    log(
        request.user,
        "export_pdf_client",
        client_obj,
        detail={"nombre_visites": visits.count()},
    )
    return _zip_response(build_visits_zip(visits), zip_filename_for_client(client_obj))
