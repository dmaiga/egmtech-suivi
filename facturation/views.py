from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .decorators import manage_invoices_required
from .forms import ContactClientForm, ProduitForm, ProfilEmetteurForm
from .models import ContactClient, Produit, ProfilEmetteur

CONTACTS_PAR_PAGE = 20
PRODUITS_PAR_PAGE = 20


@manage_invoices_required
def profil_edit(request):
    profil = ProfilEmetteur.get()
    form = ProfilEmetteurForm(request.POST or None, request.FILES or None, instance=profil)
    if request.method == "POST" and form.is_valid():
        services.modifier_profil(form, request.user)
        messages.success(request, "Profil émetteur enregistré.")
        return redirect("facturation:profil")
    return render(request, "facturation/profil_form.html", {"form": form, "profil": profil})


@manage_invoices_required
def profil_image(request, champ):
    """Sert le logo ou le cachet : jamais par une URL publique, uniquement avec la permission."""
    if champ not in services.IMAGES_PROFIL:
        raise Http404
    fichier = getattr(ProfilEmetteur.get(), champ)
    if not fichier:
        raise Http404
    try:
        response = FileResponse(fichier.open("rb"), content_type="image/png")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@manage_invoices_required
def contact_list(request):
    q = request.GET.get("q", "").strip()
    inclure_inactifs = request.GET.get("inactifs") == "1"
    contacts = services.rechercher_contacts(q, inclure_inactifs)
    page_obj = Paginator(contacts, CONTACTS_PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "facturation/contact_list.html", {
        "page_obj": page_obj,
        "contacts": page_obj.object_list,
        "q": q,
        "inclure_inactifs": inclure_inactifs,
    })


@manage_invoices_required
def contact_create(request):
    form = ContactClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contact = services.creer_contact(form, request.user)
        messages.success(request, f"Contact « {contact.nom} » créé.")
        return redirect("facturation:contact-list")
    return render(request, "facturation/contact_form.html", {"form": form})


@manage_invoices_required
def contact_update(request, pk):
    contact = get_object_or_404(ContactClient, pk=pk)
    form = ContactClientForm(request.POST or None, instance=contact)
    if request.method == "POST" and form.is_valid():
        services.modifier_contact(form, request.user)
        messages.success(request, f"Contact « {contact.nom} » mis à jour.")
        return redirect("facturation:contact-list")
    return render(request, "facturation/contact_form.html", {"form": form, "contact": contact})


@require_POST
@manage_invoices_required
def contact_deactivate(request, pk):
    contact = get_object_or_404(ContactClient, pk=pk)
    services.changer_activation_contact(contact, False, request.user)
    messages.success(request, f"Contact « {contact.nom} » désactivé.")
    return redirect("facturation:contact-list")


@require_POST
@manage_invoices_required
def contact_reactivate(request, pk):
    contact = get_object_or_404(ContactClient, pk=pk)
    services.changer_activation_contact(contact, True, request.user)
    messages.success(request, f"Contact « {contact.nom} » réactivé.")
    return redirect("facturation:contact-list")


@manage_invoices_required
def produit_list(request):
    q = request.GET.get("q", "").strip()
    inclure_inactifs = request.GET.get("inactifs") == "1"
    produits = services.rechercher_produits(q, inclure_inactifs)
    page_obj = Paginator(produits, PRODUITS_PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "facturation/produit_list.html", {
        "page_obj": page_obj,
        "produits": page_obj.object_list,
        "q": q,
        "inclure_inactifs": inclure_inactifs,
    })


@manage_invoices_required
def produit_create(request):
    form = ProduitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        produit = services.creer_produit(
            form.cleaned_data["designation"], form.cleaned_data["prix_unitaire"], request.user
        )
        messages.success(request, f"Produit « {produit.designation} » créé.")
        return redirect("facturation:produit-list")
    return render(request, "facturation/produit_form.html", {"form": form})


@manage_invoices_required
def produit_update(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    form = ProduitForm(request.POST or None, instance=produit)
    if request.method == "POST" and form.is_valid():
        # Le formulaire a déjà modifié l'instance en mémoire : le service enregistre et journalise.
        services.modifier_produit(
            produit, request.user,
            designation=form.cleaned_data["designation"], prix_unitaire=form.cleaned_data["prix_unitaire"],
        )
        messages.success(request, f"Produit « {produit.designation} » mis à jour.")
        return redirect("facturation:produit-list")
    return render(request, "facturation/produit_form.html", {"form": form, "produit": produit})


@require_POST
@manage_invoices_required
def produit_deactivate(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    services.changer_activation_produit(produit, False, request.user)
    messages.success(request, f"Produit « {produit.designation} » désactivé.")
    return redirect("facturation:produit-list")


@require_POST
@manage_invoices_required
def produit_reactivate(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    services.changer_activation_produit(produit, True, request.user)
    messages.success(request, f"Produit « {produit.designation} » réactivé.")
    return redirect("facturation:produit-list")
