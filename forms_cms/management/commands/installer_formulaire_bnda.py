from django.core.management.base import BaseCommand

from forms_cms.bnda_schema import bnda_schema
from forms_cms.models import FormTemplate


class Command(BaseCommand):
    help = "Installe le modèle d'audit CCTV BNDA sans créer de client ni d'affectation."

    def handle(self, *args, **options):
        name = "Audit CCTV BNDA"
        if FormTemplate.objects.filter(nom=name).exists():
            self.stdout.write(self.style.WARNING("Le formulaire existe déjà ; aucune modification effectuée."))
            return
        template = FormTemplate(nom=name, description="Audit de terrain CCTV pour BNDA.", schema=bnda_schema())
        template.full_clean()
        template.save()
        self.stdout.write(self.style.SUCCESS("Modèle Audit CCTV BNDA créé dans la bibliothèque."))
