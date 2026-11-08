"""Documents : liste, création, édition d'un brouillon et de ses lignes (HTMX),
détail en lecture seule et actions du cycle de vie (formulaires POST classiques).

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
from .exceptions import DocumentNonModifiable, ErreurFacturation, TransitionInterdite
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
    return get_object_or_404(Document.objects.select_related("contact", "source"), pk=pk)


def _page_du_document(document):
    """Édition pour un brouillon, détail sinon."""
    vue = "facturation:document-edit" if document.est_brouillon else "facturation:document-detail"
    return reverse(vue, args=[document.pk])


@manage_invoices_required
def document_list(request):
    page_obj = Paginator(services.lister_documents(), DOCUMENTS_PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "facturation/document_list.html", {"page_obj": page_obj, "documents": page_obj.object_list})


@manage_invoices_required
def document_detail(request, pk):
    document = get_object_or_404(Document.objects.select_related("source"), pk=pk)
    if document.est_brouillon:
        return redirect("facturation:document-edit", pk=document.pk)
    return render(request, "facturation/document_detail.html", {
        "document": document, **services.detail_document(document),
    })


# Message affiché après chaque action réussie, selon l'action et le type du document.
MESSAGES_ACTION = {
    ("emettre", Document.Type.DEVIS): "Devis {numero} envoyé.",
    ("emettre", Document.Type.FACTURE): "Facture {numero} émise.",
    ("accepter", Document.Type.DEVIS): "Devis {numero} accepté.",
    ("refuser", Document.Type.DEVIS): "Devis {numero} refusé.",
    ("payer", Document.Type.FACTURE): "Facture {numero} marquée payée.",
    ("annuler", Document.Type.FACTURE): "Facture {numero} annulée.",
}


def _message_action(action, document):
    return MESSAGES_ACTION[(action, document.type)].format(numero=document.numero)


def _refuser_action(request, document):
    """Transition refusée (état changé entre-temps, double clic) : état actuel et retour au document."""
    document.refresh_from_db()
    messages.error(request, (
        f"Action impossible : {document} est actuellement « {document.get_statut_display()} ». "
        "Il a peut-être été modifié entre-temps ; la page a été actualisée."
    ))
    return redirect(_page_du_document(document))


def _document_disparu(request):
    messages.error(request, "Ce document n'existe plus.")
    return redirect("facturation:document-list")


@require_POST
@manage_invoices_required
def document_action(request, pk, action):
    """Émettre, accepter, refuser, marquer payée, annuler : la transition est vérifiée par le service."""
    document = get_object_or_404(Document, pk=pk)
    try:
        services.appliquer_action(document, action, request.user)
    except Document.DoesNotExist:
        return _document_disparu(request)
    except TransitionInterdite:
        return _refuser_action(request, document)
    except ErreurFacturation as exc:
        messages.error(request, str(exc))
        document.refresh_from_db()
    else:
        messages.success(request, _message_action(action, document))
    return redirect(_page_du_document(document))


@require_POST
@manage_invoices_required
def document_convertir(request, pk):
    devis = get_object_or_404(Document, pk=pk)
    try:
        facture = services.convertir_en_facture(devis, request.user)
    except Document.DoesNotExist:
        return _document_disparu(request)
    except ErreurFacturation as exc:
        messages.error(request, str(exc))
        devis.refresh_from_db()
        return redirect(_page_du_document(devis))
    messages.success(request, f"Facture brouillon créée depuis le devis {devis.numero} : vérifiez-la puis émettez-la.")
    return redirect("facturation:document-edit", pk=facture.pk)


@require_POST
@manage_invoices_required
def document_dupliquer(request, pk):
    document = get_object_or_404(Document.objects.select_related("contact"), pk=pk)
    try:
        copie = services.dupliquer(document, request.user)
    except ErreurFacturation as exc:
        messages.error(request, str(exc))
        return redirect(_page_du_document(document))
    messages.success(request, f"Copie de {document} créée en brouillon : taux de TVA et validité repris du profil.")
    return redirect("facturation:document-edit", pk=copie.pk)


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
