# EGM Suivi Terrain

Plateforme web qui archive les visites terrain des auditeurs, les fait valider par un manager, puis les montre au client en lecture seule. Cloisonnement strict par client.

Stack : Django 5.2 (LTS), SQLite, templates serveur + HTMX + Tailwind (CDN). Aucun build front. Langue `fr`, fuseau `Africa/Bamako`.

## Deux usages, deux guides

| Usage | Guide | Données |
|---|---|---|
| **Démonstration / test** | [DEMO.md](docs/DEMO.md) | Fictives (`seed_demo`) |
| **Production réelle** | [EXPLOITATION.md](docs/EXPLOITATION.md) | Vraies (`installer_formulaire_bnda`) |

Ne jamais mélanger : `seed_demo` crée des comptes au mot de passe connu (`demo1234`). Il ne doit jamais être lancé sur une base réelle.

## Installation (commune)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # puis remplacer DJANGO_SECRET_KEY
python manage.py migrate
```

Générer une clé secrète :

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Variables d'environnement (`.env`, ignoré par Git) :

| Variable | Rôle | Défaut |
|---|---|---|
| `DJANGO_SECRET_KEY` | Obligatoire, l'application refuse de démarrer sans | — |
| `DJANGO_DEBUG` | `true` en local, **`false` en production** | `true` |
| `DJANGO_ALLOWED_HOSTS` | Hôtes autorisés, séparés par des virgules | `localhost,127.0.0.1` |
| `DJANGO_STATIC_ROOT` | Dossier cible de `collectstatic` | `public/static` ou `staticfiles` |

## Lancer

```bash
python manage.py runserver
```

Connexion : http://127.0.0.1:8000/comptes/connexion/ — admin Django : `/admin/`.
Chaque rôle est redirigé vers son espace : manager `/app/`, auditeur `/app/missions/`, client `/portail/`.

## Démo en une commande

```bash
python manage.py seed_demo --reset
```

Détails, comptes et déroulé dans [DEMO.md](docs/DEMO.md).

## Production réelle en une commande

```bash
python manage.py createsuperuser
python manage.py installer_formulaire_bnda
```

Détails (création des comptes, client, sites, sauvegardes, passation) dans [EXPLOITATION.md](docs/EXPLOITATION.md).

## Tests

```bash
python manage.py test
```

Les tests de cloisonnement client sont obligatoires pour tout lot touchant des données liées à un client.

## Repères pour reprendre le code

| Dossier | Contenu |
|---|---|
| `accounts` | Utilisateurs, rôles, connexion, création des auditeurs |
| `clients` | Clients, sites, comptes d'accès client |
| `forms_cms` | Formulaires (modèles), éditeur, formulaires attachés (copie figée JSON) |
| `visits` | Missions, visites, saisie terrain, revue manager |
| `portal` | Portail client en lecture seule |
| `core` | Journal d'activité, stockage des fichiers, commande `seed_demo` |
| `static/css/ds.css` | Design system (couleurs, boutons, badges) |

Conventions : voir [CLAUDE.md](CLAUDE.md) (vocabulaire, permissions Django, stockage unique, cloisonnement).
