from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.storage import get_upload_storage


class Mission(models.Model):
    """Assignation : un superviseur doit exécuter un formulaire attaché sur un site."""

    superviseur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="missions"
    )
    site = models.ForeignKey("clients.Site", on_delete=models.PROTECT, related_name="missions")
    attached_form = models.ForeignKey(
        "forms_cms.AttachedForm", on_delete=models.PROTECT, related_name="missions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="missions_creees"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.superviseur} @ {self.site} - {self.attached_form.nom}"

    def clean(self):
        super().clean()
        if self.attached_form_id and self.site_id and self.attached_form.client_id != self.site.client_id:
            raise ValidationError(
                "Le formulaire attaché doit appartenir au client du site."
            )
        if self.attached_form_id and not self.attached_form.actif:
            raise ValidationError("Le formulaire attaché est désactivé.")


class Visit(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        SOUMISE = "soumise", "Soumise"
        A_CORRIGER = "a_corriger", "À corriger"
        VALIDEE = "validee", "Validée"
        PUBLIEE = "publiee", "Publiée"
        DEPUBLIEE = "depubliee", "Dépubliée"

    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name="visits")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="visits")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.BROUILLON)
    reponses = models.JSONField(default=dict, blank=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_soumission = models.DateTimeField(null=True, blank=True)
    gps_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    signature_superviseur = models.ImageField(
        upload_to="visites/signatures/", storage=get_upload_storage, null=True, blank=True
    )
    signature_responsable = models.ImageField(
        upload_to="visites/signatures/", storage=get_upload_storage, null=True, blank=True
    )
    responsable_absent = models.BooleanField(default=False)
    motif_absence_responsable = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date_debut"]

    def __str__(self):
        return f"Visite {self.pk} - {self.mission} ({self.get_statut_display()})"

    def peut_etre_modifiee(self):
        return self.statut in (self.Statut.BROUILLON, self.Statut.A_CORRIGER)


class VisitPhoto(models.Model):
    """Une photo prise pour un champ donné du schéma (éventuellement dans un groupe répétable)."""

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="photos")
    field_key = models.CharField(max_length=255, help_text="Clé du champ, ex: 'cameras__0__photo_camera'.")
    legende = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="visites/photos/", storage=get_upload_storage)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Photo {self.field_key} - visite {self.visit_id}"
