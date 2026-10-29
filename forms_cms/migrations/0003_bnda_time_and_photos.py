from django.db import migrations


def update_schema(schema):
    labels = {
        "photos_cameras": "Photos des caméras et de leurs étiquettes (minimum 10)",
        "photos_enregistreur": "Photos de l’enregistreur et de son étiquette (minimum 3)",
        "photos_zones": "Vues d’ensemble des zones signalées (minimum 5)",
        "photos_pieces": "Photos des pièces défectueuses et des étiquettes disponibles (minimum 5)",
        "photos_baie": "Photos de la baie informatique (minimum 1)",
    }
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if field.get("key") == "heure_audit":
                field["type"] = "time"
            if field.get("type") == "photo":
                field["max_photos"] = 150
                if field.get("key") in labels:
                    field["label"] = labels[field["key"]]
    return schema


def update_bnda(apps, schema_editor):
    Template = apps.get_model("forms_cms", "FormTemplate")
    Attached = apps.get_model("forms_cms", "AttachedForm")
    templates = Template.objects.filter(nom="Audit CCTV BNDA")
    for template in templates:
        template.schema = update_schema(template.schema)
        template.save(update_fields=["schema"])
    for attached in Attached.objects.filter(template__in=templates, client__nom="BNDA"):
        attached.schema = update_schema(attached.schema)
        attached.save(update_fields=["schema"])


class Migration(migrations.Migration):
    dependencies = [("forms_cms", "0002_bnda_audit")]
    operations = [migrations.RunPython(update_bnda, migrations.RunPython.noop)]
