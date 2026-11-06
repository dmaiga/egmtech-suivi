import json
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView

from clients.models import Client, Site
from core.services import log
from visits.schema_utils import build_render_model

from .builder import FIELD_TYPE_LABELS, SUBFIELD_TYPE_LABELS, annotate_for_render, apply_action, parse_builder_form
from .decorators import manage_forms_required
from .forms import FormTemplateImportForm
from .mixins import ManageFormsRequiredMixin
from .models import AttachedForm, ExpectedVisits, FormTemplate
from .schema import validate_schema
from .services import attach_template_to_client, set_attached_sites, set_expected_visits, toggle_attached_form


class FormTemplateListView(ManageFormsRequiredMixin, ListView):
    model = FormTemplate
    template_name = "forms_cms/template_list.html"
    context_object_name = "templates"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset()
        tri = self.request.GET.get("tri", "nom")
        if tri == "-nom":
            return qs.order_by("-nom")
        elif tri == "statut":
            return qs.order_by("-actif", "nom")
        elif tri == "-statut":
            return qs.order_by("actif", "nom")
        return qs.order_by("nom")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_tri"] = self.request.GET.get("tri", "nom")
        return context


class FormTemplateImportView(ManageFormsRequiredMixin, CreateView):
    model = FormTemplate
    form_class = FormTemplateImportForm
    template_name = "forms_cms/template_import.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        log(self.request.user, "import_formulaire", self.object)
        return response

    def get_success_url(self):
        return reverse("forms_cms:list")


def _builder_context(parsed, template, errors, show_preview):
    context = {
        "nom": parsed["nom"],
        "description": parsed["description"],
        "template_pk": parsed["template_pk"],
        "sections": parsed["schema"].get("sections", []),
        "field_types": FIELD_TYPE_LABELS,
        "subfield_types": SUBFIELD_TYPE_LABELS,
        "errors": errors,
        "is_edit": template is not None,
        "schema_data": parsed["schema"],
    }
    if show_preview:
        context["preview_sections"] = build_render_model(parsed["schema"], {})
    return context


@manage_forms_required
def form_builder(request, pk=None):
    template = get_object_or_404(FormTemplate, pk=pk) if pk else None

    if request.method == "POST":
        action = request.POST.get("action", "")
        json_error = None
        if "schema_json" in request.POST:
            try:
                schema = json.loads(request.POST.get("schema_json", ""))
                if not isinstance(schema, dict):
                    raise ValueError("Le schéma doit être un objet.")
            except (ValueError, TypeError):
                schema = {"sections": []}
                json_error = "Le formulaire n'a pas pu être lu. Vos modifications n'ont pas été enregistrées."
            parsed = {"nom": request.POST.get("nom", "").strip(), "description": request.POST.get("description", "").strip(), "template_pk": str(pk or ""), "schema": schema}
        else:
            parsed = parse_builder_form(request.POST)
            apply_action(parsed["schema"], action, request.POST)

        errors = [json_error] if json_error else []
        if action == "save":
            if not parsed["nom"]:
                errors.append("Le nom du formulaire est requis.")
            errors.extend(validate_schema(parsed["schema"]))

            if not errors:
                if template:
                    template.nom = parsed["nom"]
                    template.description = parsed["description"]
                    template.schema = parsed["schema"]
                    template.save()
                    log(request.user, "modification_formulaire", template)
                else:
                    template = FormTemplate.objects.create(
                        nom=parsed["nom"],
                        description=parsed["description"],
                        schema=parsed["schema"],
                        actif=True,
                    )
                    log(request.user, "creation_formulaire", template)
                messages.success(request, "Formulaire enregistré.")
                return redirect("forms_cms:list")

        show_preview = action == "preview" and not errors and not validate_schema(parsed["schema"])
        if action == "preview" and not show_preview and not errors:
            errors.extend(validate_schema(parsed["schema"]))
        context = _builder_context(parsed, template, errors, show_preview)
        context["editor_dirty"] = True
        return render(request, "forms_cms/builder.html", context)

    if template:
        schema = template.schema if template.schema.get("sections") else {"sections": []}
        parsed = {
            "nom": template.nom,
            "description": template.description,
            "template_pk": str(template.pk),
            "schema": schema,
        }
    else:
        parsed = {"nom": "", "description": "", "template_pk": "", "schema": {"sections": []}}

    return render(request, "forms_cms/builder.html", _builder_context(parsed, template, [], False))


@manage_forms_required
def form_template_preview(request, pk):
    template = get_object_or_404(FormTemplate, pk=pk)
    preview_sections = build_render_model(template.schema, {})
    return render(
        request,
        "forms_cms/template_preview.html",
        {
            "template": template,
            "preview_sections": preview_sections,
        },
    )


@manage_forms_required
@require_POST
def form_template_toggle(request, pk):
    template = get_object_or_404(FormTemplate, pk=pk)
    template.actif = not template.actif
    template.save(update_fields=["actif"])
    action = "activation_formulaire" if template.actif else "desactivation_formulaire"
    log(request.user, action, template)
    statut_msg = "activé" if template.actif else "désactivé"
    messages.success(request, f"Formulaire « {template.nom} » {statut_msg}.")
    return redirect("forms_cms:list")


