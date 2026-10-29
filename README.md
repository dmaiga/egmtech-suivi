# egmtech-suivi-terrain

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Base de données

```bash
python manage.py migrate
python manage.py createsuperuser
```

Installer le modèle d'audit dans la bibliothèque avec `python manage.py installer_formulaire_bnda`. Cette commande ne crée ni client, ni site, ni mission et ne modifie pas un modèle existant. EGMTECH peut ensuite modifier le modèle, créer le client et lui attacher le formulaire depuis l'application. Ne pas lancer `seed_demo` pour une installation réelle : cette commande crée des comptes et données fictifs.

## Configuration locale

Copier `.env.example` vers `.env`, puis remplacer `DJANGO_SECRET_KEY` par une clé aléatoire. Par exemple, générer une clé avec `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. Le fichier `.env` est ignoré par Git et ne doit pas être partagé. `DJANGO_DEBUG=true` et les hôtes `localhost,127.0.0.1` conviennent aux tests locaux.

## Lancer le serveur

```bash
python manage.py runserver
```

Application accessible sur http://127.0.0.1:8000/, admin sur http://127.0.0.1:8000/admin/.
