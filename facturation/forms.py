from django import forms
from django.db.models import Q

from . import services
from .exceptions import ErreurFacturation
from .models import ContactClient, Document, Produit, ProfilEmetteur
from .services import IMAGES_PROFIL, preparer_image_profil


def _largeur_pleine(form):
    """Champs en pleine largeur ; le style vient de ds.css."""
    for field in form.fields.values():
        if not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput)):
            field.widget.attrs.setdefault("class", "w-full")


class ProfilEmetteurForm(forms.ModelForm):
    # Logo et cachet hors du ModelForm : ils sont validés et convertis en PNG avant stockage,
    # et le widget par défaut afficherait un lien direct vers le fichier.
    logo = forms.FileField(required=False, widget=forms.FileInput(attrs={"accept": "image/*"}))
    retirer_logo = forms.BooleanField(required=False, label="Retirer le logo actuel")
    cachet = forms.FileField(required=False, widget=forms.FileInput(attrs={"accept": "image/*"}))
    retirer_cachet = forms.BooleanField(required=False, label="Retirer le cachet actuel")

    class Meta:
        model = ProfilEmetteur
        fields = [
            "raison_sociale", "adresse", "telephone", "email", "site_web", "rccm", "numero_fiscal",
            "coordonnees_bancaires", "responsable_nom", "responsable_fonction", "phrase_remerciement",
            "taux_tva_defaut", "validite_devis_jours", "delai_relance_jours",
        ]
        widgets = {
            "adresse": forms.Textarea(attrs={"rows": 3}),
            "coordonnees_bancaires": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _largeur_pleine(self)

    def _clean_image(self, champ):
        fichier = self.cleaned_data.get(champ)
        if not fichier:
            return None
        try:
            return preparer_image_profil(fichier)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_logo(self):
        return self._clean_image("logo")

    def clean_cachet(self):
        return self._clean_image("cachet")

    def clean(self):
        cleaned = super().clean()
        for champ in IMAGES_PROFIL:
            if cleaned.get(champ) and cleaned.get(f"retirer_{champ}"):
                self.add_error(f"retirer_{champ}", "Envoyer une nouvelle image ou retirer l'actuelle, pas les deux.")
        return cleaned


class ContactClientForm(forms.ModelForm):
    class Meta:
        model = ContactClient
        fields = ["nom", "telephone", "email", "adresse", "notes"]
        widgets = {
            "telephone": forms.TextInput(attrs={"type": "tel"}),
            "adresse": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _largeur_pleine(self)


class MontantField(forms.IntegerField):
    """Entier saisi avec ou sans séparateurs de milliers (« 1 250 000 »)."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        return super().to_python(value)


def _valider_par_le_service(verification, valeur):
    """Applique un contrôle de services.py et convertit son erreur en erreur de formulaire."""
    if valeur is None:
        return valeur
    try:
        return verification(valeur)
    except ErreurFacturation as exc:
        raise forms.ValidationError(str(exc)) from exc


class ProduitForm(forms.ModelForm):
    prix_unitaire = MontantField(label="Prix unitaire (FCFA)", help_text="Entier, multiple de 5.")

    class Meta:
        model = Produit
        fields = ["designation", "prix_unitaire"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _largeur_pleine(self)

    def clean_prix_unitaire(self):
        return _valider_par_le_service(services.verifier_prix_unitaire, self.cleaned_data.get("prix_unitaire"))


class DocumentForm(forms.Form):
    """En-tête d'un brouillon : création et modification."""

    contact = forms.ModelChoiceField(queryset=ContactClient.objects.none(), empty_label="Choisir un contact")
    objet = forms.CharField(max_length=300, required=False)
    lieu_livraison = forms.CharField(label="Lieu de livraison", max_length=300, required=False)
    taux_tva = forms.IntegerField(label="Taux de TVA (%)", help_text="0 pour une exonération.")
    validite_jours = forms.IntegerField(label="Validité du devis (jours)")

    def __init__(self, *args, type_document, contact_actuel=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Contacts actifs ; le contact déjà choisi reste affiché même s'il a été désactivé depuis.
        contacts = ContactClient.objects.filter(actif=True)
        if contact_actuel is not None:
            contacts = ContactClient.objects.filter(Q(actif=True) | Q(pk=contact_actuel.pk))
        self.fields["contact"].queryset = contacts
        if type_document != Document.Type.DEVIS:
            del self.fields["validite_jours"]
        _largeur_pleine(self)

    def clean_taux_tva(self):
        return _valider_par_le_service(services.verifier_taux_tva, self.cleaned_data.get("taux_tva"))

    def clean_validite_jours(self):
        return _valider_par_le_service(services.verifier_validite_jours, self.cleaned_data.get("validite_jours"))


class LigneForm(forms.Form):
    designation = forms.CharField(label="Désignation", max_length=300)
    quantite = forms.IntegerField(label="Quantité")
    prix_unitaire = MontantField(label="Prix unitaire (FCFA)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _largeur_pleine(self)
        self.fields["quantite"].widget.attrs["inputmode"] = "numeric"
        self.fields["prix_unitaire"].widget = forms.TextInput(attrs={"class": "w-full", "inputmode": "numeric"})

    def clean_quantite(self):
        return _valider_par_le_service(services.verifier_quantite, self.cleaned_data.get("quantite"))

    def clean_prix_unitaire(self):
        return _valider_par_le_service(services.verifier_prix_unitaire, self.cleaned_data.get("prix_unitaire"))


class AjoutProduitForm(forms.Form):
    produit = forms.ModelChoiceField(
        label="Produit", queryset=Produit.objects.filter(actif=True), empty_label="Choisir un produit"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _largeur_pleine(self)
