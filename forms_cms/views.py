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
from .models import AttachedForm, FormTemplate
from .schema import validate_schema
from .services import attach_template_to_client, set_expected_visits, toggle_attached_form


class FormTemplateListView(ManageFormsRequiredMixin, ListView):
    model = FormTemplate
    template_name = "forms_cms/template_list.html"
    context_object_name = "templates"


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
        "sections": annotate_for_render(parsed["schema"]),
        "field_types": FIELD_TYPE_LABELS,
        "subfield_types": SUBFIELD_TYPE_LABELS,
        "errors": errors,
        "is_edit": template is not None,
    }
    if show_preview:
        context["preview_sections"] = build_render_model(parsed["schema"], {})
    return context


@manage_forms_required
def form_builder(request, pk=None):
    template = get_object_or_404(FormTemplate, pk=pk) if pk else None

    if request.method == "POST":
        parsed = parse_builder_form(request.POST)
        action = request.POST.get("action", "")
        apply_action(parsed["schema"], action, request.POST)

        errors = []
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

        show_preview = action == "preview" or bool(errors)
        context = _builder_context(parsed, template, errors, show_preview)
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
    template = get_object_or_404(FormTemplate, pk=request.POST.get("template_id"), actif=True)
    attach_template_to_client(request.user, client, template)
    messages.success(request, "Formulaire attaché au client.")
    return redirect("clients:detail", pk=client_pk)


@manage_forms_required
@require_POST
def attached_form_toggle(request, client_pk, pk):
    attached = get_object_or_404(AttachedForm, pk=pk, client_id=client_pk)
    toggle_attached_form(request.user, attached)
    statut_msg = "activé" if attached.actif else "désactivé"
    messages.success(request, f"Formulaire attaché « {attached.nom} » {statut_msg}.")
    return redirect("clients:detail", pk=client_pk)


@manage_forms_required
@require_POST
def expected_visits_update(request, client_pk, pk):
    attached = get_object_or_404(AttachedForm, pk=pk, client_id=client_pk)
    for site in Site.objects.filter(client_id=client_pk):
        raw = request.POST.get(f"nombre_prevu_{site.pk}")
        if raw is None or raw == "":
            continue
        try:
            nombre_prevu = int(raw)
        except ValueError:
            continue
        if nombre_prevu < 0:
            continue
        set_expected_visits(request.user, attached, site, nombre_prevu)
    messages.success(request, "Prévisions mises à jour.")
    return redirect("clients:detail", pk=client_pk)
