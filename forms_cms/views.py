from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView

from clients.models import Client, Site
from core.services import log

from .decorators import manage_forms_required
from .forms import FormTemplateImportForm
from .mixins import ManageFormsRequiredMixin
from .models import AttachedForm, FormTemplate
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


@manage_forms_required
@require_POST
def form_template_toggle(request, pk):
    template = get_object_or_404(FormTemplate, pk=pk)
    template.actif = not template.actif
    template.save(update_fields=["actif"])
    action = "activation_formulaire" if template.actif else "desactivation_formulaire"
    log(request.user, action, template)
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
