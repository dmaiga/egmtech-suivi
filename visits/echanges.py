import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from core.images import nom_aleatoire, nom_sur, optimiser_image

from .models import Echange, EchangeFichier, EchangeMessage, Visit

EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXT_DOCUMENTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}

_VISIBLE_CLIENT = Q(visit__isnull=True) | Q(visit__statut=Visit.Statut.PUBLIEE)


def echange_accessible(echange):
    """Un échange lié à une visite n'est actif que tant que la visite est publiée."""
    return echange.visit_id is None or echange.visit.statut == Visit.Statut.PUBLIEE


def preparer_fichiers(fichiers):
    """Valide les pièces jointes ; optimise les images. Retourne (prêts, erreurs)."""
    prets, erreurs = [], []
    if len(fichiers) > settings.ECHANGES_MAX_FICHIERS:
        return [], [f"Maximum {settings.ECHANGES_MAX_FICHIERS} pièces jointes par message."]
    max_mb = settings.ECHANGES_MAX_FICHIER_BYTES // (1024 * 1024)
    for f in fichiers:
        nom = nom_sur(f.name)
        ext = os.path.splitext(nom)[1].lower()
        if f.size > settings.ECHANGES_MAX_FICHIER_BYTES:
            erreurs.append(f"« {nom} » dépasse {max_mb} Mo.")
        elif ext in EXT_IMAGES:
            try:
                image, miniature = optimiser_image(f)
            except ValueError:
                erreurs.append(f"« {nom} » n'est pas une image valide.")
                continue
            prets.append({"nom": nom, "fichier": image, "miniature": miniature, "est_image": True})
        elif ext in EXT_DOCUMENTS:
            f.seek(0)
            prets.append({
                "nom": nom, "fichier": ContentFile(f.read(), name=nom_aleatoire(ext)),
                "miniature": None, "est_image": False,
            })
        else:
            erreurs.append(f"« {nom} » : type de fichier non autorisé.")
    return prets, erreurs


def creer_echange(client, auteur, sujet, texte, visit=None, fichiers=()):
    echange = Echange.objects.create(client=client, visit=visit, sujet=sujet)
    envoyer_message(echange, auteur, texte, fichiers)
    return echange


def envoyer_message(echange, auteur, texte, fichiers=()):
    """Ajoute un message ; un message du client rouvre un échange clos."""
    message = EchangeMessage.objects.create(echange=echange, auteur=auteur, texte=texte)
    for f in fichiers:
        EchangeFichier.objects.create(
            message=message, fichier=f["fichier"], miniature=f["miniature"] or "",
            nom_original=f["nom"], est_image=f["est_image"], taille=f["fichier"].size,
        )
    echange.dernier_message_le = message.created_at
    if auteur.role == User.Role.CLIENT:
        echange.statut = Echange.Statut.OUVERT
    echange.save(update_fields=["dernier_message_le", "statut"])
    return message


def _non_lus(echanges, cote_client):
    """Messages non lus par la partie `cote_client` (True = client, False = équipe)."""
    from_client = Q(messages__auteur__role=User.Role.CLIENT)
    autre_cote = ~from_client if cote_client else from_client
    return echanges.annotate(
        non_lus=Count("messages", filter=autre_cote & Q(messages__lu_le__isnull=True))
    )


def echanges_manager():
    return _non_lus(Echange.objects.select_related("client", "visit__mission__site"), False)


def echanges_client(client):
    qs = Echange.objects.filter(_VISIBLE_CLIENT, client=client).select_related(
        "visit__mission__site", "visit__mission__attached_form"
    )
    return _non_lus(qs, True)


def nb_non_lus_manager():
    return EchangeMessage.objects.filter(
        auteur__role=User.Role.CLIENT, lu_le__isnull=True
    ).count()


def nb_non_lus_client(client):
    return (
        EchangeMessage.objects.filter(
            Q(echange__visit__isnull=True) | Q(echange__visit__statut=Visit.Statut.PUBLIEE),
            echange__client=client,
            lu_le__isnull=True,
        )
        .exclude(auteur__role=User.Role.CLIENT)
        .count()
    )


def marquer_lus(echange, cote_client):
    qs = echange.messages.filter(lu_le__isnull=True)
    qs = qs.exclude(auteur__role=User.Role.CLIENT) if cote_client else qs.filter(auteur__role=User.Role.CLIENT)
    qs.update(lu_le=timezone.now())


def sujet_par_defaut(visit):
    return f"{visit.mission.attached_form.nom} - {visit.mission.site.nom}"
