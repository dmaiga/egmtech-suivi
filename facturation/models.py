from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.storage import get_upload_storage

# Bornes des paramètres numériques du profil (validation du formulaire et contrainte en base).
TAUX_TVA_MIN, TAUX_TVA_MAX = 1, 100
VALIDITE_DEVIS_MIN, VALIDITE_DEVIS_MAX = 1, 365
DELAI_RELANCE_MIN, DELAI_RELANCE_MAX = 1, 90


class ProfilEmetteurQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Le profil émetteur ne peut pas être supprimé.")


class ProfilEmetteur(models.Model):
    """Identité de l'entreprise qui émet les devis et factures. Une seule ligne : ProfilEmetteur.get()."""

    # Garantit l'unicité en base, sans dépendre de la clé primaire : un seul `True` possible.
    singleton = models.BooleanField(default=True, unique=True, editable=False)

    raison_sociale = models.CharField(max_length=200, blank=True)
    adresse = models.TextField(blank=True)
    telephone = models.CharField("téléphone", max_length=50, blank=True)
    email = models.EmailField("e-mail", blank=True)
    site_web = models.CharField("site web", max_length=200, blank=True)
    rccm = models.CharField("RCCM", max_length=100, blank=True)
    numero_fiscal = models.CharField("numéro fiscal", max_length=100, blank=True)
    coordonnees_bancaires = models.TextField("coordonnées bancaires", blank=True)
    logo = models.ImageField(upload_to="facturation/profil/", storage=get_upload_storage, blank=True)
    cachet = models.ImageField(upload_to="facturation/profil/", storage=get_upload_storage, blank=True)
    responsable_nom = models.CharField("nom du responsable de facturation", max_length=150, blank=True)
    responsable_fonction = models.CharField("fonction du responsable", max_length=150, blank=True)
    phrase_remerciement = models.CharField("phrase de remerciement", max_length=300, blank=True)
    taux_tva_defaut = models.PositiveSmallIntegerField(
        "taux de TVA par défaut (%)",
        default=18,
        validators=[MinValueValidator(TAUX_TVA_MIN), MaxValueValidator(TAUX_TVA_MAX)],
    )
    validite_devis_jours = models.PositiveSmallIntegerField(
        "validité des devis (jours)",
        default=30,
        validators=[MinValueValidator(VALIDITE_DEVIS_MIN), MaxValueValidator(VALIDITE_DEVIS_MAX)],
    )
    delai_relance_jours = models.PositiveSmallIntegerField(
        "délai de relance (jours)",
        default=7,
        validators=[MinValueValidator(DELAI_RELANCE_MIN), MaxValueValidator(DELAI_RELANCE_MAX)],
    )

    objects = ProfilEmetteurQuerySet.as_manager()

    class Meta:
        verbose_name = "profil émetteur"
        verbose_name_plural = "profil émetteur"
        # Permission de tout le module, portée par ce modèle qui existera toujours
        # (déplacer une permission vers un autre modèle en ferait une nouvelle).
        permissions = [
            ("manage_invoices", "Peut gérer la facturation (devis, factures, contacts)"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(singleton=True), name="facturation_profil_singleton"),
            models.CheckConstraint(
                condition=models.Q(taux_tva_defaut__gte=TAUX_TVA_MIN, taux_tva_defaut__lte=TAUX_TVA_MAX),
                name="facturation_profil_taux_tva_bornes",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    validite_devis_jours__gte=VALIDITE_DEVIS_MIN, validite_devis_jours__lte=VALIDITE_DEVIS_MAX
                ),
                name="facturation_profil_validite_bornes",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    delai_relance_jours__gte=DELAI_RELANCE_MIN, delai_relance_jours__lte=DELAI_RELANCE_MAX
                ),
                name="facturation_profil_relance_bornes",
            ),
        ]

    def __str__(self):
        return self.raison_sociale or "Profil émetteur"

    @classmethod
    def get(cls):
        """Retourne le profil, créé avec les valeurs par défaut s'il n'existe pas encore."""
        profil, _ = cls.objects.get_or_create(singleton=True)
        return profil

    def save(self, *args, **kwargs):
        if self._state.adding and type(self).objects.exists():
            raise ValidationError("Le profil émetteur existe déjà : utiliser ProfilEmetteur.get().")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le profil émetteur ne peut pas être supprimé.")


class ContactClient(models.Model):
    """Client destinataire des devis et factures. Sans lien avec clients.Client (suivi terrain)."""

    nom = models.CharField(max_length=200)
    telephone = models.CharField("téléphone", max_length=50, blank=True)
    email = models.EmailField("e-mail", blank=True)
    adresse = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom", "pk"]
        verbose_name = "contact client"
        verbose_name_plural = "contacts clients"

    def __str__(self):
        return self.nom
