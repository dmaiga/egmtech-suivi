"""Copie toutes les données d'une base SQLite vers la base MySQL (ou PostgreSQL) configurée.

Usage :
    python manage.py transferer_donnees                 # lit db.sqlite3
    python manage.py transferer_donnees --source /chemin/vers/db.sqlite3

Prérequis : DB_NAME (et DB_USER, DB_PASSWORD...) renseignés dans le .env, pour que la base
« default » soit MySQL/MariaDB ou PostgreSQL. La base cible doit être vide : la commande refuse sinon.
Les fichiers (photos, signatures) ne bougent pas : ils restent dans MEDIA_ROOT.
"""

import os
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

SOURCE = "source_sqlite"
# Recréés par migrate sur la cible, ou sans intérêt à copier.
EXCLUS = ["contenttypes", "auth.permission", "sessions"]


class Command(BaseCommand):
    help = "Transfère les données de SQLite (db.sqlite3) vers MySQL ou PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(settings.BASE_DIR / "db.sqlite3"),
                            help="Chemin du fichier SQLite à copier.")

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.is_file():
            raise CommandError(f"Fichier SQLite introuvable : {source}")
        cible = connections["default"]
        if cible.vendor == "sqlite":
            raise CommandError("La base « default » est encore SQLite : renseigner DB_NAME dans le .env.")

        if cible.vendor == "mysql":
            with cible.cursor() as cursor:
                cursor.execute("SELECT @@character_set_database")
                charset = cursor.fetchone()[0]
            if charset != "utf8mb4":
                raise CommandError(
                    f"La base MySQL est en {charset} : les accents seraient abîmés. Dans phpMyAdmin, "
                    f"exécuter : ALTER DATABASE `{cible.settings_dict['NAME']}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; puis relancer."
                )

        # Déclare la base SQLite source à côté de la base cible.
        config = dict(cible.settings_dict)
        config.update(ENGINE="django.db.backends.sqlite3", NAME=str(source),
                      USER="", PASSWORD="", HOST="", PORT="", OPTIONS={}, CONN_MAX_AGE=0)
        connections.databases[SOURCE] = config

        self.stdout.write(f"1/3 Création des tables {cible.display_name} (migrate)...")
        call_command("migrate", interactive=False, verbosity=0)

        user_model = apps.get_model(settings.AUTH_USER_MODEL)
        if user_model.objects.using("default").exists():
            raise CommandError("La base cible contient déjà des utilisateurs : transfert annulé "
                               "pour ne rien écraser. Vider la base puis relancer.")

        fd, dump = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            self.stdout.write("2/3 Export des données SQLite...")
            call_command("dumpdata", database=SOURCE, exclude=EXCLUS, natural_foreign=True,
                         indent=None, output=dump, verbosity=0)
            self.stdout.write(f"3/3 Import dans {cible.display_name}...")
            call_command("loaddata", dump, database="default", verbosity=0)
        finally:
            os.remove(dump)
            connections[SOURCE].close()

        # Contrôle : mêmes volumes de chaque côté.
        ecarts = []
        for model in apps.get_models():
            label = model._meta.label
            if model._meta.app_label in ("contenttypes", "sessions") or label == "auth.Permission":
                continue
            avant = model.objects.using(SOURCE).count()
            apres = model.objects.using("default").count()
            if avant or apres:
                self.stdout.write(f"  {label:<35} {avant:>6} -> {apres:>6}")
            if avant != apres:
                ecarts.append(label)
        connections[SOURCE].close()
        if ecarts:
            raise CommandError(f"Volumes différents pour : {', '.join(ecarts)}")
        self.stdout.write(self.style.SUCCESS("Transfert terminé : toutes les données sont copiées."))
