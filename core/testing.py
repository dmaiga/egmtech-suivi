"""Outils partagés par les tests (ce module n'est pas lui-même un module de tests)."""

import shutil
import tempfile

from django.conf import settings
from django.test import override_settings


class TempMediaRootMixin:
    """Donne à la classe de tests un MEDIA_ROOT temporaire, supprimé à la fin de la classe.

    À placer avant TestCase dans les bases : ``class MesTests(TempMediaRootMixin, TestCase)``.
    Tout test qui enregistre un fichier (photo, signature, pièce jointe, seed) doit l'utiliser :
    un test ne doit jamais écrire dans le vrai dossier media/.

    Le dossier est créé dans BASE_DIR et non dans le /tmp du système : xhtml2pdf refuse de lire
    une image située hors du répertoire courant, et les photos manqueraient dans les PDF testés.
    Le préfixe `.test-media-` est ignoré par git (reste éventuel après une interruption brutale).
    """

    @classmethod
    def setUpClass(cls):
        media_root = tempfile.mkdtemp(prefix=".test-media-", dir=settings.BASE_DIR)
        cls.addClassCleanup(shutil.rmtree, media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media_root)
        override.enable()
        cls.addClassCleanup(override.disable)
        cls.media_root = media_root
        super().setUpClass()
