from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.db.models import Q

from visits.models import Visit, VisitPhoto


@login_required
def private_media(request, name):
    """Serve only visit files visible to the authenticated user."""
    photo = VisitPhoto.objects.select_related("visit__mission__site").filter(image=name).first()
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
    file = photo.image if photo else (
        visit.signature_superviseur if visit.signature_superviseur.name == name
        else visit.signature_responsable
    )
    try:
        response = FileResponse(file.open("rb"))
    except FileNotFoundError:
        raise Http404
    # Ne jamais servir un contenu actif (HTML ou SVG) sous le domaine de l'application.
    suffix = name.rsplit('.', 1)[-1].lower()
    response['Content-Type'] = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}.get(suffix, 'application/octet-stream')
    if response['Content-Type'] == 'application/octet-stream':
        response['Content-Disposition'] = 'attachment'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
