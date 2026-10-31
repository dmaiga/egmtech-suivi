from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="visites_creees")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
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

    commentaire_rejet = models.TextField(blank=True)
    decision_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decisions_visites",
        help_text="Auteur de la dernière décision de revue (validation, rejet, publication...).",
    )
    decision_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_debut"]
        permissions = [
            ("validate_visits", "Peut valider les visites"),
        ]

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
    miniature = models.ImageField(
        upload_to="visites/miniatures/", storage=get_upload_storage, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Photo {self.field_key} - visite {self.visit_id}"

    @property
    def vignette_url(self):
        """Miniature si elle existe (anciennes photos : image d'origine)."""
        return (self.miniature or self.image).url


class Echange(models.Model):
    """Conversation entre un client et les managers, éventuellement liée à une visite publiée."""

    class Statut(models.TextChoices):
        OUVERT = "ouvert", "Ouvert"
        CLOS = "clos", "Clos"

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="echanges")
    visit = models.OneToOneField(
        Visit, on_delete=models.CASCADE, related_name="echange", null=True, blank=True
    )
    sujet = models.CharField(max_length=200)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.OUVERT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    dernier_message_le = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-dernier_message_le"]

    def __str__(self):
        return f"{self.sujet} ({self.get_statut_display()})"


class EchangeMessage(models.Model):
    echange = models.ForeignKey(Echange, on_delete=models.CASCADE, related_name="messages")
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="messages_echange"
    )
    texte = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    lu_le = models.DateTimeField(null=True, blank=True, help_text="Lu par l'autre partie.")

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Message {self.pk} - échange {self.echange_id}"


class EchangeFichier(models.Model):
    """Pièce jointe d'un message d'échange (image optimisée avec miniature, ou document)."""

    message = models.ForeignKey(EchangeMessage, on_delete=models.CASCADE, related_name="fichiers")
    fichier = models.FileField(upload_to="echanges/", storage=get_upload_storage)
    miniature = models.ImageField(
        upload_to="echanges/miniatures/", storage=get_upload_storage, blank=True
    )
    nom_original = models.CharField(max_length=200)
    est_image = models.BooleanField(default=False)
    taille = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.nom_original
