from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User

from .models import Client, Site


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["nom", "actif"]


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["code", "nom", "ville", "quartier", "latitude", "longitude", "responsable_local"]


class ClientUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
