from django.contrib.auth.backends import ModelBackend
from .models import User


class ClientEmailBackend(ModelBackend):
    """Connexion par e-mail (tous les rôles) ou par identifiant (administrateur)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and "@" in username:
            matches = list(User.objects.filter(email__iexact=username.strip())[:2])
            if len(matches) == 1:
                return super().authenticate(request, username=matches[0].username, password=password, **kwargs)
            if matches:
                return None
        return super().authenticate(request, username=username, password=password, **kwargs)
