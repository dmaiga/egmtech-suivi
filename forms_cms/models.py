from django.core.exceptions import ValidationError
from django.db import models

from .schema import validate_schema


class FormTemplate(models.Model):
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    schema = models.JSONField()
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        permissions = [
            ("manage_forms", "Peut gérer les formulaires"),
        ]

    def __str__(self):
        return self.nom

    def clean(self):
        super().clean()
        errors = validate_schema(self.schema)
        if errors:
            raise ValidationError({"schema": errors})


class AttachedForm(models.Model):
    """Copie figée d'un FormTemplate attachée à un client.

    Modifier le FormTemplate source n'a aucun effet sur cette copie.
    """

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="attached_forms")
    template = models.ForeignKey(FormTemplate, on_delete=models.PROTECT, related_name="attached_forms")
    nom = models.CharField(max_length=150)
    schema = models.JSONField()
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return f"{self.nom} ({self.client.nom})"


class ExpectedVisits(models.Model):
    site = models.ForeignKey("clients.Site", on_delete=models.CASCADE, related_name="expected_visits")
    attached_form = models.ForeignKey(AttachedForm, on_delete=models.CASCADE, related_name="expected_visits")
    nombre_prevu = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["site__nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "attached_form"], name="unique_expected_visits_per_site_form"
            ),
        ]

    def __str__(self):
        return f"{self.attached_form} @ {self.site} = {self.nombre_prevu}"
