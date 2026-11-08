from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Replace
from django.utils import timezone

from core.images import nom_aleatoire, optimiser_image_png
from core.services import log

from .exceptions import (
    ConversionImpossible,
    DocumentNonModifiable,
    ErreurFacturation,
    MontantInvalide,
    TransitionInterdite,
)
from .models import (
    PAS_MONTANT,
    PRIX_UNITAIRE_MAX,
    QUANTITE_MAX,
    QUANTITE_MIN,
    TAUX_TVA_MAX,
    TAUX_TVA_MIN,
    VALIDITE_DEVIS_MAX,
    VALIDITE_DEVIS_MIN,
    ContactClient,
    Document,
    HistoriqueStatut,
    LigneDocument,
    Produit,
    ProfilEmetteur,
    SequenceNumero,
)

IMAGES_PROFIL = ("logo", "cachet")
IMAGE_PROFIL_MAX_BYTES = 5 * 1024 * 1024
IMAGE_PROFIL_COTE_MAX = 1200


def preparer_image_profil(fichier):
    """Valide un logo ou un cachet envoyé et le convertit en PNG. ValueError avec un message lisible."""
    if fichier.size > IMAGE_PROFIL_MAX_BYTES:
        raise ValueError(f"L'image dépasse {IMAGE_PROFIL_MAX_BYTES // (1024 * 1024)} Mo.")
    try:
        return optimiser_image_png(fichier, IMAGE_PROFIL_COTE_MAX)
    except ValueError as exc:
        raise ValueError("Ce fichier n'est pas une image valide.") from exc


def modifier_profil(form, user):
    """Enregistre le profil depuis ProfilEmetteurForm valide ; remplace ou retire logo et cachet.

    Les anciens fichiers ne sont supprimés du stockage qu'une fois la transaction validée.
    """
    profil = form.save(commit=False)
    anciens = []
    champs_images = []
    for champ in IMAGES_PROFIL:
        nouveau = form.cleaned_data.get(champ)
        retirer = form.cleaned_data.get(f"retirer_{champ}")
        if not (nouveau or retirer):
            continue
        fichier = getattr(profil, champ)
        if fichier:
            anciens.append(fichier.name)
        if nouveau:
            fichier.save(nom_aleatoire(".png"), nouveau, save=False)
        else:
            setattr(profil, champ, "")
        champs_images.append(champ)

    with transaction.atomic():
        profil.save()
        champs = {c for c in form.changed_data if not c.startswith("retirer_")} | set(champs_images)
        log(user, "modification_profil_emetteur", profil, detail={"champs": sorted(champs)})
        storage = profil.logo.storage
        for nom in anciens:
            transaction.on_commit(lambda nom=nom: storage.delete(nom))
    return profil


SEPARATEURS_TELEPHONE = (" ", ".", "-")


def normaliser_telephone(telephone):
    """Téléphone sans espaces, points ni tirets : « 76 12-34.56 » devient « 76123456 »."""
    for separateur in SEPARATEURS_TELEPHONE:
        telephone = telephone.replace(separateur, "")
    return telephone


def _telephone_normalise_sql():
    """Même normalisation que normaliser_telephone, calculée par la base (REPLACE, sans colonne)."""
    expression = F("telephone")
    for separateur in SEPARATEURS_TELEPHONE:
        expression = Replace(expression, Value(separateur), Value(""))
    return expression


def rechercher_contacts(q="", inclure_inactifs=False):
    """Contacts triés par nom, filtrés par nom (contient, sans casse) ou par téléphone
    (contient, séparateurs ignorés des deux côtés)."""
    contacts = ContactClient.objects.all()
    if not inclure_inactifs:
        contacts = contacts.filter(actif=True)
    q = (q or "").strip()
    if q:
        filtre = Q(nom__icontains=q)
        telephone = normaliser_telephone(q)
        if telephone:
            contacts = contacts.annotate(telephone_normalise=_telephone_normalise_sql())
            filtre |= Q(telephone_normalise__icontains=telephone)
        contacts = contacts.filter(filtre)
    return contacts


def creer_contact(form, user):
    contact = form.save()
    log(user, "creation_contact_facturation", contact)
    return contact


def modifier_contact(form, user):
    contact = form.save()
    log(user, "modification_contact_facturation", contact, detail={"champs": form.changed_data})
    return contact


