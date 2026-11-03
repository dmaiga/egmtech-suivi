from django.core.management.base import BaseCommand

from accounts.models import User


# Prénom, nom, e-mail (sert aussi d'identifiant de connexion).
AUDITEURS = [
    ("Oumar", "Touré", "oumar.toure@egmtech.co"),
    ("Oumar", "Sidibé", "oumar.sidibe@egmtech.co"),
    ("Soumaïla", "Traoré", "soumaila.traore@egmtech.co"),
    ("Ousmane", "Diawara", "ousmane.diawara@egmtech.co"),
    ("Boubacar", "Sy", "boubacar.sy@egmtech.co"),
]


class Command(BaseCommand):
    help = "Crée les comptes auditeurs de production. Sans danger à relancer : un compte existant n'est pas modifié."

    def add_arguments(self, parser):
        # Le mot de passe initial n'est jamais écrit dans le code ni dans Git.
        parser.add_argument("--password", required=True, help="Mot de passe initial des comptes créés.")

    def handle(self, *args, **options):
        for first_name, last_name, email in AUDITEURS:
            if User.objects.filter(email__iexact=email).exists():
                self.stdout.write(self.style.WARNING(f"{email} existe déjà ; inchangé."))
                continue
            user = User(username=email, email=email, first_name=first_name, last_name=last_name, role=User.Role.SUPERVISEUR)
            user.set_password(options["password"])
            user.save()
            self.stdout.write(self.style.SUCCESS(f"{email} créé (auditeur)."))
