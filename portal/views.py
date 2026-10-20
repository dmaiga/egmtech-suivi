from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.decorators import role_required
from accounts.models import User
from clients.models import Site
from core.services import log
from forms_cms.models import AttachedForm, ExpectedVisits
from visits.models import Visit
from visits.pdf import (
    build_visits_zip,
    render_visit_pdf,
    visit_pdf_filename,
    zip_filename_for_client,
    zip_filename_for_site,
)
from visits.schema_utils import build_render_model, get_visit_detail_context


@role_required(User.Role.CLIENT)
def dashboard(request):
    client = request.user.client

    ville = request.GET.get("ville", "")
    form_id = request.GET.get("formulaire", "")
    q = request.GET.get("q", "").strip()

    sites = Site.objects.filter(client=client).order_by("nom")
    forms = AttachedForm.objects.filter(client=client).order_by("nom")

    if q:
        sites = sites.filter(Q(nom__icontains=q) | Q(code__icontains=q))
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
    total_faites = 0
    total_prevues = 0

    for site in sites_list:
        entries = []
        for attached_form in forms_list:
            key = (site.pk, attached_form.pk)
            stats = stats_map.get(key)
            prevu = expected_map.get(key, 0)
            fait = stats["fait"] if stats else 0
            dernier_passage = stats["dernier_passage"] if stats else None

            total_faites += fait
            total_prevues += prevu

            if prevu > 0:
                pourcentage = min(100, int(round((fait / prevu) * 100)))
            else:
                pourcentage = 100 if fait > 0 else 0

            if fait >= prevu and prevu > 0:
                statut_key = "complet"
                statut_label = "Complet"
            elif fait > 0:
                statut_key = "en_cours"
                statut_label = "En cours"
            else:
                statut_key = "non_visite"
                statut_label = "Pas encore visité"

            entries.append(
                {
                    "attached_form": attached_form,
                    "prevu": prevu,
                    "fait": fait,
                    "pourcentage": pourcentage,
                    "statut": statut_key,
                    "statut_label": statut_label,
                    "dernier_passage": dernier_passage,
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

    progression_globale = (
        min(100, int(round((total_faites / total_prevues) * 100)))
        if total_prevues > 0
        else (100 if total_faites > 0 else 0)
    )

    context = {
        "table": table,
        "villes": villes,
        "all_forms": all_forms,
        "selected_ville": ville,
        "selected_formulaire": form_id,
        "search_query": q,
        "total_sites": len(sites_list),
        "total_visites_faites": total_faites,
        "total_visites_prevues": total_prevues,
        "progression_globale": progression_globale,
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

    attached_forms = AttachedForm.objects.filter(client=site.client, actif=True).order_by("nom")
    expected_map = {
        ev.attached_form_id: ev.nombre_prevu
        for ev in ExpectedVisits.objects.filter(site=site)
    }
    stats_map = {
        row["mission__attached_form_id"]: row["total"]
        for row in Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site=site)
        .values("mission__attached_form_id")
        .annotate(total=Count("id"))
    }

    previsions = []
    total_reste = 0
    for af in attached_forms:
        prevu = expected_map.get(af.pk, 0)
        fait = stats_map.get(af.pk, 0)
        reste = max(0, prevu - fait)
        total_reste += reste
        if prevu > 0:
            pourcentage = min(100, int(round(fait / prevu * 100)))
        else:
            pourcentage = 100 if fait > 0 else 0

        if fait >= prevu and prevu > 0:
            statut_key = "complet"
            statut_label = "Complet"
        elif fait > 0:
            statut_key = "en_cours"
            statut_label = "En cours"
        else:
            statut_key = "non_visite"
            statut_label = "Pas encore visité"

        previsions.append({
            "attached_form": af,
            "prevu": prevu,
            "fait": fait,
            "reste": reste,
            "pourcentage": pourcentage,
            "statut": statut_key,
            "statut_label": statut_label,
        })

    context = {
        "site": site,
        "visits": visits,
        "previsions": previsions,
        "total_reste": total_reste,
    }
    return render(request, "portal/site_detail.html", context)


@role_required(User.Role.CLIENT)
def visit_detail(request, pk):
    visit = get_object_or_404(
        Visit,
        pk=pk,
        statut=Visit.Statut.PUBLIEE,
        mission__site__client=request.user.client,
    )

    log(request.user, "consultation_visite_portail", visit, detail={"mission_id": visit.mission_id})

    context = get_visit_detail_context(visit, user=request.user, is_portal=True)
    return render(request, "portal/visit_detail.html", context)


def _pdf_response(content, filename):
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _zip_response(content, filename):
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@role_required(User.Role.CLIENT)
def visit_pdf(request, pk):
    visit = get_object_or_404(
        Visit, pk=pk, statut=Visit.Statut.PUBLIEE, mission__site__client=request.user.client
    )
    log(request.user, "telechargement_pdf_visite", visit, detail={"mission_id": visit.mission_id})
    return _pdf_response(render_visit_pdf(visit), visit_pdf_filename(visit))


@role_required(User.Role.CLIENT)
def site_export(request, pk):
    site = get_object_or_404(Site, pk=pk, client=request.user.client)
    visits = Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site=site)
    log(request.user, "export_pdf_site", site, detail={"nombre_visites": visits.count()})
    return _zip_response(build_visits_zip(visits), zip_filename_for_site(site))


@role_required(User.Role.CLIENT)
def client_export(request):
    client = request.user.client
    visits = Visit.objects.filter(statut=Visit.Statut.PUBLIEE, mission__site__client=client)
    log(request.user, "export_pdf_client", client, detail={"nombre_visites": visits.count()})
    return _zip_response(build_visits_zip(visits), zip_filename_for_client(client))
