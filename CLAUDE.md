# egmtech-suivi-terrain

## Produit
Plateforme web qui archive les visites terrain de superviseurs, les fait valider par un manager,
puis les montre au client en lecture seule. Multi-clients dès le départ : **cloisonnement strict
par client** sur toutes les données.

## Stack
- Django (dernière LTS), SQLite.
- Templates Django côté serveur + HTMX pour l'interactivité + Tailwind via CDN.
- **Aucun build front** (pas de npm/webpack/vite). Tout en CDN.
- Langue : fr. Fuseau : Africa/Bamako.

## Vocabulaire (ne pas dévier)
- **Administrateur** : accès Django admin, tous les droits.
- **Manager** : rôle métier.
- **Superviseur** : exécute les visites.
- **Client** : accès lecture seule à ses propres données via le portail.
- Les droits fins (valider une visite, gérer les formulaires, etc.) sont des **permissions
  Django**, attribuables à un utilisateur ou à un groupe — pas de champs de rôle ad hoc.

## Modèle métier
- Pas de notion d'« audit » ni d'« installation » dans le code.
- Un **formulaire** est nommé et attaché à un client.
- Une **mission** = superviseur + site + formulaire attaché.
- Une **visite** = exécution d'une mission.
- Un formulaire attaché à une mission est une **copie figée (JSON)** du formulaire source au
  moment de l'attachement. Pas de migration entre versions de formulaire.

## Fichiers / stockage
- Tout upload passe par **une seule fonction/stockage configurable** dans `settings.py`
  (`STORAGES`, `MEDIA_ROOT`/`MEDIA_URL`). Jamais de chemin en dur dans le code métier.

## Cloisonnement multi-clients
- Toute requête côté client (portail) doit être filtrée par le client de l'utilisateur connecté.
- Des **tests sont obligatoires** pour vérifier ce cloisonnement à chaque lot qui touche des
  données liées à un client.

## Process
- Code simple, pas de dépendance non nécessaire.
- Petits commits, un lot à la fois.
