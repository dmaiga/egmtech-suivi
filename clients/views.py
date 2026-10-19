from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from core.services import log

from forms_cms.models import FormTemplate

from .forms import ClientForm, ClientUserCreationForm, SiteForm
from .models import Client, Site


class ManagerRequiredMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.MANAGER,)


class ClientListView(ManagerRequiredMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"


class ClientCreateView(ManagerRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def get_success_url(self):
        return reverse("clients:detail", args=[self.object.pk])


class ClientDetailView(ManagerRequiredMixin, DetailView):
    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sites"] = self.object.sites.all()
        context["site_form"] = SiteForm()
        context["client_users"] = self.object.users.filter(role=User.Role.CLIENT)
        context["user_form"] = ClientUserCreationForm()

        sites = list(context["sites"])
        attached_forms = self.object.attached_forms.select_related("template").prefetch_related("expected_visits")
        attached_forms_data = []
        for attached_form in attached_forms:
            previsions = {ev.site_id: ev.nombre_prevu for ev in attached_form.expected_visits.all()}
            attached_forms_data.append(
                {
                    "form": attached_form,
                    "sites": [(site, previsions.get(site.pk, 0)) for site in sites],
                }
            )
        context["attached_forms_data"] = attached_forms_data

        attached_template_ids = attached_forms.values_list("template_id", flat=True)
        context["available_templates"] = FormTemplate.objects.filter(actif=True).exclude(
            pk__in=attached_template_ids
        )
        return context


class SiteUpdateView(ManagerRequiredMixin, UpdateView):
    model = Site
    form_class = SiteForm
    template_name = "clients/site_form.html"

    def get_queryset(self):
        return Site.objects.filter(client_id=self.kwargs["client_pk"])

    def get_success_url(self):
        return reverse("clients:detail", args=[self.kwargs["client_pk"]])


@role_required(User.Role.MANAGER)
@require_POST
def site_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    form = SiteForm(request.POST)
    if form.is_valid():
        site = form.save(commit=False)
        site.client = client
        site.save()
        log(request.user, "creation_site", site, detail={"client_id": client.pk})
        return render(
            request,
            "clients/_site_create_success.html",
            {"client": client, "site": site, "site_form": SiteForm()},
        )
    return render(
        request,
        "clients/_site_form.html",
        {"client": client, "site_form": form},
        status=400,
    )


@role_required(User.Role.MANAGER)
@require_POST
def site_delete(request, client_pk, pk):
    site = get_object_or_404(Site, pk=pk, client_id=client_pk)
    log(request.user, "suppression_site", site, detail={"client_id": client_pk, "nom": site.nom})
    site.delete()
    return redirect("clients:detail", pk=client_pk)


@role_required(User.Role.MANAGER)
@require_POST
def client_user_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    form = ClientUserCreationForm(request.POST)
    if form.is_valid():
        user = form.save(commit=False)
        user.role = User.Role.CLIENT
        user.client = client
        user.save()
        log(request.user, "creation_compte_client", user, detail={"client_id": client.pk})
        messages.success(request, "Compte client créé.")
        return redirect("clients:detail", pk=client.pk)

    context = {
        "client": client,
        "sites": client.sites.all(),
        "site_form": SiteForm(),
        "client_users": client.users.filter(role=User.Role.CLIENT),
        "user_form": form,
    }
    return render(request, "clients/client_detail.html", context, status=400)


@role_required(User.Role.MANAGER)
@require_POST
def client_user_revoke(request, client_pk, user_pk):
    user = get_object_or_404(User, pk=user_pk, client_id=client_pk, role=User.Role.CLIENT)
    user.is_active = False
    user.save(update_fields=["is_active"])
    log(request.user, "revocation_compte", user, detail={"client_id": client_pk})
    messages.success(request, "Compte révoqué.")
    return redirect("clients:detail", pk=client_pk)
