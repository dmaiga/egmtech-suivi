# Taux de TVA du profil : 0 autorisé (exonération).

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('facturation', '0001_initial'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='profilemetteur',
            name='facturation_profil_taux_tva_bornes',
        ),
        migrations.AlterField(
            model_name='profilemetteur',
            name='taux_tva_defaut',
            field=models.PositiveSmallIntegerField(default=18, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name='taux de TVA par défaut (%)'),
        ),
        migrations.AddConstraint(
            model_name='profilemetteur',
            constraint=models.CheckConstraint(condition=models.Q(('taux_tva_defaut__gte', 0), ('taux_tva_defaut__lte', 100)), name='facturation_profil_taux_tva_bornes'),
        ),
    ]
