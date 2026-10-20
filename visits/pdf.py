"""Génération des PDF de visite.

Le rendu passe par un gabarit HTML unique (templates/visits/pdf/visit_pdf.html)
converti en PDF par xhtml2pdf (pur Python, sans dépendance système). Si ce
moteur se révèle insuffisant, ne changer que `_html_to_pdf` ci-dessous : le
reste du module (contexte, nommage, ZIP) n'a pas besoin de bouger.
"""

import io
import os
import zipfile

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.text import slugify
from xhtml2pdf import pisa

from .schema_utils import build_render_model


def _link_callback(uri, _rel):
    """Résout les URL /media/... et /static/... en chemins disque pour xhtml2pdf."""

    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
    if uri.startswith(settings.STATIC_URL):
        for static_dir in settings.STATICFILES_DIRS:
            candidate = os.path.join(static_dir, uri[len(settings.STATIC_URL):])
            if os.path.exists(candidate):
                return candidate
    return uri


def _html_to_pdf(html):
    buffer = io.BytesIO()
    pisa.CreatePDF(src=html, dest=buffer, link_callback=_link_callback)
    return buffer.getvalue()


def _visit_pdf_context(visit):
    schema = visit.mission.attached_form.schema
    photos_by_field = {}
    for photo in visit.photos.all():
        photos_by_field.setdefault(photo.field_key, []).append(photo)
    sections = build_render_model(schema, visit.reponses, photos_by_field)
    return {
        "visit": visit,
        "mission": visit.mission,
        "site": visit.mission.site,
        "client": visit.mission.site.client,
        "sections": sections,
    }


def render_visit_pdf(visit):
    """Retourne le contenu binaire du PDF d'une visite."""

    html = render_to_string("visits/pdf/visit_pdf.html", _visit_pdf_context(visit))
    return _html_to_pdf(html)


def visit_pdf_filename(visit):
    client_nom = slugify(visit.mission.site.client.nom) or "client"
    site_nom = slugify(visit.mission.site.nom) or "site"
    date_str = visit.date_soumission.strftime("%Y-%m-%d") if visit.date_soumission else "sans-date"
    return f"{client_nom}_{site_nom}_{date_str}_visite-{visit.pk}.pdf"


def build_visits_zip(visits):
    """Construit un ZIP en mémoire contenant le PDF de chaque visite (publiées uniquement)."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used_names = set()
        for visit in visits:
            name = visit_pdf_filename(visit)
            if name in used_names:
                name = f"{name[:-4]}_{visit.pk}.pdf"
            used_names.add(name)
            archive.writestr(name, render_visit_pdf(visit))
    return buffer.getvalue()


def zip_filename_for_site(site):
    return f"{slugify(site.client.nom) or 'client'}_{slugify(site.nom) or 'site'}_visites-publiees.zip"


def zip_filename_for_client(client):
    return f"{slugify(client.nom) or 'client'}_visites-publiees.zip"
