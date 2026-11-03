from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from clients.models import Client, Site
from clients.services import cle_nom
from forms_cms.models import ExpectedVisits, FormTemplate
from forms_cms.services import attach_template_to_client, set_expected_visits


# Agences BNDA : (nom du site, ville).
AGENCES = [
    ("Générale Bâtiment", "Bamako"), ("Agence de l'Hippodrome", "Bamako"), ("Médine", "Bamako"),
    ("Ngolonina", "Bamako"), ("Grand Marché", "Bamako"), ("Marché Rose", "Bamako"),
    ("Bamako Coura", "Bamako"), ("Sébénicoro", "Bamako"), ("Bacodjicoroni", "Bamako"),
    ("Kalaban Coro", "Bamako"), ("Kalaban Coura", "Bamako"), ("Niamacoro", "Bamako"),
    ("Faladjè", "Bamako"), ("Missabougou", "Bamako"), ("Badalabougou", "Bamako"),
    ("Kati", "Kati"), ("Kayes Plateau", "Kayes"), ("Kayes Khasso", "Kayes"),
    ("Kéniéba", "Kéniéba"), ("Kita", "Kita"), ("Koulikoro", "Koulikoro"),
    ("Fana", "Fana"), ("Dioïla", "Dioïla"), ("Baroueli", "Baroueli"),
    ("Ségou Centre", "Ségou"), ("Ségou Pélengana", "Ségou"), ("Niono", "Niono"),
    ("Bla", "Bla"), ("Mpessoba", "Mpessoba"), ("Koutiala", "Koutiala"),
    ("Koutiala Koko", "Koutiala"), ("Yorosso", "Yorosso"), ("San", "San"),
    ("Sévaré", "Mopti"), ("Mopti", "Mopti"), ("Bandiagara", "Bandiagara"),
    ("Tombouctou", "Tombouctou"), ("Gao", "Gao"), ("Ouélessébougou", "Ouélessébougou"),
    ("Bougouni", "Bougouni"), ("Yanfolila", "Yanfolila"), ("Niéna", "Niéna"),
    ("Kolondiéba", "Kolondiéba"), ("Kadiolo", "Kadiolo"), ("Sikasso Wayerma", "Sikasso"),
    ("Sikasso Médine", "Sikasso"), ("Zégoua", "Zégoua"),
]


class Command(BaseCommand):
    help = (
        "Crée les agences BNDA absentes, attache le formulaire « Audit CCTV BNDA » au client BNDA "
        "(une seule fois) et prévoit une visite par agence. Ne crée aucune mission : le dispatching aux auditeurs reste au manager. "
        "Sans danger à relancer : une prévision existante n'est pas modifiée."
    )

    def add_arguments(self, parser):
        parser.add_argument("--client", default="BNDA", help="Nom du client (défaut : BNDA).")
        parser.add_argument("--par", help="E-mail de l'utilisateur inscrit au journal (défaut : premier administrateur).")

    def handle(self, *args, **options):
        client = Client.objects.filter(nom__iexact=options["client"]).first()
        if client is None:
            raise CommandError(f"Client « {options['client']} » introuvable.")
        template = FormTemplate.objects.filter(nom="Audit CCTV BNDA").first()
        if template is None:
            raise CommandError("Modèle « Audit CCTV BNDA » absent : lancer d'abord installer_formulaire_bnda.")
        if options["par"]:
            user = User.objects.filter(email__iexact=options["par"]).first()
        else:
            user = User.objects.filter(is_superuser=True).order_by("pk").first()
        if user is None:
            raise CommandError("Utilisateur introuvable : préciser --par <e-mail>.")

        with transaction.atomic():
            # Une agence déjà saisie (même avec d'autres accents ou majuscules) n'est pas recréée.
            noms = {cle_nom(nom) for nom in client.sites.values_list("nom", flat=True)}
            sites_crees = 0
            for nom, ville in AGENCES:
                if cle_nom(nom) not in noms:
                    Site.objects.create(client=client, nom=nom, ville=ville)
                    noms.add(cle_nom(nom))
                    sites_crees += 1
            self.stdout.write(self.style.SUCCESS(f"{sites_crees} agence(s) créée(s) chez {client.nom}."))

            attached = client.attached_forms.filter(template=template, actif=True).first()
            if attached is None:
                attached = attach_template_to_client(user, client, template)
                self.stdout.write(self.style.SUCCESS(f"Formulaire « {attached.nom} » attaché à {client.nom}."))
            else:
                self.stdout.write(self.style.WARNING(f"Formulaire « {attached.nom} » déjà attaché à {client.nom} ; réutilisé."))

            # Seuls les sites de ce client sont concernés (cloisonnement multi-clients).
            existants = set(ExpectedVisits.objects.filter(attached_form=attached).values_list("site_id", flat=True))
            creees = 0
            for site in client.sites.exclude(pk__in=existants):
                set_expected_visits(user, attached, site, 1)
                creees += 1

        total = client.sites.count()
        self.stdout.write(self.style.SUCCESS(
            f"{creees} prévision(s) d'une visite créée(s), {total - creees} déjà existante(s) — {total} agence(s) chez {client.nom}."
        ))
