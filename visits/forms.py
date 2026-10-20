from django import forms

from accounts.models import User
from forms_cms.models import AttachedForm

from .models import Mission


class MissionForm(forms.ModelForm):
    class Meta:
        model = Mission
        fields = ["superviseur", "site", "attached_form"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["superviseur"].queryset = User.objects.filter(
            role=User.Role.SUPERVISEUR, is_active=True
        )
        self.fields["attached_form"].queryset = AttachedForm.objects.filter(actif=True)
