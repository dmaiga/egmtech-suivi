from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilisateur de l'application.

    L'administrateur n'est pas un rôle : c'est is_superuser (accès Django admin).
    """

    class Role(models.TextChoices):
        MANAGER = "manager", "Manager"
        SUPERVISEUR = "superviseur", "Superviseur"
        CLIENT = "client", "Client"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        blank=True,
        help_text="Vide pour un compte administrateur sans rôle métier.",
    )

    def is_manager(self):
        return self.role == self.Role.MANAGER

    def is_superviseur(self):
        return self.role == self.Role.SUPERVISEUR

    def is_client(self):
        return self.role == self.Role.CLIENT
