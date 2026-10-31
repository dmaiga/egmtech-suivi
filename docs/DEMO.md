# Script de démonstration — EGM Suivi Terrain

Ce document présente l'ensemble des fonctionnalités de la plateforme EGM Suivi Terrain à travers un déroulé pas à pas complet, fluide et réaliste.

---

## 1. Préparer l'environnement

```bash
python manage.py seed_demo --reset
python manage.py runserver
```

Point d'entrée : **`/comptes/connexion/`**  
La plateforme redirige automatiquement l'utilisateur connecté vers son espace dédié selon son rôle :
- Managers & Administrateurs : `/app/` (Tableau de bord)
- Superviseurs : `/app/missions/` (Mes missions mobile-first)
- Clients : `/portail/` (Avancement des sites)

---

## 2. Comptes de démonstration

Mot de passe commun : **`demo1234`**

| Compte | Rôle | Droits & Accès | Espace par défaut |
|---|---|---|---|
| `admin` | Administrateur | Superuser, Django admin (`/admin/`), tous les droits | `/app/` |
| `manager1` | Manager complet | Gestion des formulaires (`manage_forms`) + Validation (`validate_visits`) | `/app/` |
| `manager2` | Manager revue | Validation des visites (`validate_visits`) uniquement (pas de gestion formulaires) | `/app/` |
| `sup1` | Superviseur | Issa Konaté — Missions de terrain | `/app/missions/` |
| `sup2` | Superviseur | Fatoumata Traoré — Fil rouge de la démo | `/app/missions/` |
| `sup3` | Superviseur | Moussa Diarra — Missions de terrain | `/app/missions/` |
| `sup4` | Superviseur | Aminata Coulibaly — Missions de terrain | `/app/missions/` |
| `client_bnda` | Client | BNDA (8 sites sous contrat, Bamako, Kayes, Sikasso...) | `/portail/` |
| `client_exemple` | Client | Banque Exemple (3 sites sous contrat) | `/portail/` |

---

## 3. Déroulé conseillé de la démonstration (10 à 12 minutes)

### Étape 1 : Espace Manager — Synthèse & Gestion des Formulaires (`manager1`)
*Objectif : Présenter la gouvernance centrale, les métriques clés et le catalogue de formulaires.*

1. **Connexion avec `manager1`** :
   - Arrivée directe sur le **Tableau de bord manager** (`/app/`).
   - Découverte des 4 indicateurs de synthèse : Visites à revoir, Visites à corriger, Missions en cours, Visites publiées ce mois-ci.
   - Section des 5 dernières visites soumises avec lien direct d'accès à la revue.
2. **Menu Formulaires** (`/app/formulaires/`) :
   - Souligner que cet onglet n'est visible que par les utilisateurs disposant de la permission `manage_forms`.
   - Explorer le catalogue de formulaires : tri par nom ou statut, pagination.
   - Cliquer sur **Aperçu** sur le formulaire *Audit technique* pour visualiser le schéma dynamique.
   - Montrer la confirmation sécurisée sur le bouton **Désactiver / Réactiver**.

---

### Étape 2 : Espace Manager — Clients & Missions dépendantes (`manager1`)
*Objectif : Montrer la configuration multi-clients, l'avancement global et l'assignation interactive HTMX.*

1. **Menu Clients** (`/app/clients/`) :
   - Tableau avec tri par colonnes (Client, Statut, Sites, Avancement global).
   - Cliquer sur le client **BNDA** pour ouvrir la fiche détaillée à 3 onglets :
     - **Sites** : Liste des 8 sites avec code, ville, quartier et coordonnées GPS.
     - **Formulaires rattachés** : Matrice des prévisions par site (modifiables directement en HTMX).
     - **Accès client** : Liste des comptes actifs avec possibilité d'en créer ou de révoquer un accès avec confirmation.
2. **Menu Missions** (`/app/missions/`) :
   - Tableau complet filtrable (Superviseur, Client, Site, Statut) avec tri sur colonnes.
   - En bas, tester le bloc **Assigner une nouvelle mission** :
     - Choisir le client BNDA : HTMX recharge instantanément les sites de la BNDA et ses formulaires autorisés.
     - Sélectionner un site, le formulaire et le superviseur `sup2`.

---

### Étape 3 : Expérience Superviseur Mobile-First (`sup2`)
*Objectif : Démontrer l'ergonomie mobile, la saisie guidée, les photos et la signature électronique.*