def changer_activation_contact(contact, actif, user):
    """Désactive ou réactive un contact ; un contact n'est jamais supprimé."""
    if contact.actif == actif:
        return contact
    contact.actif = actif
    contact.save(update_fields=["actif"])
    action = "reactivation_contact_facturation" if actif else "desactivation_contact_facturation"
    log(user, action, contact)
    return contact


# ---------------------------------------------------------------------------
# Montants (FCFA) : entiers uniquement, jamais de float ni de Decimal.
# ---------------------------------------------------------------------------

def _exiger_entier(valeur, libelle):
    # bool est un sous-type de int en Python : on le refuse explicitement.
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise MontantInvalide(f"{libelle} doit être un nombre entier.")
    return valeur


def arrondir_au_multiple_de_5(numerateur, denominateur):
    """Multiple de 5 le plus proche de numerateur / denominateur, demi vers le haut.

    Seule fonction d'arrondi des montants. Arithmétique entière :
    floor(n / d / 5 + 1/2) x 5 = floor((2n + 5d) / 10d) x 5.
    """
    _exiger_entier(numerateur, "Le numérateur")
    _exiger_entier(denominateur, "Le dénominateur")
    if numerateur < 0 or denominateur <= 0:
        raise MontantInvalide("Arrondi défini pour un numérateur positif et un dénominateur strictement positif.")
    return (2 * numerateur + PAS_MONTANT * denominateur) // (2 * PAS_MONTANT * denominateur) * PAS_MONTANT


def verifier_quantite(quantite):
    _exiger_entier(quantite, "La quantité")
    if not QUANTITE_MIN <= quantite <= QUANTITE_MAX:
        raise MontantInvalide(f"La quantité doit être comprise entre {QUANTITE_MIN} et {QUANTITE_MAX}.")
    return quantite


def verifier_prix_unitaire(prix):
    _exiger_entier(prix, "Le prix unitaire")
    if prix <= 0 or prix > PRIX_UNITAIRE_MAX:
        raise MontantInvalide(f"Le prix unitaire doit être compris entre {PAS_MONTANT} et {PRIX_UNITAIRE_MAX} FCFA.")
    if prix % PAS_MONTANT:
        raise MontantInvalide(f"Le prix unitaire doit être un multiple de {PAS_MONTANT} FCFA.")
    return prix


def verifier_taux_tva(taux):
    _exiger_entier(taux, "Le taux de TVA")
    if not TAUX_TVA_MIN <= taux <= TAUX_TVA_MAX:
        raise MontantInvalide(f"Le taux de TVA doit être compris entre {TAUX_TVA_MIN} et {TAUX_TVA_MAX} %.")
    return taux


def verifier_validite_jours(jours):
    if isinstance(jours, bool) or not isinstance(jours, int) or not VALIDITE_DEVIS_MIN <= jours <= VALIDITE_DEVIS_MAX:
        raise ErreurFacturation(
            f"La validité doit être un nombre entier de jours entre {VALIDITE_DEVIS_MIN} et {VALIDITE_DEVIS_MAX}."
        )
    return jours


def calculer_total_ligne(quantite, prix_unitaire):
    return verifier_quantite(quantite) * verifier_prix_unitaire(prix_unitaire)


def calculer_tva(total_ht, taux):
    """TVA = HT x taux / 100, arrondie au multiple de 5 le plus proche (demi vers le haut)."""
    _exiger_entier(total_ht, "Le total HT")
    return arrondir_au_multiple_de_5(total_ht * verifier_taux_tva(taux), 100)


def calculer_totaux(totaux_lignes, taux):
    """Retourne (HT, TVA, TTC) à partir des totaux de lignes."""
    total_ht = sum(totaux_lignes)
    total_tva = calculer_tva(total_ht, taux)
    return total_ht, total_tva, total_ht + total_tva


# ---------------------------------------------------------------------------
# Produits : désactivés, jamais supprimés.
# ---------------------------------------------------------------------------

def creer_produit(designation, prix_unitaire, user):
    produit = Produit.objects.create(designation=designation, prix_unitaire=verifier_prix_unitaire(prix_unitaire))
    log(user, "creation_produit", produit)
    return produit


def modifier_produit(produit, user, designation=None, prix_unitaire=None):
    """Modifie le catalogue ; les lignes déjà copiées dans des documents ne changent pas."""
    if designation is not None:
        produit.designation = designation
    if prix_unitaire is not None:
        produit.prix_unitaire = verifier_prix_unitaire(prix_unitaire)
    produit.save()
    log(user, "modification_produit", produit)
    return produit


