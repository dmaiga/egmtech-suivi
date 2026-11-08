from django import forms

from . import services
from .exceptions import ErreurFacturation
from .models import ContactClient, Produit, ProfilEmetteur
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

