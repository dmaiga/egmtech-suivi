# Audit de dette technique

Audit réalisé le 31/10/2026 sur l'état du dépôt (branche `main`, modifications non committées sur les échanges et les pièces jointes comprises). 221 tests passent.

Priorité : **P1** à traiter avant la mise en production réelle, **P2** à planifier, **P3** confort.

## À reprendre plus tard

| Sujet | Détail |
|---|---|
| **Images HEIC (iPhone)** | Pillow ne lit pas le HEIC. Safari convertit en général en JPEG à l'envoi, mais ce n'est pas garanti (envoi depuis l'app Fichiers, AirDrop, etc.). Le fichier est alors refusé (« n'est pas une image valide »). À faire : tester sur un vrai iPhone ; si le refus se produit, ajouter `pillow-heif` (une dépendance, à justifier) et accepter `.heic` / `.heif` dans `core/images.py` et `visits/echanges.py`. |
| **Photos déjà enregistrées** | Elles n'ont ni compression ni miniature (champ `miniature` vide) et sont affichées en taille d'origine. Prévoir une commande de rattrapage qui les recompresse et crée les miniatures. |

## P1 — Avant la production

1. **Réglages de sécurité de production.** `manage.py check --deploy` signale 5 avertissements : `DEBUG` vaut `true` par défaut, pas de `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT` ni `SECURE_HSTS_SECONDS`. Le défaut de `DJANGO_DEBUG` devrait être `false`. Pas de `LOGGING` configuré non plus : en production, aucune trace des erreurs.
2. **Front chargé depuis des CDN sans contrôle.** `templates/base.html` charge `cdn.tailwindcss.com` (le CDN « play » de Tailwind n'est pas prévu pour la production : compilation dans le navigateur à chaque page, avertissement console) et `unpkg.com/htmx.org@2.0.3`, sans intégrité (SRI). Si un CDN tombe ou est compromis, l'application est dégradée ou exposée. Le choix « aucun build » est dans `CLAUDE.md` : à arbitrer (héberger les fichiers dans `static/` reste sans build).
3. **Exports PDF et ZIP synchrones.** `client_export` et `site_export` (`portal/views.py`) génèrent tous les PDF dans la requête HTTP, en mémoire. Un client avec des centaines de visites fera dépasser le délai du serveur. De plus, `visits/pdf.py` embarque les photos en taille d'origine, ce qui alourdit chaque PDF : utiliser l'image optimisée ou la miniature.
4. **Fichiers privés servis par Django et jamais mis en cache.** `private_media` répond avec `Cache-Control: private, no-store` et ouvre le fichier à chaque requête. Chaque affichage de rapport recharge toutes les miniatures. Passer à `private, max-age=…` pour les miniatures et photos (les noms ne changent pas), et à terme faire servir les fichiers par le serveur web (`X-Accel-Redirect` / `X-Sendfile`) tout en gardant le contrôle d'accès Django.
5. **Aucune notification.** Un message client ou une réponse manager n'est visible que dans l'application (badge). Aucun e-mail : le client et le manager doivent se reconnecter pour savoir qu'il y a du nouveau. Le journal `ActivityLog` n'est pas relu par l'interface.
6. **Sauvegardes.** SQLite et `media/` sont sur le même disque. Le guide d'exploitation décrit les sauvegardes, mais rien n'est automatisé ni testé en restauration.

## P2 — À planifier

7. **`visits/` fait trop de choses.** `visits/views.py` (877 lignes, 35 fonctions) mélange missions, saisie des visites, revue manager et échanges. Les échanges (`Echange`, `EchangeMessage`, `EchangeFichier`, `visits/echanges.py`, vues, templates) n'ont aucun lien avec les visites hors du lien optionnel : ils méritent leur propre application `echanges`, ce qui évite aussi que `core/views.py` et `core/context_processors.py` dépendent de `visits`. Attention : déplacer des modèles demande une migration soignée.
8. **Logique dupliquée dans le portail.** Le calcul du statut d'avancement (« complet », « en cours », « non visité »…) est écrit en double dans `dashboard` et `site_detail` (`portal/views.py`). À factoriser dans une fonction.
9. **`except Exception: pass` / `except Exception:`.** `portal/views.py` (filtres de date, lignes 255 et 260), `visits/schema_utils.py` (lignes 316 et 324, génération des URL du PDF) et `visits/views.py` (ligne 507) avalent les erreurs sans trace. Cibler l'exception attendue (`ValidationError`, `NoReverseMatch`) et journaliser le reste.
10. **Gabarits volumineux et dupliqués.** `_visit_detail.html` fait 651 lignes (rendu des champs, lightbox, historique, JS). `base.html` répète deux fois (menu mobile et menu bureau) la série de `<svg>` d'icônes de navigation ; chaque nouvelle icône doit être ajoutée aux deux endroits. Isoler l'icône dans un petit gabarit inclus.
11. **Requêtes à chaque page.** Le processeur de contexte `navigation` (`core/context_processors.py`) compte les messages non lus à chaque requête, y compris pour le HTMX et les fichiers de pages simples. Acceptable maintenant, à surveiller (index sur `EchangeMessage.lu_le`, ou mise en cache courte).
12. **Journal d'activité sans index.** `ActivityLog` est interrogé par `(object_type, object_id)` sur chaque page de détail de visite, sans index. Ajouter un index quand le volume augmente. Le journal n'enregistre pas la lecture des messages ni la clôture d'un échange.
13. **Fonctions d'échange à compléter.** Pas de modification ni suppression de message, pas de recherche dans la boîte de réception, pas de pagination (la boîte de réception et la liste du portail chargent tout), pas de limite de débit contre l'envoi massif. La rétention des pièces jointes n'est pas définie (les fichiers d'un échange supprimé restent sur disque).
14. **Compression incomplète.** Les signatures (`signature_*`) ne passent pas par Pillow. Les images envoyées au serveur sont décodées dans la requête : un fichier de 120 Mpx est accepté et occupe plusieurs centaines de Mo de mémoire le temps du traitement. Envisager de réduire `MAX_PIXELS` (`core/images.py`) et de faire la compression côté navigateur avant envoi (déjà prévu par le script `js-photo-compress` pour les photos de visite).
15. **Migrations de l'application `visits`.** `0004` a été régénérée sous le même nom après avoir été appliquée sur la base de développement (voir l'incident du 31/10). Les autres postes qui ont appliqué l'ancienne version devront faire `migrate visits 0003` avant `migrate`. À ne plus refaire : une migration appliquée ne se réécrit pas.
16. **Données de démonstration dans le code de production.** `core/management/commands/seed_demo.py` (539 lignes) et `forms_cms/management/commands/seed_demo_forms.py` vivent à côté du code métier. Pas dangereux, mais à protéger (refuser de tourner si `DEBUG` est faux).

