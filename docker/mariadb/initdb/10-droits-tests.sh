#!/bin/bash
# Exécuté une seule fois, à la création du volume (premier démarrage).
# Donne à l'utilisateur de l'application tous les droits sur les bases dont le nom commence par
# « test_ » (Django crée et supprime test_<DB_NAME> à chaque lancement des tests).
# Aucun droit global : l'image lui a déjà donné les droits sur MARIADB_DATABASE, rien d'autre.
set -eu

mariadb --protocol=socket -uroot -p"${MARIADB_ROOT_PASSWORD}" <<SQL
GRANT ALL PRIVILEGES ON \`test\\_%\`.* TO '${MARIADB_USER}'@'%';
FLUSH PRIVILEGES;
SQL
