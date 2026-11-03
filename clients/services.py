import unicodedata
from collections import defaultdict

from accounts.models import User

from .models import Client, Site


def visible_clients(user):
    """Clients visibles par cet utilisateur : un seul pour un compte client, tous pour le reste."""

    if user.is_superuser or user.role != User.Role.CLIENT:
        return Client.objects.all()
    return Client.objects.filter(pk=user.client_id)


def visible_sites(user):
    """Sites visibles par cet utilisateur, filtrés par client pour un compte client."""

    if user.is_superuser or user.role != User.Role.CLIENT:
        return Site.objects.all()
    return Site.objects.filter(client_id=user.client_id)


def cle_nom(nom):
    """Clé de comparaison et de tri : sans accents, sans casse, apostrophes typographiques unifiées."""
    nom = unicodedata.normalize("NFKD", nom.replace("’", "'"))
    return " ".join("".join(c for c in nom if not unicodedata.combining(c)).lower().split())


def sites_par_localite(sites):
    """Regroupe les sites par ville : Bamako d'abord, puis les autres villes par ordre alphabétique,
    les sites sans ville en dernier. Les sites sont triés par nom dans chaque groupe."""

    groupes = defaultdict(list)
    for site in sites:
        groupes[site.ville.strip()].append(site)

    def ordre(ville):
        return (0 if cle_nom(ville) == "bamako" else 2 if not ville else 1, cle_nom(ville))

    return [
        (ville or "Sans localité", sorted(groupes[ville], key=lambda site: cle_nom(site.nom)))
        for ville in sorted(groupes, key=ordre)
    ]
