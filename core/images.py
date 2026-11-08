"""Compression et miniatures d'images avec Pillow (photos de visites, pièces jointes)."""

import os
from io import BytesIO
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_PIXELS = 120_000_000


def _ouvrir(fichier, cote_max):
    """Ouvre l'image, applique l'orientation EXIF et la réduit à `cote_max` px de côté."""
    fichier.seek(0)
    try:
        img = Image.open(fichier)
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("Image trop grande.")
        img.draft("RGB", (cote_max, cote_max))  # décodage JPEG réduit : rapide sur les gros fichiers
        img = ImageOps.exif_transpose(img)
        img.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Fichier image invalide.") from exc
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fond = Image.new("RGB", img.size, "white")
        fond.paste(img, mask=img.getchannel("A"))
        img = fond
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((cote_max, cote_max), Image.LANCZOS)
    return img


def _jpeg(img, qualite):
    buf = BytesIO()
    img.save(buf, "JPEG", quality=qualite, optimize=True, progressive=True)  # sans métadonnées EXIF/GPS
    return buf.getvalue()


def optimiser_image(fichier, nom=None):
    """Retourne (image optimisée, miniature) en ContentFile JPEG. ValueError si ce n'est pas une image."""
    base = nom or uuid4().hex
    img = _ouvrir(fichier, settings.IMAGE_MAX_SIDE)
    principale = ContentFile(_jpeg(img, settings.IMAGE_JPEG_QUALITY), name=f"{base}.jpg")
    img.thumbnail((settings.IMAGE_THUMB_SIDE, settings.IMAGE_THUMB_SIDE), Image.LANCZOS)
    miniature = ContentFile(_jpeg(img, 70), name=f"{base}_thumb.jpg")
    return principale, miniature


def optimiser_image_png(fichier, cote_max, nom=None):
    """Valide une image et la réenregistre en PNG réduit à `cote_max` px, transparence conservée.

    Pour les logos et cachets, posés plus tard sur des documents : un fond blanc imposé (JPEG)
    masquerait le texte sous un cachet. Le réencodage retire les métadonnées (EXIF, GPS).
    Retourne un ContentFile ; ValueError si ce n'est pas une image.
    """
    fichier.seek(0)
    try:
        img = Image.open(fichier)
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("Image trop grande.")
        img = ImageOps.exif_transpose(img)
        img.load()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        # OSError couvre UnidentifiedImageError et les fichiers tronqués ; certains décodeurs
        # lèvent SyntaxError sur un fichier corrompu.
        raise ValueError("Fichier image invalide.") from exc
    transparente = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    img = img.convert("RGBA" if transparente else "RGB")
    img.thumbnail((cote_max, cote_max), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return ContentFile(buf.getvalue(), name=f"{nom or uuid4().hex}.png")


def nom_aleatoire(extension=""):
    return uuid4().hex + extension


def nom_sur(nom):
    return os.path.basename(nom or "")[:200]
