from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
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
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        help_text="Obligatoire pour un compte client.",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=~models.Q(role="client") | models.Q(client__isnull=False),
                name="accounts_client_role_requires_client",
            )
        ]

    def clean(self):
        super().clean()
        if self.role == self.Role.CLIENT and self.client_id is None:
            raise ValidationError({"client": "Un compte client doit être lié à un client."})

    def is_manager(self):
        return self.role == self.Role.MANAGER

    def is_superviseur(self):
        return self.role == self.Role.SUPERVISEUR

    def is_client(self):
        return self.role == self.Role.CLIENT
