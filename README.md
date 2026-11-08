# EGM Suivi Terrain

Plateforme web qui archive les visites terrain des auditeurs, les fait valider par un manager, puis les montre au client en lecture seule. Cloisonnement strict par client.

Stack : Django 5.2 (LTS), MariaDB (SQLite et PostgreSQL restent possibles), templates serveur + HTMX + Tailwind (CDN). Aucun build front. Langue `fr`, fuseau `Africa/Bamako`.

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
cp .env.example .env             # puis remplacer DJANGO_SECRET_KEY et les mots de passe
```

Puis démarrer la base et migrer : voir [Environnement de développement](#environnement-de-développement).

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

## Environnement de développement

En local, on travaille sur **MariaDB 11.4** dans Docker (Colima), comme la prod.
La version et la collation (`utf8mb4` / `utf8mb4_unicode_ci`) sont alignées sur la **prod supposée** :
à confirmer dès que l'accès au serveur sera disponible (`SELECT VERSION(), @@collation_server;`).

Identifiants : `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` et `MARIADB_ROOT_PASSWORD` dans `.env`
(voir `.env.example`). Le conteneur ne publie son port que sur `127.0.0.1` ; si le port 3306 est
déjà pris sur le Mac, mettre `DB_PORT=3307` dans `.env` (le compose et Django lisent la même valeur).

```bash
colima start                                  # démarre la VM Docker
docker compose up -d mariadb                  # démarre MariaDB (attendre « healthy »)
docker compose ps                             # état du conteneur
python manage.py migrate
python manage.py seed_demo                    # données fictives, jamais sur une base réelle
python manage.py test                         # suite complète, crée et supprime test_<DB_NAME>
```

Au premier démarrage, `docker/mariadb/initdb/10-droits-tests.sh` donne à `DB_USER` le droit de
créer et supprimer les bases `test_*` (nécessaire à `manage.py test`), sans aucun droit global.

Arrêter : `docker compose stop` (les données restent dans le volume).

Repartir de zéro (supprime **toutes** les données MariaDB locales, pas `media/`) :

```bash
docker compose down -v                        # supprime le conteneur et le volume
docker compose up -d mariadb                  # recrée la base vide (et relance le script de droits)
python manage.py migrate && python manage.py seed_demo
```

Les mots de passe de `.env` sont figés à la création du volume : pour les changer, repartir de zéro.

Lancer les tests sur SQLite sans toucher au `.env` : `DB_NAME= python manage.py test`.

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

Avant toute livraison : suite complète sur MariaDB, le nombre de tests ne doit pas baisser
(référence au 08/11/2026 : 271 tests). Un test qui enregistre des fichiers utilise
`core.testing.TempMediaRootMixin` : aucun test n'écrit dans le vrai dossier `media/`.

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
