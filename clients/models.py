from django.db import models


class Client(models.Model):
    nom = models.CharField(max_length=150)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Site(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="sites")
    code = models.CharField(max_length=50)
    nom = models.CharField(max_length=150)
    ville = models.CharField(max_length=100, blank=True)
    quartier = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    responsable_local = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["client", "code"], name="unique_site_code_per_client"),
        ]

    def __str__(self):
        return f"{self.nom} ({self.client.nom})"
