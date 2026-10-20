from django.core.files.storage import storages


def get_upload_storage():
    """Point d'entrée unique pour le stockage des fichiers uploadés par l'app.

    Configurable via STORAGES["default"] dans settings.py. Ne jamais construire
    de chemin de stockage en dur dans le code métier : passer par cette fonction.
    """

    return storages["default"]
