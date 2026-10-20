from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, render

from accounts.decorators import role_required
from accounts.models import User
from clients.models import Site
from core.services import log
from forms_cms.models import AttachedForm, ExpectedVisits
from visits.models import Visit
from visits.schema_utils import build_render_model


@role_required(User.Role.CLIENT)
def dashboard(request):
    client = request.user.client

    ville = request.GET.get("ville", "")
    form_id = request.GET.get("formulaire", "")

    sites = Site.objects.filter(client=client).order_by("nom")
    forms = AttachedForm.objects.filter(client=client).order_by("nom")

    if ville:
        sites = sites.filter(ville=ville)
    if form_id:
        forms = forms.filter(pk=form_id)

    expected_map = {
        (ev.site_id, ev.attached_form_id): ev.nombre_prevu
        for ev in ExpectedVisits.objects.filter(site__client=client)
    }

    stats_map = {
        (row["mission__site_id"], row["mission__attached_form_id"]): row
        for row in Visit.objects.filter(
            statut=Visit.Statut.PUBLIEE, mission__site__client=client
        )
        .values("mission__site_id", "mission__attached_form_id")
        .annotate(fait=Count("id"), dernier_passage=Max("date_soumission"))
    }

    sites_list = list(sites)
    forms_list = list(forms)

    table = []
    for site in sites_list:
        entries = []
        for attached_form in forms_list:
            key = (site.pk, attached_form.pk)
            stats = stats_map.get(key)
            entries.append(
                {
                    "attached_form": attached_form,
                    "prevu": expected_map.get(key, 0),
                    "fait": stats["fait"] if stats else 0,
                    "dernier_passage": stats["dernier_passage"] if stats else None,
                }
            )
        table.append({"site": site, "entries": entries})

    villes = (
        Site.objects.filter(client=client)
        .exclude(ville="")
        .values_list("ville", flat=True)
        .distinct()
        .order_by("ville")
    )
    all_forms = AttachedForm.objects.filter(client=client).order_by("nom")

    context = {
        "table": table,
        "villes": villes,
        "all_forms": all_forms,
        "selected_ville": ville,
        "selected_formulaire": form_id,
    }
    return render(request, "portal/dashboard.html", context)


@role_required(User.Role.CLIENT)
def site_detail(request, pk):
    site = get_object_or_404(Site, pk=pk, client=request.user.client)
    visits = (
        Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site=site)
        .select_related("mission", "mission__attached_form", "auteur")
        .order_by("-date_soumission")
    )
    return render(request, "portal/site_detail.html", {"site": site, "visits": visits})


@role_required(User.Role.CLIENT)
def visit_detail(request, pk):
    visit = get_object_or_404(
        Visit,
        pk=pk,
        statut=Visit.Statut.PUBLIEE,
        mission__site__client=request.user.client,
    )

    log(request.user, "consultation_visite_portail", visit, detail={"mission_id": visit.mission_id})

    schema = visit.mission.attached_form.schema
    photos_by_field = {}
    for photo in visit.photos.all():
        photos_by_field.setdefault(photo.field_key, []).append(photo)
    sections = build_render_model(schema, visit.reponses, photos_by_field)

    context = {
        "visit": visit,
        "mission": visit.mission,
        "site": visit.mission.site,
        "sections": sections,
    }
    return render(request, "portal/visit_detail.html", context)
