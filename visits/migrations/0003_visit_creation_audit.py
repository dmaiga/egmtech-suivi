from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_creation_date(apps, schema_editor):
    Visit = apps.get_model("visits", "Visit")
    Visit.objects.filter(date_debut__isnull=False).update(created_at=models.F("date_debut"))


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("visits", "0002_alter_visit_options_visit_commentaire_rejet_and_more"),
    ]
    operations = [
        migrations.AddField(model_name="visit", name="created_at", field=models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        migrations.AddField(model_name="visit", name="created_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="visites_creees", to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(backfill_creation_date, migrations.RunPython.noop),
    ]
