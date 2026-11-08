from django.db import transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Replace

from core.images import nom_aleatoire, optimiser_image_png
from core.services import log

from .models import ContactClient

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