def changer_activation_produit(produit, actif, user):
    if produit.actif == actif:
        return produit
    produit.actif = actif
    produit.save(update_fields=["actif"])
    log(user, "reactivation_produit" if actif else "desactivation_produit", produit)
    return produit


# ---------------------------------------------------------------------------
# Documents : brouillons, lignes, totaux.
# ---------------------------------------------------------------------------

S = Document.Statut
T = Document.Type

# Cycle de vie : seules ces transitions existent.
TRANSITIONS = {
    T.DEVIS: {S.BROUILLON: {S.ENVOYE}, S.ENVOYE: {S.ACCEPTE, S.REFUSE}},
    T.FACTURE: {S.BROUILLON: {S.EMISE}, S.EMISE: {S.PAYEE, S.ANNULEE}},
}
STATUT_EMISSION = {T.DEVIS: S.ENVOYE, T.FACTURE: S.EMISE}
PREFIXES_NUMERO = {T.DEVIS: "DEV", T.FACTURE: "FAC"}
CHAMPS_BROUILLON_MODIFIABLES = {"contact", "objet", "lieu_livraison", "taux_tva", "validite_jours"}


def _historiser(document, ancien, nouveau, user):
    HistoriqueStatut.objects.create(document=document, ancien_statut=ancien, nouveau_statut=nouveau, utilisateur=user)


def _copier_contact(document, contact):
    document.contact = contact
    document.contact_nom = contact.nom
    document.contact_telephone = contact.telephone
    document.contact_adresse = contact.adresse


def _verrouiller(document):
    """Relit le document en base avec un verrou de ligne (à appeler dans une transaction)."""
    return Document.objects.select_for_update().get(pk=document.pk)


def _verrouiller_brouillon(document):
    verrouille = _verrouiller(document)
    if not verrouille.est_brouillon:
        raise DocumentNonModifiable(f"{verrouille} n'est plus un brouillon : il ne peut plus être modifié.")
    return verrouille


def _recalculer_totaux(document):
    totaux = document.lignes.values_list("total", flat=True)
    document.total_ht, document.total_tva, document.total_ttc = calculer_totaux(totaux, document.taux_tva)
    document.save(update_fields=["total_ht", "total_tva", "total_ttc", "updated_at"])


def _creer_ligne(document, designation, quantite, prix_unitaire, produit=None):
    designation = (designation or "").strip()
    if not designation:
        raise ErreurFacturation("Une ligne doit avoir une désignation.")
    rang = (document.lignes.order_by("-rang").values_list("rang", flat=True).first() or 0) + 1
    return LigneDocument.objects.create(
        document=document,
        rang=rang,
        designation=designation,
        quantite=quantite,
        prix_unitaire=prix_unitaire,
        total=calculer_total_ligne(quantite, prix_unitaire),
        produit=produit,
    )


def _copie_lignes(document):
    return [
        {"designation": l.designation, "quantite": l.quantite, "prix_unitaire": l.prix_unitaire, "produit": l.produit}
        for l in document.lignes.all()
    ]


def _nouveau_brouillon(type_document, contact, user, objet, lieu_livraison, taux_tva, validite_jours, lignes, source=None):
    document = Document(
        type=type_document,
        objet=objet,
        lieu_livraison=lieu_livraison,
        taux_tva=verifier_taux_tva(taux_tva),
        validite_jours=verifier_validite_jours(validite_jours) if type_document == T.DEVIS else None,
        source=source,
        cree_par=user,
    )
    _copier_contact(document, contact)
    document.save()
    _historiser(document, "", S.BROUILLON, user)
    for ligne in lignes:
        _creer_ligne(document, **ligne)
    _recalculer_totaux(document)
    return document


def creer_brouillon(type_document, contact, user, objet="", lieu_livraison="", lignes=()):
    """Nouveau devis ou facture en brouillon ; taux de TVA et validité repris du profil émetteur.

    `lignes` : dictionnaires {designation, quantite, prix_unitaire[, produit]}.
    """
    if type_document not in TRANSITIONS:
        raise ErreurFacturation("Type de document inconnu.")
    profil = ProfilEmetteur.get()
    with transaction.atomic():
        document = _nouveau_brouillon(
            type_document, contact, user, objet, lieu_livraison,
            taux_tva=profil.taux_tva_defaut, validite_jours=profil.validite_devis_jours, lignes=lignes,
        )
        log(user, "creation_document", document, detail={"type": type_document})
    return document