1. **Connexion avec `sup2`** (simuler un écran téléphone via l'inspecteur du navigateur) :
   - Redirection automatique sur **Mes missions** (`/app/missions/`).
   - Si une mission est à corriger, elle apparaît en tête de liste avec son motif de rejet dans un bandeau d'alerte rouge bien visible.
   - Repérer la mission non commencée sur **Agence Kayes** et cliquer sur **Commencer**.
2. **Écran de saisie mobile** (`/app/missions/visites/<id>/`) :
   - **Barre de progression** dynamique en tête indiquant les sections complétées.
   - **Sections repliables en accordéon** pour ne pas surcharger l'écran.
   - **Champs adaptés** : claviers numériques automatiques pour les nombres, cases à cocher lisibles.
   - **Photos de terrain** : bouton tactile "Prendre une photo", compression automatique, miniature immédiate et compteur "2 sur 4".
   - **Tableau répétable** : cartes de caméras avec ajout et suppression dynamique de lignes.
   - **Signature électronique** : zone tactile plein format avec bouton d'effacement pour signature du technicien et du responsable.
   - Cliquer sur **Soumettre** : si des champs obligatoires manquent, un résumé clair s'affiche et scroll directement au premier champ en erreur.
   - Une fois complet, soumettre : redirection vers l'**écran de confirmation de soumission** dédié (`/confirmation/`).

---

### Étape 4 : Revue Manager en vue scindée (`manager2`)
*Objectif : Valider le flux de contrôle qualité sans rechargement de page.*

1. **Connexion avec `manager2`** :
   - Constater dans la barre latérale que le menu *Formulaires* est masqué (droits restreints).
   - Ouvrir **Revue des visites** (`/app/revue/`).
2. **Expérience de revue sur ordinateur** :
   - Colonne de gauche : liste des visites avec tri rapide (Plus récents, Client, Statut).
   - Colonne de droite : chargement asynchrone HTMX de la visite sélectionnée au clic.
   - Vérifier le composant universel :
     - Alerte discrète si l'écart GPS avec le site dépasse 500 m.
     - Visionneuse photos intégrée (lightbox avec zoom et navigation au clavier).
     - Rendu des signatures et bloc d'audit interne ActivityLog.
3. **Cycle Rejet & Validation** :
   - Cliquer sur **Rejeter** : saisie obligatoire du motif (ex. : « *Photo du compteur floue, merci de reprendre le cliché.* »). Statut -> *À corriger*.
   - *(Optionnel)* Reconnexion rapide de `sup2` pour montrer le motif en bandeau, puis re-soumission.
   - Cliquer sur **Valider** : statut passe à *Validée*.
   - Cliquer sur **Publier** : statut passe à *Publiée*. La visite est désormais certifiée et visible pour le client.

---

### Étape 5 : Portail Client sobre & rassurant (`client_bnda`)
*Objectif : Vérifier le cloisonnement strict, l'absence totale de vocabulaire interne et les exports.*

1. **Connexion avec `client_bnda`** :
   - Redirection automatique sur `/portail/`.
   - **Synthèse en haut** : 3 chiffres clés (Sites sous contrat, Visites réalisées, Visites planifiées) et barre de progression globale.
   - **Filtres** : filtrer par ville (ex. Kayes) ou par type de formulaire, recherche textuelle.
   - Chaque site affiche ses formulaires avec barres de progression et pastilles de couleur (*Complet*, *En cours*, *Pas encore visité*).
2. **Fiche d'un site** (`/portail/sites/<id>/`) :
   - Chronologie verticale épurée des visites publiées et checklist des interventions restant à planifier.
3. **Détail d'une visite client** (`/portail/visites/<id>/`) :
   - Gabarit universel en lecture seule : **aucun statut interne**, aucun commentaire de rejet ni historique d'audit interne.
   - Bouton **Télécharger le PDF** pour obtenir le rapport officiel mis en page.
4. **Exports groupés** :
   - Bouton **Exporter le site (ZIP)** sur la fiche du site.
   - Bouton **Exporter tout (ZIP)** en tête du portail client.

---

### Étape 6 : Sécurité & Révocation instantanée
*Objectif : Montrer la dépublication en direct et la gestion des comptes clients.*

1. **Dépublication** :
   - Depuis `manager2` sur `/app/revue/`, cliquer sur **Dépublier** sur la visite.
   - Côté `client_bnda`, rafraîchir : la visite disparaît immédiatement des compteurs et de la chronologie.
2. **Révocation d'un accès client** :
   - Avec `manager1` sur `/app/clients/` (BNDA, onglet Accès client), cliquer sur **Révoquer** pour `client_bnda`.
   - Tenter de se reconnecter avec `client_bnda` : accès refusé immédiatement.

---

## 4. Revenir à l'état initial

Pour réinitialiser la base à son état de départ propre à tout moment :

```bash
python manage.py seed_demo --reset
```
