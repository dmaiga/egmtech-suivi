from django.contrib.auth.mixins import UserPassesTestMixin


class RoleRequiredMixin(UserPassesTestMixin):
    """Équivalent class-based view de accounts.decorators.role_required.

    Utilisateur anonyme -> redirection vers la page de connexion.
    Utilisateur connecté mais rôle non autorisé -> 403.
    """

    allowed_roles = ()

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role in self.allowed_roles)