def modifier_brouillon(document, user, **champs):
    """Modifie contact, objet, lieu de livraison, taux de TVA ou validité d'un brouillon."""
    inconnus = set(champs) - CHAMPS_BROUILLON_MODIFIABLES
    if inconnus:
        raise ErreurFacturation(f"Champs non modifiables : {', '.join(sorted(inconnus))}.")
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(document)
        if "taux_tva" in champs:
            verrouille.taux_tva = verifier_taux_tva(champs["taux_tva"])
        if "validite_jours" in champs:
            if verrouille.type != T.DEVIS:
                raise ErreurFacturation("Seul un devis a une durée de validité.")
            verrouille.validite_jours = verifier_validite_jours(champs["validite_jours"])
        if "contact" in champs:
            _copier_contact(verrouille, champs["contact"])
        for champ in ("objet", "lieu_livraison"):
            if champ in champs:
                setattr(verrouille, champ, champs[champ])
        verrouille.save()
        _recalculer_totaux(verrouille)
        log(user, "modification_document", verrouille, detail={"champs": sorted(champs)})
    document.refresh_from_db()
    return document


def ajouter_ligne(document, user, designation, quantite, prix_unitaire, produit=None):
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(document)
        ligne = _creer_ligne(verrouille, designation, quantite, prix_unitaire, produit)
        _recalculer_totaux(verrouille)
        log(user, "modification_lignes_document", verrouille, detail={"ajout": ligne.rang})
    document.refresh_from_db()
    return ligne


def ajouter_produit(document, user, produit, quantite=1):
    """Copie la désignation et le prix d'un produit actif dans une nouvelle ligne."""
    if not produit.actif:
        raise ErreurFacturation(f"Le produit « {produit} » est désactivé.")
    return ajouter_ligne(document, user, produit.designation, quantite, produit.prix_unitaire, produit=produit)


def modifier_ligne(ligne, user, designation=None, quantite=None, prix_unitaire=None):
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(ligne.document)
        ligne = LigneDocument.objects.get(pk=ligne.pk, document=verrouille)
        if designation is not None:
            if not designation.strip():
                raise ErreurFacturation("Une ligne doit avoir une désignation.")
            ligne.designation = designation.strip()
        if quantite is not None:
            ligne.quantite = quantite
        if prix_unitaire is not None:
            ligne.prix_unitaire = prix_unitaire
        ligne.total = calculer_total_ligne(ligne.quantite, ligne.prix_unitaire)
        ligne.save()
        _recalculer_totaux(verrouille)
        log(user, "modification_lignes_document", verrouille, detail={"modification": ligne.rang})
    return ligne


def supprimer_ligne(ligne, user):
    """Supprime une ligne d'un brouillon et renumérote les suivantes."""
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(ligne.document)
        rang = ligne.rang
        LigneDocument.objects.filter(pk=ligne.pk, document=verrouille).delete()
        # Ordre croissant : chaque rang visé vient d'être libéré (contrainte d'unicité).
        for suivante in verrouille.lignes.filter(rang__gt=rang).order_by("rang"):
            suivante.rang -= 1
            suivante.save(update_fields=["rang"])
        _recalculer_totaux(verrouille)
        log(user, "modification_lignes_document", verrouille, detail={"suppression": rang})


def remplacer_lignes(document, user, lignes):
    """Remplace toutes les lignes d'un brouillon (même format que creer_brouillon)."""
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(document)
        verrouille.lignes.all().delete()
        for ligne in lignes:
            _creer_ligne(verrouille, **ligne)
        _recalculer_totaux(verrouille)
        log(user, "modification_lignes_document", verrouille, detail={"remplacement": len(lignes)})
    document.refresh_from_db()
    return document


def supprimer_brouillon(document, user):
    """Seuls les brouillons se suppriment ; un document émis reste à vie."""
    with transaction.atomic():
        verrouille = _verrouiller_brouillon(document)
        log(user, "suppression_document", verrouille, detail={"type": verrouille.type})
        verrouille.delete()


# ---------------------------------------------------------------------------
# Numérotation et cycle de vie.
# ---------------------------------------------------------------------------

