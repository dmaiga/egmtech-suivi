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
