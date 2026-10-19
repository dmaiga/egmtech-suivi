from django.core.management.base import BaseCommand

from forms_cms.models import FormTemplate

RAPPORT_INSTALLATION_SCHEMA = {
    "sections": [
        {
            "title": "Identification",
            "fields": [
                {"key": "nom_technicien", "label": "Nom du technicien", "type": "text", "required": True},
                {"key": "date_intervention", "label": "Date d'intervention", "type": "date", "required": True},
            ],
        },
        {
            "title": "Localisation",
            "fields": [
                {"key": "position_gps", "label": "Position GPS", "type": "gps", "required": True},
            ],
        },
        {
            "title": "Photos",
            "fields": [
                {"key": "photo_facade", "label": "Photo façade", "type": "photo", "max_photos": 1, "required": True},
                {
                    "key": "photo_installation",
                    "label": "Photo installation",
                    "type": "photo",
                    "max_photos": 1,
                    "required": True,
                },
                {"key": "photo_compteur", "label": "Photo compteur", "type": "photo", "max_photos": 1, "required": True},
                {
                    "key": "photo_cablage",
                    "label": "Photo câblage",
                    "type": "photo",
                    "max_photos": 1,
                    "required": True,
                },
            ],
        },
        {
            "title": "Observations",
            "fields": [
                {"key": "observations", "label": "Observations", "type": "text", "required": False},
                {"key": "signature", "label": "Signature", "type": "signature", "required": True},
            ],
        },
    ]
}

AUDIT_TECHNIQUE_SCHEMA = {
    "sections": [
        {
            "title": "Identification",
            "fields": [
                {"key": "nom_technicien", "label": "Nom du technicien", "type": "text", "required": True},
                {"key": "date_audit", "label": "Date de l'audit", "type": "date", "required": True},
                {"key": "nombre_cameras", "label": "Nombre de caméras", "type": "number", "required": True},
            ],
        },
        {
            "title": "Caméras",
            "fields": [
                {
                    "key": "cameras",
                    "label": "Caméras",
                    "type": "repeat",
                    "required": True,
                    "fields": [
                        {"key": "marque", "label": "Marque", "type": "text", "required": True},
                        {"key": "modele", "label": "Modèle", "type": "text", "required": True},
                        {"key": "serie", "label": "Numéro de série", "type": "text", "required": True},
                        {
                            "key": "etat",
                            "label": "État",
                            "type": "choice",
                            "required": True,
                            "options": ["Fonctionnel", "Défectueux", "À remplacer"],
                        },
                        {"key": "photo_camera", "label": "Photo caméra", "type": "photo", "max_photos": 2, "required": True},
                    ],
                },
            ],
        },
        {
            "title": "Enregistreur",
            "fields": [
                {"key": "enregistreur", "label": "Enregistreur", "type": "text", "required": True},
                {"key": "anomalies", "label": "Anomalies", "type": "text", "required": False},
                {"key": "observation", "label": "Observation", "type": "text", "required": False},
                {"key": "signature", "label": "Signature", "type": "signature", "required": True},
            ],
        },
    ]
}


class Command(BaseCommand):
    help = "Crée deux formulaires de démonstration : Rapport d'installation et Audit technique."

    def handle(self, *args, **options):
        for nom, description, schema in [
            (
                "Rapport d'installation",
                "Rapport standard de visite d'installation.",
                RAPPORT_INSTALLATION_SCHEMA,
            ),
            (
                "Audit technique",
                "Audit technique des caméras et de l'enregistreur sur site.",
                AUDIT_TECHNIQUE_SCHEMA,
            ),
        ]:
            template, created = FormTemplate.objects.update_or_create(
                nom=nom,
                defaults={"description": description, "schema": schema, "actif": True},
            )
            status = "créé" if created else "mis à jour"
            self.stdout.write(self.style.SUCCESS(f"Formulaire '{template.nom}' {status}."))
