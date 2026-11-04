"""Backend PostgreSQL TEMPORAIRE pour un serveur en PostgreSQL 10 à 13.

Django 5.2 refuse PostgreSQL < 14 au démarrage. Ce backend ne fait que lever ce contrôle :
le reste du moteur est celui de Django. À n'utiliser que le temps des tests, en attendant que
l'hébergeur passe PostgreSQL en 14 ou plus. Activé par DB_POSTGRES_ANCIEN=true dans le .env ;
le retirer dès que le serveur est à jour.
"""

from django.db.backends.postgresql import base, features


class DatabaseFeatures(features.DatabaseFeatures):
    minimum_database_version = (10,)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