## P3 — Confort

17. **Pas d'outillage de qualité.** Aucun linter ni formateur (`ruff`), pas d'intégration continue qui lance `manage.py test`, pas de verrouillage des versions exactes (`requirements.txt` donne des plages). Les tests mettent 80 s : certains créent des données lourdes (`seed_demo`) et pourraient être allégés.
18. **Tests de gabarits fragiles.** Plusieurs tests vérifient la présence de texte dans le HTML (« Aucun échange », « 1 nouveau »). Un changement de libellé les casse. Préférer tester le contexte ou des identifiants stables.
19. **Dépendance implicite entre `Role` et permissions.** Les droits fins sont des permissions Django (conforme à `CLAUDE.md`) mais le menu et les vues testent aussi `is_manager()` à plusieurs endroits (`core/views.py`, `core/context_processors.py`). Un manager sans la permission `validate_visits` voit certains écrans mais pas d'autres : vérifier que c'est voulu et le documenter.
20. **Documentation.** `README.md` et `docs/` ne décrivent pas encore les échanges, les pièces jointes ni la compression d'images. Le vocabulaire (« auditeur » à l'écran, `superviseur` dans le code) est respecté mais le gabarit `_visit_detail.html` affiche encore « Auteur (Superviseur) » : à corriger.

## Points solides à conserver

- Cloisonnement par client testé de façon systématique (portail, échanges, fichiers privés).
- Stockage unique et configurable (`get_upload_storage`), aucun chemin en dur.
- Droits fins par permissions Django, pas de champs de rôle ad hoc.
- Aucune dépendance front à compiler ; peu de dépendances Python (Django, Pillow, xhtml2pdf, python-dotenv).
- Couverture de tests large (221 tests) sur les parcours critiques.
