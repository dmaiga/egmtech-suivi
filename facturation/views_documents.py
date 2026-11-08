"""Saisie des documents : liste, création, édition d'un brouillon et de ses lignes (HTMX).

Vues minces : la validation de saisie est dans forms.py, les règles et calculs dans services.py.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .decorators import manage_invoices_required
from .exceptions import DocumentNonModifiable, ErreurFacturation
from .forms import AjoutProduitForm, DocumentForm, LigneForm
from .models import Document, LigneDocument, ProfilEmetteur

DOCUMENTS_PAR_PAGE = 20
MESSAGE_NON_BROUILLON = "Ce document n'est plus un brouillon : il ne peut plus être modifié ni supprimé."
PREFIXE_NOUVELLE_LIGNE = "nouvelle"


def _est_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _refuser_non_brouillon(request, message=MESSAGE_NON_BROUILLON):
    """Message d'erreur et retour à la liste ; une requête HTMX est redirigée par l'en-tête HX-Redirect."""
    messages.error(request, message)
    url = reverse("facturation:document-list")
    if _est_htmx(request):
        response = HttpResponse()
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def _prefixe_ligne(ligne):
    return f"ligne-{ligne.pk}"


def _initial_entete(document):
    return {
        "contact": document.contact_id, "objet": document.objet, "lieu_livraison": document.lieu_livraison,
        "taux_tva": document.taux_tva, "validite_jours": document.validite_jours,
    }


def _formulaire_entete(document, data=None):
    return DocumentForm(data, type_document=document.type, contact_actuel=document.contact,
                        initial=_initial_entete(document))


def _contexte_edition(document, entete_form=None, formulaires_lignes=None, ajout_form=None, ajout_produit_form=None):
    """Contexte de la page d'édition et du fragment des lignes.

    `formulaires_lignes` : {pk de ligne: formulaire lié} pour réafficher une ligne en erreur.
    """
    formulaires_lignes = formulaires_lignes or {}
    lignes = []
    for ligne in document.lignes.order_by("rang"):  # tri direct, sans jointure sur le document
        form = formulaires_lignes.get(ligne.pk) or LigneForm(
            prefix=_prefixe_ligne(ligne),
            initial={"designation": ligne.designation, "quantite": ligne.quantite, "prix_unitaire": ligne.prix_unitaire},
        )
        lignes.append({"ligne": ligne, "form": form})
    return {
        "document": document,
        "lignes": lignes,
        "entete_form": entete_form or _formulaire_entete(document),
        "ajout_form": ajout_form or LigneForm(prefix=PREFIXE_NOUVELLE_LIGNE, initial={"quantite": 1}),
        "ajout_produit_form": ajout_produit_form or AjoutProduitForm(),
        "lignes_max": services.LIGNES_MAX,
    }


def _repondre_lignes(request, document, en_erreur=False, **formulaires):
    """Fragment des lignes et des totaux (HTMX) ; sans HTMX, retour à la page ou page en erreur."""
    document.refresh_from_db()
    if _est_htmx(request):
        return render(request, "facturation/_lignes.html", _contexte_edition(document, **formulaires))
    if en_erreur:
        return render(request, "facturation/document_edit.html", _contexte_edition(document, **formulaires))
    return redirect("facturation:document-edit", pk=document.pk)


def _brouillon(pk):
    return get_object_or_404(Document.objects.select_related("contact"), pk=pk)


@manage_invoices_required
def document_list(request):
    page_obj = Paginator(services.lister_documents(), DOCUMENTS_PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "facturation/document_list.html", {"page_obj": page_obj, "documents": page_obj.object_list})


@manage_invoices_required
def document_create(request, type_document):
    if type_document not in Document.Type.values:
        raise Http404
    profil = ProfilEmetteur.get()
    form = DocumentForm(
        request.POST or None,
        type_document=type_document,
        initial={"taux_tva": profil.taux_tva_defaut, "validite_jours": profil.validite_devis_jours},
    )
    if request.method == "POST" and form.is_valid():
        donnees = form.cleaned_data
        try:
            document = services.creer_brouillon(
                type_document, donnees["contact"], request.user,
                objet=donnees["objet"], lieu_livraison=donnees["lieu_livraison"],
                taux_tva=donnees["taux_tva"], validite_jours=donnees.get("validite_jours"),
            )
        except ErreurFacturation as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"{document.get_type_display()} brouillon créé : ajoutez les lignes.")
            return redirect("facturation:document-edit", pk=document.pk)
    return render(request, "facturation/document_create.html", {
        "form": form, "type_document": type_document, "type_libelle": Document.Type(type_document).label,
    })


@manage_invoices_required
def document_edit(request, pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    entete_form = None
    if request.method == "POST":
        entete_form = _formulaire_entete(document, request.POST)
        if entete_form.is_valid():
            champs = {c: entete_form.cleaned_data[c] for c in entete_form.changed_data}
            if not champs:
                messages.info(request, "Aucune modification.")
                return redirect("facturation:document-edit", pk=document.pk)
            try:
                services.modifier_brouillon(document, request.user, **champs)
            except DocumentNonModifiable:
                return _refuser_non_brouillon(request)
            except ErreurFacturation as exc:
                entete_form.add_error(None, str(exc))
            else:
                messages.success(request, "En-tête enregistré.")
                return redirect("facturation:document-edit", pk=document.pk)
    return render(request, "facturation/document_edit.html", _contexte_edition(document, entete_form=entete_form))


@require_POST
@manage_invoices_required
def ligne_add(request, pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    form = LigneForm(request.POST, prefix=PREFIXE_NOUVELLE_LIGNE)
    if form.is_valid():
        try:
            services.ajouter_ligne(document, request.user, **form.cleaned_data)
        except DocumentNonModifiable:
            return _refuser_non_brouillon(request)
        except ErreurFacturation as exc:
            form.add_error(None, str(exc))
        else:
            form = None  # ligne ajoutée : formulaire vierge
    return _repondre_lignes(request, document, en_erreur=form is not None, ajout_form=form)


@require_POST
@manage_invoices_required
def ligne_add_produit(request, pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    form = AjoutProduitForm(request.POST)
    if form.is_valid():
        try:
            services.ajouter_produit(document, request.user, form.cleaned_data["produit"], quantite=1)
        except DocumentNonModifiable:
            return _refuser_non_brouillon(request)
        except ErreurFacturation as exc:
            form.add_error(None, str(exc))
        else:
            form = None
    return _repondre_lignes(request, document, en_erreur=form is not None, ajout_produit_form=form)


@require_POST
@manage_invoices_required
def ligne_update(request, pk, ligne_pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    ligne = get_object_or_404(LigneDocument, pk=ligne_pk, document=document)
    form = LigneForm(request.POST, prefix=_prefixe_ligne(ligne))
    formulaires_lignes = {}
    if form.is_valid():
        try:
            services.modifier_ligne(ligne, request.user, **form.cleaned_data)
        except DocumentNonModifiable:
            return _refuser_non_brouillon(request)
        except ErreurFacturation as exc:
            form.add_error(None, str(exc))
            formulaires_lignes[ligne.pk] = form
    else:
        formulaires_lignes[ligne.pk] = form
    return _repondre_lignes(request, document, en_erreur=bool(formulaires_lignes), formulaires_lignes=formulaires_lignes)


@require_POST
@manage_invoices_required
def ligne_delete(request, pk, ligne_pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    ligne = get_object_or_404(LigneDocument, pk=ligne_pk, document=document)
    try:
        services.supprimer_ligne(ligne, request.user)
    except DocumentNonModifiable:
        return _refuser_non_brouillon(request)
    return _repondre_lignes(request, document)


@manage_invoices_required
def document_delete(request, pk):
    document = _brouillon(pk)
    if not document.est_brouillon:
        return _refuser_non_brouillon(request)
    if request.method == "POST":
        libelle = f"{document.get_type_display()} brouillon"
        try:
            services.supprimer_brouillon(document, request.user)
        except DocumentNonModifiable:
            return _refuser_non_brouillon(request)
        messages.success(request, f"{libelle} supprimé.")
        return redirect("facturation:document-list")
    return render(request, "facturation/document_confirm_delete.html", {"document": document})