@manage_forms_required
@require_POST
def client_attach_form(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    template_id = request.POST.get("template_id", "").strip()
    destination = reverse("clients:detail", args=[client_pk]) + "?onglet=formulaires"
    if not template_id.isascii() or not template_id.isdigit() or len(template_id) > 18:
        messages.error(request, "Sélectionnez un formulaire disponible avant de continuer.")
        return redirect(destination)
    template = FormTemplate.objects.filter(pk=int(template_id), actif=True).first()
    if template is None:
        messages.error(request, "Ce formulaire n'est plus disponible. Sélectionnez un formulaire actif.")
        return redirect(destination)
    if AttachedForm.objects.filter(client=client, template=template).exists():
        messages.error(request, "Ce formulaire est déjà attaché à ce client.")
        return redirect(destination)
    sites = _perimetre_depuis_post(request.POST, client) if "perimetre" in request.POST else None
    if sites is not None and not sites:
        messages.error(request, "Cochez « Tous les sites » ou au moins un site.")
        return redirect(destination)
    attach_template_to_client(request.user, client, template, sites)
    messages.success(request, "Formulaire attaché au client.")
    return redirect(destination)


def _perimetre_depuis_post(post, client):
    """None si « tous les sites » est coché, sinon la liste des sites cochés (du client seulement)."""

    if post.get("tous_les_sites"):
        return None
    ids = [raw for raw in post.getlist("sites") if raw.isascii() and raw.isdigit() and len(raw) <= 18]
    return list(Site.objects.filter(client=client, pk__in=ids))


@manage_forms_required
@require_POST
def attached_form_toggle(request, client_pk, pk):
    attached = get_object_or_404(AttachedForm, pk=pk, client_id=client_pk)
    toggle_attached_form(request.user, attached)
    statut_msg = "réactivé" if attached.actif else "archivé"
    messages.success(request, f"Formulaire « {attached.nom} » {statut_msg}.")
    return redirect(_onglet_formulaires(client_pk))


def _onglet_formulaires(client_pk):
    return reverse("clients:detail", args=[client_pk]) + "?onglet=formulaires"


@manage_forms_required
@require_POST
def attached_form_delete(request, client_pk, pk):
    """Retire un formulaire du client tant qu'aucune mission ne l'utilise (sinon : archiver)."""

    attached = get_object_or_404(AttachedForm, pk=pk, client_id=client_pk)
    if attached.missions.exists():
        messages.error(request, f"« {attached.nom} » est déjà utilisé par des missions : archivez-le plutôt.")
        return redirect(_onglet_formulaires(client_pk))
    log(request.user, "suppression_formulaire_attache", attached,
        detail={"client_id": client_pk, "template_id": attached.template_id})
    attached.delete()
    messages.success(request, f"Formulaire « {attached.nom} » retiré du client.")
    return redirect(_onglet_formulaires(client_pk))


@manage_forms_required
@require_POST
def attached_sites_add(request, client_pk, pk):
    attached = get_object_or_404(AttachedForm.objects.select_related("client"), pk=pk, client_id=client_pk)
    nouveaux = _perimetre_depuis_post(request.POST, attached.client)
    if nouveaux is None:
        set_attached_sites(request.user, attached, None)
    elif not nouveaux:
        messages.error(request, "Cochez au moins un site à ajouter.")
        return redirect(_onglet_formulaires(client_pk))
    elif not attached.tous_les_sites:
        set_attached_sites(request.user, attached, list(attached.sites.all()) + nouveaux)
    messages.success(request, "Site(s) ajouté(s) au formulaire.")
    return redirect(_onglet_formulaires(client_pk))


@manage_forms_required
@require_POST
def attached_site_remove(request, client_pk, pk, site_pk):
    attached = get_object_or_404(AttachedForm.objects.select_related("client"), pk=pk, client_id=client_pk)
    site = get_object_or_404(Site, pk=site_pk, client_id=client_pk)
    restants = [s for s in attached.sites_concernes() if s.pk != site.pk]
    if not restants:
        messages.error(request, "C'est le dernier site de ce formulaire : supprimez ou archivez le formulaire.")
        return redirect(_onglet_formulaires(client_pk))
    set_attached_sites(request.user, attached, restants)
    messages.success(request, f"Site « {site.nom} » retiré du formulaire « {attached.nom} ».")
    return redirect(_onglet_formulaires(client_pk))


@manage_forms_required
@require_POST
def expected_visits_update(request, client_pk, pk):
    attached = get_object_or_404(AttachedForm.objects.select_related("client"), pk=pk, client_id=client_pk)
    for site in attached.sites_concernes():
        raw = request.POST.get(f"nombre_prevu_{site.pk}")
        if raw is None:
            continue
        if raw == "":
            expected = ExpectedVisits.objects.filter(site=site, attached_form=attached).first()
            if expected:
                log(request.user, "suppression_prevision_visites", expected, detail={"site_id": site.pk, "attached_form_id": attached.pk})
                expected.delete()
            continue
        try:
            nombre_prevu = int(raw)
        except ValueError:
            continue
        if nombre_prevu < 0:
            continue
        set_expected_visits(request.user, attached, site, nombre_prevu)
    messages.success(request, "Prévisions mises à jour.")
    return redirect(reverse("clients:detail", args=[client_pk]) + "?onglet=formulaires")
