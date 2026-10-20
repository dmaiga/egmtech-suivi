# Script de démonstration

## Préparer l'environnement

```
python manage.py seed_demo --reset
python manage.py runserver
```

Connexion : `/comptes/connexion/` — redirige automatiquement vers `/app/` (managers,
superviseurs) ou `/portail/` (clients).

## Comptes de démonstration

Mot de passe commun : `demo1234`

| Compte           | Rôle                | Détails                                      |
|------------------|---------------------|-----------------------------------------------|
| `admin`          | Administrateur      | Superuser, accès Django admin (`/admin/`)     |
| `manager1`       | Manager             | Permissions : gérer les formulaires + valider les visites |
| `manager2`       | Manager             | Permission : valider les visites uniquement   |
| `sup1`           | Superviseur         | Issa Konaté                                    |
| `sup2`           | Superviseur         | Fatoumata Traoré                               |
| `sup3`           | Superviseur         | Moussa Diarra                                  |
| `sup4`           | Superviseur         | Aminata Coulibaly                              |
| `client_bnda`    | Client (lecture seule) | Rattaché au client BNDA (8 sites)          |
| `client_exemple` | Client (lecture seule) | Rattaché au client Banque Exemple (3 sites)|

Après un `seed_demo --reset`, le jeu de données contient toujours une mission encore
**en brouillon** : "Rapport d'installation" sur le site **Agence Kayes** du client **BNDA**,
assignée à **sup2**. C'est elle qui sert de fil rouge à la démo ci-dessous.

## Déroulé (8 à 10 minutes)

1. **(0:00–1:00) Connexion `sup2`** — écran *Mes missions* (`/app/missions/`).
   Repérer la mission "Rapport d'installation" sur "Agence Kayes" (encore sans visite
   en cours) et cliquer sur **Commencer** pour ouvrir l'écran de saisie de la visite.

2. **(1:00–3:00) Écran *Visite*** (`/app/missions/visites/<id>/`, compte `sup2`).
   Remplir les champs obligatoires (nom du technicien, date d'intervention, position
   GPS), prendre une photo pour chacun des 4 champs photo obligatoires (façade,
   installation, compteur, câblage), dessiner la signature du formulaire puis la
   signature du superviseur en bas de page, et cliquer **Soumettre**. Le statut passe
   à *Soumise* et la visite quitte la liste des missions de sup2.

3. **(3:00–4:00) Déconnexion, connexion `manager2`** — écran *Revue des visites*
   (`/app/revue/`). Repérer la visite soumise par sup2 sur Agence Kayes, cliquer
   **Rejeter**, saisir un motif réaliste (ex. « Photo du compteur illisible, merci de
   reprendre la photo. ») et valider. Le statut passe à *À corriger*.

4. **(4:00–5:00) Reconnexion `sup2`** — écran *Mes missions* puis *Visite* : le motif
   de rejet s'affiche en haut de la fiche. Corriger l'observation, reprendre la photo
   du compteur si on veut rejouer la correction à l'identique, puis cliquer à nouveau
   **Soumettre**. Le statut repasse à *Soumise*.

5. **(5:00–6:00) Reconnexion `manager2`** — écran *Revue des visites* : cliquer
   **Valider** (statut *Validée*), puis **Publier** (statut *Publiée*). La visite
   devient visible côté client.

6. **(6:00–7:30) Connexion `client_bnda`** — écran *Tableau de bord* (`/portail/`).
   Montrer la ligne "Agence Kayes" / "Rapport d'installation" qui passe à 1/1 réalisé.
   Ouvrir la fiche du site, puis le détail de la visite publiée, et télécharger son
   PDF (bouton **Télécharger le PDF**).

7. **(7:30–8:30) Reconnexion `manager2`** — écran *Revue des visites* : cliquer
   **Dépublier** sur cette même visite. Reconnexion `client_bnda` : la visite a
   disparu du portail (le compteur du site revient à 0/1), preuve que la
   dépublication masque immédiatement la donnée côté client sans la supprimer.

8. **(8:30–9:30) Connexion `manager1`** — écran *Fiche client* (`/app/clients/`,
   cliquer sur "BNDA"). Dans la liste des comptes clients, cliquer **Révoquer** sur
   `client_bnda`. Tenter ensuite de se reconnecter avec `client_bnda` sur
   `/comptes/connexion/` : le formulaire refuse la connexion (compte désactivé).

## Revenir à l'état initial

```
python manage.py seed_demo --reset
```

Cette commande efface entièrement les comptes, clients, sites et visites de
démonstration (y compris toutes les actions effectuées pendant la démo : visite
publiée/dépubliée, compte client révoqué) et recrée le même jeu de données initial.
