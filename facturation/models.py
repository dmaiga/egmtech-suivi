from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.lookups import Exact
from django.utils import timezone

from core.storage import get_upload_storage

from .exceptions import DocumentNonModifiable

# Bornes des paramètres numériques du profil (validation du formulaire et contrainte en base).
TAUX_TVA_MIN, TAUX_TVA_MAX = 0, 100  # 0 : exonération voulue
VALIDITE_DEVIS_MIN, VALIDITE_DEVIS_MAX = 1, 365
DELAI_RELANCE_MIN, DELAI_RELANCE_MAX = 1, 90

# Montants en FCFA : entiers, prix multiples de 5. Bornes hautes de sécurité : un total de
# document reste très loin de la limite d'une colonne BIGINT (9,2 x 10^18).
PAS_MONTANT = 5
PRIX_UNITAIRE_MAX = 10**12
QUANTITE_MIN, QUANTITE_MAX = 1, 10**6


def valider_multiple_de_5(valeur):
    if valeur % PAS_MONTANT:
        raise ValidationError(f"Le montant doit être un multiple de {PAS_MONTANT} FCFA.")


VALIDATEURS_PRIX = [MinValueValidator(PAS_MONTANT), MaxValueValidator(PRIX_UNITAIRE_MAX), valider_multiple_de_5]
VALIDATEURS_QUANTITE = [MinValueValidator(QUANTITE_MIN), MaxValueValidator(QUANTITE_MAX)]
VALIDATEURS_TAUX = [MinValueValidator(TAUX_TVA_MIN), MaxValueValidator(TAUX_TVA_MAX)]
VALIDATEURS_VALIDITE = [MinValueValidator(VALIDITE_DEVIS_MIN), MaxValueValidator(VALIDITE_DEVIS_MAX)]


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


class ProduitQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Un produit ne se supprime pas : le désactiver.")


class Produit(models.Model):
    """Article du catalogue. Ses valeurs sont copiées dans les lignes : le modifier ne change aucun document."""

    designation = models.CharField("désignation", max_length=300)
    prix_unitaire = models.PositiveBigIntegerField("prix unitaire (FCFA)", validators=VALIDATEURS_PRIX)
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    objects = ProduitQuerySet.as_manager()

    class Meta:
        ordering = ["designation", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(prix_unitaire__gte=PAS_MONTANT, prix_unitaire__lte=PRIX_UNITAIRE_MAX),
                name="facturation_produit_prix_bornes",
            ),
            models.CheckConstraint(
                condition=Exact(F("prix_unitaire") % PAS_MONTANT, 0), name="facturation_produit_prix_multiple_5"
            ),
        ]

    def __str__(self):
        return self.designation

    def delete(self, *args, **kwargs):
        raise ValidationError("Un produit ne se supprime pas : le désactiver.")


# Statuts possibles selon le type (contrainte en base ; transitions dans services.py).
STATUTS_DEVIS = ("brouillon", "envoye", "accepte", "refuse")
STATUTS_FACTURE = ("brouillon", "emise", "payee", "annulee")


class DocumentQuerySet(models.QuerySet):
    def expires(self):
        """Devis envoyés dont la date de validité est passée (jamais stocké, calculé à la date du jour)."""
        return self.filter(
            type=Document.Type.DEVIS,
            statut=Document.Statut.ENVOYE,
            date_validite__lt=timezone.localdate(),
        )

    def delete(self):
        if self.exclude(statut=Document.Statut.BROUILLON).exists():
            raise DocumentNonModifiable("Seuls les brouillons peuvent être supprimés.")
        return super().delete()


