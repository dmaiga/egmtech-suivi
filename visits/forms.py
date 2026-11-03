from django import forms
from django.db import transaction

from accounts.models import User
from clients.models import Site
from forms_cms.models import AttachedForm

from .models import Mission


class MissionForm(forms.ModelForm):
    """Assigne en une fois plusieurs sites d'un même client à un auditeur : une mission par site."""

    sites = forms.ModelMultipleChoiceField(
        queryset=Site.objects.all(),
        label="Sites",
        error_messages={"required": "Sélectionner au moins un site."},
    )

    class Meta:
        model = Mission
        fields = ["superviseur", "attached_form"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["superviseur"].queryset = User.objects.filter(
            role=User.Role.SUPERVISEUR, is_active=True
        )
        self.fields["attached_form"].queryset = AttachedForm.objects.filter(actif=True)

    def clean(self):
        cleaned = super().clean()
        attached = cleaned.get("attached_form")
        sites = cleaned.get("sites")
        if attached and sites and any(site.client_id != attached.client_id for site in sites):
            raise forms.ValidationError("Le formulaire attaché doit appartenir au client du site.")
        return cleaned

    def save_missions(self, created_by):
        with transaction.atomic():
            return [
                Mission.objects.create(
                    superviseur=self.cleaned_data["superviseur"],
                    site=site,
                    attached_form=self.cleaned_data["attached_form"],
                    created_by=created_by,
                )
                for site in self.cleaned_data["sites"]
            ]
