from django.contrib.auth.forms import UserCreationForm

from .models import User


class AuditorCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "username", "email")
        labels = {
            "first_name": "Prénom",
            "last_name": "Nom",
            "username": "Identifiant de connexion",
            "email": "Adresse e-mail",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        for field in self.fields.values():
            field.widget.attrs.update({"class": "w-full rounded-xl border border-gray-300 px-4 py-3 text-sm focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500"})

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.SUPERVISEUR
        if commit:
            user.save()
        return user