class Document(models.Model):
    """Devis ou facture. Modifiable uniquement en brouillon ; les règles sont dans services.py."""

    class Type(models.TextChoices):
        DEVIS = "devis", "Devis"
        FACTURE = "facture", "Facture"

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        ENVOYE = "envoye", "Envoyé"
        ACCEPTE = "accepte", "Accepté"
        REFUSE = "refuse", "Refusé"
        EMISE = "emise", "Émise"
        PAYEE = "payee", "Payée"
        ANNULEE = "annulee", "Annulée"

    # Hors brouillon, seuls ces champs changent encore (transitions de statut).
    CHAMPS_MODIFIABLES_HORS_BROUILLON = {"statut", "updated_at"}

    type = models.CharField(max_length=10, choices=Type.choices)
    numero = models.CharField(
        "numéro", max_length=20, unique=True, null=True, blank=True,
        help_text="Attribué à l'émission ; vide (NULL) tant que brouillon.",
    )
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    contact = models.ForeignKey("ContactClient", on_delete=models.PROTECT, related_name="documents")
    contact_nom = models.CharField("nom du contact", max_length=200, blank=True)
    contact_telephone = models.CharField("téléphone du contact", max_length=50, blank=True)
    contact_adresse = models.TextField("adresse du contact", blank=True)
    objet = models.CharField(max_length=300, blank=True)
    lieu_livraison = models.CharField("lieu de livraison", max_length=300, blank=True)
    taux_tva = models.PositiveSmallIntegerField("taux de TVA (%)", validators=VALIDATEURS_TAUX)
    validite_jours = models.PositiveSmallIntegerField(
        "validité (jours)", null=True, blank=True, validators=VALIDATEURS_VALIDITE,
        help_text="Devis uniquement.",
    )
    date_emission = models.DateField("date d'émission", null=True, blank=True)
    date_validite = models.DateField("date de validité", null=True, blank=True)
    total_ht = models.PositiveBigIntegerField("total HT", default=0)
    total_tva = models.PositiveBigIntegerField("total TVA", default=0)
    total_ttc = models.PositiveBigIntegerField("total TTC", default=0)
    source = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="factures",
        help_text="Devis d'origine d'une facture.",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="documents_facturation"
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["type", "statut"], name="facturation_doc_type_statut")]
        constraints = [
            models.CheckConstraint(
                condition=Q(type="devis", statut__in=STATUTS_DEVIS) | Q(type="facture", statut__in=STATUTS_FACTURE),
                name="facturation_doc_statut_selon_type",
            ),
            models.CheckConstraint(
                condition=(Q(statut="brouillon") & Q(numero__isnull=True))
                | (~Q(statut="brouillon") & Q(numero__isnull=False)),
                name="facturation_doc_numero_hors_brouillon",
            ),
            models.CheckConstraint(
                condition=Q(source__isnull=True) | Q(type="facture"),
                name="facturation_doc_source_facture",
            ),
            models.CheckConstraint(
                condition=Q(taux_tva__gte=TAUX_TVA_MIN, taux_tva__lte=TAUX_TVA_MAX),
                name="facturation_doc_taux_tva_bornes",
            ),
            models.CheckConstraint(
                condition=Q(total_ttc=F("total_ht") + F("total_tva")),
                name="facturation_doc_ttc_egal_ht_plus_tva",
            ),
        ]

    def __str__(self):
        return self.numero or f"{self.get_type_display()} brouillon #{self.pk}"

    @property
    def est_brouillon(self):
        return self.statut == self.Statut.BROUILLON

    @property
    def est_expire(self):
        """Devis envoyé dont la date de validité est passée. Jamais stocké."""
        return (
            self.type == self.Type.DEVIS
            and self.statut == self.Statut.ENVOYE
            and self.date_validite is not None
            and self.date_validite < timezone.localdate()
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self._verifier_modification_autorisee()
        super().save(*args, **kwargs)

    def _verifier_modification_autorisee(self):
        """Hors brouillon (en base), refuse tout changement autre que le statut."""
        champs = [f.attname for f in self._meta.concrete_fields]
        en_base = type(self).objects.filter(pk=self.pk).values(*champs).first()
        if en_base is None or en_base["statut"] == self.Statut.BROUILLON:
            return
        modifies = {c for c in champs if en_base[c] != getattr(self, c)} - self.CHAMPS_MODIFIABLES_HORS_BROUILLON
        if modifies:
            raise DocumentNonModifiable(
                f"{self} n'est plus un brouillon : impossible de modifier {', '.join(sorted(modifies))}."
            )

    def delete(self, *args, **kwargs):
        if not self.est_brouillon:
            raise DocumentNonModifiable("Seuls les brouillons peuvent être supprimés.")
        return super().delete(*args, **kwargs)


class LigneDocumentQuerySet(models.QuerySet):
    def delete(self):
        if self.exclude(document__statut=Document.Statut.BROUILLON).exists():
            raise DocumentNonModifiable("Les lignes d'un document émis ne se suppriment pas.")
        return super().delete()


class LigneDocument(models.Model):
    """Ligne figée : désignation et prix copiés, sans lien vivant avec le produit."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="lignes")
    rang = models.PositiveIntegerField()
    designation = models.CharField("désignation", max_length=300)
    quantite = models.PositiveIntegerField("quantité", validators=VALIDATEURS_QUANTITE)
    prix_unitaire = models.PositiveBigIntegerField("prix unitaire (FCFA)", validators=VALIDATEURS_PRIX)
    total = models.PositiveBigIntegerField("total de la ligne")
    produit = models.ForeignKey(
        Produit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Pour mémoire : produit d'où la ligne a été copiée.",
    )

    objects = LigneDocumentQuerySet.as_manager()

    class Meta:
        ordering = ["document", "rang"]
        constraints = [
            models.UniqueConstraint(fields=["document", "rang"], name="facturation_ligne_rang_unique"),
            models.CheckConstraint(
                condition=Q(quantite__gte=QUANTITE_MIN, quantite__lte=QUANTITE_MAX),
                name="facturation_ligne_quantite_bornes",
            ),
            models.CheckConstraint(
                condition=Q(prix_unitaire__gte=PAS_MONTANT, prix_unitaire__lte=PRIX_UNITAIRE_MAX),
                name="facturation_ligne_prix_bornes",
            ),
            models.CheckConstraint(
                condition=Exact(F("prix_unitaire") % PAS_MONTANT, 0), name="facturation_ligne_prix_multiple_5"
            ),
            models.CheckConstraint(
                condition=Q(total=F("quantite") * F("prix_unitaire")),
                name="facturation_ligne_total",
            ),
        ]

    def __str__(self):
        return f"{self.document} — {self.rang}. {self.designation}"

    def _verifier_document_brouillon(self):
        statut = Document.objects.filter(pk=self.document_id).values_list("statut", flat=True).first()
        if statut is not None and statut != Document.Statut.BROUILLON:
            raise DocumentNonModifiable("Les lignes d'un document émis ne se modifient pas.")

    def save(self, *args, **kwargs):
        self._verifier_document_brouillon()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._verifier_document_brouillon()
        return super().delete(*args, **kwargs)


class SequenceNumero(models.Model):
    """Dernier numéro attribué par type de document et par année (verrouillé à chaque attribution)."""

    type = models.CharField(max_length=10, choices=Document.Type.choices)
    annee = models.PositiveSmallIntegerField("année")
    dernier = models.PositiveIntegerField("dernier numéro attribué", default=0)

    class Meta:
        ordering = ["type", "annee"]
        verbose_name = "séquence de numérotation"
        verbose_name_plural = "séquences de numérotation"
        constraints = [
            models.UniqueConstraint(fields=["type", "annee"], name="facturation_sequence_type_annee"),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.annee} : {self.dernier}"


class HistoriqueStatut(models.Model):
    """Une ligne à la création du brouillon (ancien statut vide) puis à chaque transition."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="historique")
    ancien_statut = models.CharField(max_length=10, choices=Document.Statut.choices, blank=True)
    nouveau_statut = models.CharField(max_length=10, choices=Document.Statut.choices)
    date = models.DateTimeField(default=timezone.now)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="historique_facturation"
    )

    class Meta:
        ordering = ["date", "pk"]
        verbose_name = "historique de statut"
        verbose_name_plural = "historique des statuts"

    def __str__(self):
        return f"{self.document} : {self.ancien_statut or '—'} → {self.nouveau_statut}"
