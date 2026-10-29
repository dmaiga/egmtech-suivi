from django import forms
from django.contrib.auth.models import Permission
from django.contrib.auth.forms import UserCreationForm

from .models import User


MANAGER_PERMISSIONS = ("manage_forms", "validate_visits", "manage_users")


class AuditorCreationForm(UserCreationForm):
    role = forms.ChoiceField(
        label="Type de compte",
        choices=[(User.Role.SUPERVISEUR, "Superviseur (auditeur)"), (User.Role.MANAGER, "Manager")],
        initial=User.Role.SUPERVISEUR,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Adresse e-mail",
        }

    field_order = ("role", "first_name", "last_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True
        for field in self.fields.values():
            field.widget.attrs.update({"class": "w-full rounded-xl border border-gray-300 px-4 py-3 text-sm focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte utilise déjà cette adresse e-mail.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data["role"]
        # La connexion se fait par e-mail ; l'identifiant interne en est dérivé.
        user.username = user.email
        if commit:
            user.save()
            self.save_m2m()
            if user.role == User.Role.MANAGER:
                # Un manager reçoit d'office les droits métier : l'admin n'intervient pas.
                user.user_permissions.add(*Permission.objects.filter(codename__in=MANAGER_PERMISSIONS))
        return user
