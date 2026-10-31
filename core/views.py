from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.db.models import Q

from visits.models import EchangeFichier, Visit, VisitPhoto


def _servir(file, name, inline_image=True, download_name=None):
    try:
        response = FileResponse(file.open("rb"))
    except FileNotFoundError:
        raise Http404
    # Ne jamais servir un contenu actif (HTML ou SVG) sous le domaine de l'application.
    suffix = name.rsplit('.', 1)[-1].lower()
    response['Content-Type'] = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}.get(suffix, 'application/octet-stream')
    if response['Content-Type'] == 'application/octet-stream':
        response['Content-Disposition'] = 'attachment'
        if download_name:
            response['Content-Disposition'] = f'attachment; filename="{download_name}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _echange_fichier(request, name):
    from visits.echanges import echange_accessible

    pj = (
        EchangeFichier.objects.select_related("message__echange__visit")
        .filter(Q(fichier=name) | Q(miniature=name))
        .first()
    )
    if not pj:
        return None
    echange = pj.message.echange
    user = request.user
    allowed = (
        user.is_superuser or user.has_perm("visits.validate_visits")
        or (user.is_client() and user.client_id == echange.client_id and echange_accessible(echange))
    )
    if not allowed:
        raise Http404
    file = pj.fichier if pj.fichier.name == name else pj.miniature
    return _servir(file, name, download_name=pj.nom_original.replace('"', ""))


@login_required
def private_media(request, name):
    """Serve only files visible to the authenticated user."""
    response = _echange_fichier(request, name)
    if response:
        return response
    photo = VisitPhoto.objects.select_related("visit__mission__site").filter(
        Q(image=name) | Q(miniature=name)
    ).first()
    visit = photo.visit if photo else Visit.objects.select_related("mission__site").filter(
        Q(signature_superviseur=name) | Q(signature_responsable=name)
    ).first()
    if not visit:
        raise Http404
    user = request.user
    allowed = (
        user.is_superuser or user.is_manager() or user.has_perm("visits.validate_visits")
        or (user.is_superviseur() and visit.auteur_id == user.pk)
        or (user.is_client() and visit.mission.site.client_id == user.client_id
            and visit.statut == Visit.Statut.PUBLIEE)
    )
    if not allowed:
        raise Http404
    if photo:
        file = photo.image if photo.image.name == name else photo.miniature
    else:
        file = (
            visit.signature_superviseur if visit.signature_superviseur.name == name
            else visit.signature_responsable
        )
    return _servir(file, name)
