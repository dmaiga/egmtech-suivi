from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User

from .models import Client, Site


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["nom", "actif"]
        labels = {
            "nom": "Nom de l'entreprise ou entité",
            "actif": "Client actif",
        }
        widgets = {
            "nom": forms.TextInput(attrs={
                "class": "w-full px-3.5 py-2.5 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm transition",
                "placeholder": "Ex: BNDA, EDM SA, Moov Africa...",
                "autofocus": "autofocus",
            }),
            "actif": forms.CheckboxInput(attrs={
                "class": "h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded cursor-pointer",
            }),
        }


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["code", "nom", "ville", "quartier", "latitude", "longitude", "responsable_local"]
        labels = {
            "code": "Code site",
            "nom": "Nom du site",
            "ville": "Ville",
            "quartier": "Quartier / Adresse",
            "latitude": "Latitude (GPS)",
            "longitude": "Longitude (GPS)",
            "responsable_local": "Responsable local (Nom & Contact)",
        }
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: BAM-001",
            }),
            "nom": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: Agence Principale",
            }),
            "ville": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: Bamako",
            }),
            "quartier": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: Hamdallaye ACI",
            }),
            "latitude": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "12.6392",
                "step": "any",
            }),
            "longitude": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "-8.0029",
                "step": "any",
            }),
            "responsable_local": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: Amadou Traoré - 76 00 00 00",
            }),
        }


class ClientUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        labels = {
            "username": "Identifiant de connexion",
            "email": "Adresse email",
        }
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Ex: client_bnda",
            }),
            "email": forms.EmailInput(attrs={
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "contact@client.com",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update({
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Mot de passe sécurisé",
            })
        if "password2" in self.fields:
            self.fields["password2"].widget.attrs.update({
                "class": "w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-sm",
                "placeholder": "Confirmer le mot de passe",
            })
