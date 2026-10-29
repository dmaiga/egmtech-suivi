from django.db import migrations


def remove_unused_initial_bnda(apps, schema_editor):
    Client = apps.get_model("clients", "Client")
    Template = apps.get_model("forms_cms", "FormTemplate")
    Attached = apps.get_model("forms_cms", "AttachedForm")
    Mission = apps.get_model("visits", "Mission")
    User = apps.get_model("accounts", "User")
    # L'ancienne migration vient de créer le seul client et le seul modèle dans
    # une base neuve. Ne rien supprimer si la base contient déjà d'autres données.
    if User.objects.exists() or Client.objects.count() != 1 or Template.objects.count() != 1:
        return
    from forms_cms.bnda_schema import bnda_schema
    original_schema = bnda_schema()
    for template in Template.objects.filter(nom="Audit CCTV BNDA", schema=original_schema):
        for client in Client.objects.filter(nom="BNDA"):
            if client.sites.exists() or User.objects.filter(client=client).exists():
                continue
            attached = Attached.objects.filter(client=client, template=template)
            if any(Mission.objects.filter(attached_form=item).exists() or item.expected_visits.exists() for item in attached):
                continue
            if Attached.objects.filter(client=client).exclude(template=template).exists():
                continue
            attached.delete()
            client.delete()
        if not Client.objects.filter(nom="BNDA").exists() and not Attached.objects.filter(template=template).exists():
            template.delete()


class Migration(migrations.Migration):
    dependencies = [("forms_cms", "0003_bnda_time_and_photos"), ("visits", "0003_visit_creation_audit"), ("accounts", "0002_alter_user_options_user_client_and_more")]
    operations = [migrations.RunPython(remove_unused_initial_bnda, migrations.RunPython.noop)]