def attribuer_numero(type_document, annee):
    """Numéro suivant DEV-AAAA-NNNN ou FAC-AAAA-NNNN : une suite par type et par année.

    Verrou sur la ligne de séquence jusqu'à la fin de la transaction de l'appelant : pas de doublon,
    et pas de trou puisque l'incrément est annulé avec elle si l'émission échoue.
    """
    with transaction.atomic():
        sequence = SequenceNumero.objects.select_for_update().filter(type=type_document, annee=annee).first()
        if sequence is None:
            # Première émission de l'année pour ce type. Laisser plusieurs transactions tenter
            # l'INSERT en même temps provoque un deadlock sous InnoDB (verrous partagés posés sur le
            # doublon, puis demandes de verrou exclusif croisées). On sérialise donc la création
            # derrière le verrou de la ligne du profil émetteur, qui existe toujours ; la transaction
            # suivante relit la séquence validée entre-temps (isolation READ COMMITTED).
            ProfilEmetteur.get()
            ProfilEmetteur.objects.select_for_update().get(singleton=True)
            sequence, _ = SequenceNumero.objects.select_for_update().get_or_create(type=type_document, annee=annee)
        sequence.dernier += 1
        sequence.save(update_fields=["dernier"])
    return f"{PREFIXES_NUMERO[type_document]}-{annee}-{sequence.dernier:04d}"


def _preparer_emission(document):
    """Fige le document : totaux, contact, dates, numéro."""
    if not document.lignes.exists():
        raise ErreurFacturation("Un document sans ligne ne peut pas être émis.")
    totaux = document.lignes.values_list("total", flat=True)
    document.total_ht, document.total_tva, document.total_ttc = calculer_totaux(totaux, document.taux_tva)
    _copier_contact(document, document.contact)
    document.date_emission = timezone.localdate()
    if document.type == T.DEVIS:
        document.date_validite = document.date_emission + timedelta(days=document.validite_jours)
    document.numero = attribuer_numero(document.type, document.date_emission.year)


def changer_statut(document, nouveau_statut, user):
    """Applique une transition du cycle de vie ; toute autre transition lève TransitionInterdite."""
    with transaction.atomic():
        verrouille = _verrouiller(document)
        ancien = verrouille.statut
        if nouveau_statut not in TRANSITIONS[verrouille.type].get(ancien, set()):
            raise TransitionInterdite(
                f"{verrouille.get_type_display()} : passage de « {S(ancien).label} » à "
                f"« {S(nouveau_statut).label if nouveau_statut in S.values else nouveau_statut} » interdit."
            )
        if ancien == S.BROUILLON:
            _preparer_emission(verrouille)
        verrouille.statut = nouveau_statut
        verrouille.save()
        _historiser(verrouille, ancien, nouveau_statut, user)
        log(user, "transition_document", verrouille, detail={
            "ancien": ancien, "nouveau": nouveau_statut, "numero": verrouille.numero,
        })
    document.refresh_from_db()
    return document


def emettre(document, user):
    """Envoie un devis ou émet une facture (numéro attribué)."""
    return changer_statut(document, STATUT_EMISSION[document.type], user)


def facture_active(devis):
    """Facture non annulée issue de ce devis (brouillon compris), ou None."""
    return devis.factures.exclude(statut=S.ANNULEE).first()


def convertir_en_facture(devis, user):
    """Facture brouillon reprenant un devis accepté. Le devis n'est pas modifié.

    Un devis n'a qu'une facture non annulée à la fois : la vérification se fait sous verrou du devis.
    """
    with transaction.atomic():
        verrouille = _verrouiller(devis)
        if verrouille.type != T.DEVIS or verrouille.statut != S.ACCEPTE:
            raise ConversionImpossible("Seul un devis accepté peut être converti en facture.")
        existante = facture_active(verrouille)
        if existante is not None:
            raise ConversionImpossible(
                f"Le devis {verrouille.numero} a déjà une facture en cours ({existante}) : l'annuler d'abord."
            )
        facture = _nouveau_brouillon(
            T.FACTURE, verrouille.contact, user, verrouille.objet, verrouille.lieu_livraison,
            taux_tva=verrouille.taux_tva, validite_jours=None, lignes=_copie_lignes(verrouille), source=verrouille,
        )
        log(user, "conversion_devis", facture, detail={"devis_id": verrouille.pk, "devis": verrouille.numero})
    return facture


def dupliquer(document, user):
    """Nouveau brouillon du même type : lignes, objet, lieu et contact copiés ; taux et validité du profil."""
    profil = ProfilEmetteur.get()
    with transaction.atomic():
        copie = _nouveau_brouillon(
            document.type, document.contact, user, document.objet, document.lieu_livraison,
            taux_tva=profil.taux_tva_defaut, validite_jours=profil.validite_devis_jours,
            lignes=_copie_lignes(document),
        )
        log(user, "duplication_document", copie, detail={"origine_id": document.pk})
    return copie
