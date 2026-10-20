import base64
import random
from io import BytesIO

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from accounts.models import User
from clients.models import Client, Site
from core.models import ActivityLog
from core.services import log
from forms_cms.models import AttachedForm, FormTemplate
from forms_cms.services import attach_template_to_client, set_expected_visits
from visits.models import Mission, Visit, VisitPhoto
from visits.schema_utils import repeat_row_name

DEMO_PASSWORD = "demo1234"

DEMO_USERNAMES = [
    "admin",
    "manager1",
    "manager2",
    "sup1",
    "sup2",
    "sup3",
    "sup4",
    "client_bnda",
    "client_exemple",
]

SUPERVISEURS = [
    ("sup1", "Issa", "Konaté"),
    ("sup2", "Fatoumata", "Traoré"),
    ("sup3", "Moussa", "Diarra"),
    ("sup4", "Aminata", "Coulibaly"),
]

# (code, nom, ville, latitude, longitude)
SITES_BNDA = [
    ("BNDA-SIEGE", "Siège Bamako", "Bamako", "12.639200", "-8.002900"),
    ("BNDA-ACI", "Agence ACI 2000", "Bamako", "12.609600", "-7.996700"),
    ("BNDA-KAYES", "Agence Kayes", "Kayes", "14.446900", "-11.444800"),
    ("BNDA-SIKASSO", "Agence Sikasso", "Sikasso", "11.317600", "-5.666500"),
    ("BNDA-SEGOU", "Agence Ségou", "Ségou", "13.431700", "-6.215700"),
    ("BNDA-MOPTI", "Agence Mopti", "Mopti", "14.484300", "-4.197900"),
    ("BNDA-KLK1", "Agence Koulikoro Centre", "Koulikoro", "12.862500", "-7.560000"),
    ("BNDA-KLK2", "Agence Koulikoro Sud", "Koulikoro", "12.845000", "-7.550000"),
]

SITES_BE = [
    ("BE-SIEGE", "Siège Bamako", "Bamako", "12.650000", "-8.010000"),
    ("BE-KAYES", "Agence Kayes", "Kayes", "14.452000", "-11.430000"),
    ("BE-SIKASSO", "Agence Sikasso", "Sikasso", "11.325000", "-5.650000"),
]

AUDIT = "Audit technique"
INSTALLATION = "Rapport d'installation"

CAMERA_MARQUES = ["Hikvision", "Dahua", "ZKTeco"]
CAMERA_ETATS = ["Fonctionnel", "Fonctionnel", "Fonctionnel", "Défectueux", "À remplacer"]

# Chaque entrée décrit une visite de démonstration. Les offsets sont en jours
# avant aujourd'hui, pour étaler les visites sur les 6 dernières semaines.
VISIT_SPECS = [
    dict(
        key="v1", client="BNDA", site="BNDA-SIEGE", form=AUDIT, sup="sup1",
        statut=Visit.Statut.PUBLIEE, debut=42, soumission=41, decision=40,
        validateur="manager1", nb_cameras=8, anomalies=True,
    ),
    dict(
        key="v2", client="BNDA", site="BNDA-SIEGE", form=INSTALLATION, sup="sup2",
        statut=Visit.Statut.PUBLIEE, debut=39, soumission=38, decision=37,
        validateur="manager2",
    ),
    dict(
        key="v3", client="BNDA", site="BNDA-ACI", form=INSTALLATION, sup="sup1",
        statut=Visit.Statut.PUBLIEE, debut=36, soumission=35, decision=34,
        validateur="manager1",
    ),
    dict(
        key="v4", client="BNDA", site="BNDA-KAYES", form=AUDIT, sup="sup3",
        statut=Visit.Statut.PUBLIEE, debut=33, soumission=32, decision=31,
        validateur="manager2", nb_cameras=6, anomalies=False,
    ),
    dict(
        key="v5", client="BE", site="BE-SIEGE", form=AUDIT, sup="sup4",
        statut=Visit.Statut.PUBLIEE, debut=30, soumission=29, decision=28,
        validateur="manager1", nb_cameras=10, anomalies=True,
    ),
    dict(
        key="v6", client="BE", site="BE-KAYES", form=AUDIT, sup="sup2",
        statut=Visit.Statut.PUBLIEE, debut=27, soumission=26, decision=25,
        validateur="manager2", nb_cameras=7, anomalies=False,
    ),
    dict(
        key="v7", client="BNDA", site="BNDA-SIKASSO", form=AUDIT, sup="sup3",
        statut=Visit.Statut.DEPUBLIEE, debut=24, soumission=23, decision=22,
        validateur="manager1", nb_cameras=9, anomalies=True,
    ),
    dict(
        key="v8", client="BNDA", site="BNDA-SEGOU", form=INSTALLATION, sup="sup4",
        statut=Visit.Statut.VALIDEE, debut=21, soumission=20, decision=19,
        validateur="manager2",
    ),
    dict(
        key="v9", client="BNDA", site="BNDA-MOPTI", form=AUDIT, sup="sup1",
        statut=Visit.Statut.A_CORRIGER, debut=18, soumission=17, decision=16,
        validateur="manager1", nb_cameras=12, anomalies=True,
        commentaire_rejet="Plusieurs caméras sans photo lisible et numéro de série de "
        "l'enregistreur manquant : merci de reprendre l'audit sur ces points.",
    ),
    dict(
        key="v10", client="BNDA", site="BNDA-KLK1", form=INSTALLATION, sup="sup2",
        statut=Visit.Statut.SOUMISE, debut=14, soumission=13,
        responsable_absent=True,
    ),
    dict(
        key="v11", client="BNDA", site="BNDA-KLK2", form=AUDIT, sup="sup3",
        statut=Visit.Statut.SOUMISE, debut=11, soumission=10,
        nb_cameras=8, anomalies=False,
    ),
    dict(
        key="v12", client="BE", site="BE-SIKASSO", form=AUDIT, sup="sup4",
        statut=Visit.Statut.SOUMISE, debut=8, soumission=7,
        nb_cameras=6, anomalies=False,
    ),
    dict(
        key="v13", client="BNDA", site="BNDA-ACI", form=AUDIT, sup="sup1",
        statut=Visit.Statut.BROUILLON, debut=5,
        nb_cameras=3, anomalies=False,
    ),
    dict(
        key="v14", client="BNDA", site="BNDA-KAYES", form=INSTALLATION, sup="sup2",
        statut=Visit.Statut.BROUILLON, debut=2,
    ),
]


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_photo_jpeg(legende, site_nom, seed):
    rng = random.Random(seed)
    width, height = 1600, 1200
    color = tuple(rng.randint(40, 200) for _ in range(3))
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    draw.text((60, height // 2 - 70), legende, fill="white", font=_font(56))
    draw.text((60, height // 2 + 20), site_nom, fill="white", font=_font(40))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def make_signature_png(seed):
    rng = random.Random(seed)
    width, height = 320, 140
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    points = []
    x, y = 20, height // 2
    while x < width - 20:
        y = max(10, min(height - 10, y + rng.randint(-25, 25)))
        points.append((x, y))
        x += rng.randint(8, 18)
    draw.line(points, fill="black", width=3, joint="curve")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def make_signature_data_url(seed):
    png = make_signature_png(seed)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


class Command(BaseCommand):
    help = "Crée un jeu de données de démonstration (comptes, clients, sites, visites)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Efface entièrement le jeu de données de démonstration avant de le recréer.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            if options["reset"]:
                self._reset()

            users = self._ensure_users()
            self._ensure_forms()
            bnda, exemple = self._ensure_clients_and_sites()
            users.update(self._ensure_client_users(bnda, exemple))
            self._ensure_attached_forms(users, bnda, exemple)
            self._ensure_visits(users, bnda, exemple)

        self._print_summary(users)

    def _reset(self):
        demo_users = list(User.objects.filter(username__in=DEMO_USERNAMES))
        clients = Client.objects.filter(nom__in=["BNDA", "Banque Exemple"])

        ActivityLog.objects.filter(user__in=demo_users).delete()
        Visit.objects.filter(mission__site__client__in=clients).delete()
        Mission.objects.filter(site__client__in=clients).delete()
        AttachedForm.objects.filter(client__in=clients).delete()
        # Les comptes clients doivent disparaître avant leur Client (FK PROTECT).
        User.objects.filter(username__in=DEMO_USERNAMES).delete()
        Site.objects.filter(client__in=clients).delete()
        clients.delete()

    def _ensure_users(self):
        users = {}

        admin, _ = User.objects.update_or_create(
            username="admin",
            defaults={"is_superuser": True, "is_staff": True, "role": ""},
        )
        admin.set_password(DEMO_PASSWORD)
        admin.save()
        users["admin"] = admin

        manage_forms_perm = Permission.objects.get(codename="manage_forms")
        validate_visits_perm = Permission.objects.get(codename="validate_visits")

        manager1, _ = User.objects.update_or_create(
            username="manager1",
            defaults={"role": User.Role.MANAGER, "first_name": "Aïssata", "last_name": "Keïta"},
        )
        manager1.set_password(DEMO_PASSWORD)
        manager1.save()
        manager1.user_permissions.set([manage_forms_perm, validate_visits_perm])
        users["manager1"] = manager1

        manager2, _ = User.objects.update_or_create(
            username="manager2",
            defaults={"role": User.Role.MANAGER, "first_name": "Oumar", "last_name": "Sangaré"},
        )
        manager2.set_password(DEMO_PASSWORD)
        manager2.save()
        manager2.user_permissions.set([validate_visits_perm])
        users["manager2"] = manager2

        for username, first_name, last_name in SUPERVISEURS:
            sup, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "role": User.Role.SUPERVISEUR,
                    "first_name": first_name,
                    "last_name": last_name,
                },
            )
            sup.set_password(DEMO_PASSWORD)
            sup.save()
            users[username] = sup

        return users

    def _ensure_client_users(self, bnda, exemple):
        client_users = {}
        for username, client in [("client_bnda", bnda), ("client_exemple", exemple)]:
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={"role": User.Role.CLIENT, "client": client},
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            client_users[username] = user
        return client_users

    def _ensure_forms(self):
        existants = FormTemplate.objects.filter(nom__in=[INSTALLATION, AUDIT]).count()
        if existants < 2:
            call_command("seed_demo_forms")

    def _ensure_clients_and_sites(self):
        bnda, _ = Client.objects.get_or_create(nom="BNDA", defaults={"actif": True})
        exemple, _ = Client.objects.get_or_create(nom="Banque Exemple", defaults={"actif": True})

        for code, nom, ville, lat, lng in SITES_BNDA:
            Site.objects.update_or_create(
                client=bnda, code=code,
                defaults={"nom": nom, "ville": ville, "latitude": lat, "longitude": lng},
            )
        for code, nom, ville, lat, lng in SITES_BE:
            Site.objects.update_or_create(
                client=exemple, code=code,
                defaults={"nom": nom, "ville": ville, "latitude": lat, "longitude": lng},
            )

        return bnda, exemple

    def _ensure_attached_forms(self, users, bnda, exemple):
        manager1 = users["manager1"]
        templates = {t.nom: t for t in FormTemplate.objects.filter(nom__in=[INSTALLATION, AUDIT])}

        bnda_forms = {}
        for nom in (INSTALLATION, AUDIT):
            attached = AttachedForm.objects.filter(client=bnda, template=templates[nom]).first()
            if attached is None:
                attached = attach_template_to_client(manager1, bnda, templates[nom])
            bnda_forms[nom] = attached

        exemple_forms = {
            AUDIT: AttachedForm.objects.filter(client=exemple, template=templates[AUDIT]).first()
        }
        if exemple_forms[AUDIT] is None:
            exemple_forms[AUDIT] = attach_template_to_client(manager1, exemple, templates[AUDIT])

        for site in bnda.sites.all():
            for attached in bnda_forms.values():
                set_expected_visits(manager1, attached, site, 1)

        for site in exemple.sites.all():
            set_expected_visits(manager1, exemple_forms[AUDIT], site, 3)

        self._bnda_forms = bnda_forms
        self._exemple_forms = exemple_forms

    def _ensure_visits(self, users, bnda, exemple):
        sites_by_code = {s.code: s for s in Site.objects.filter(client__in=[bnda, exemple])}
        forms_by_client_and_name = {
            ("BNDA", nom): attached for nom, attached in self._bnda_forms.items()
        }
        forms_by_client_and_name.update(
            {("BE", nom): attached for nom, attached in self._exemple_forms.items()}
        )

        manager1 = users["manager1"]

        for spec in VISIT_SPECS:
            site = sites_by_code[spec["site"]]
            attached_form = forms_by_client_and_name[(spec["client"], spec["form"])]
            superviseur = users[spec["sup"]]

            mission, mission_created = Mission.objects.get_or_create(
                superviseur=superviseur,
                site=site,
                attached_form=attached_form,
                defaults={"created_by": manager1},
            )
            if mission_created:
                log(
                    manager1, "creation_mission", mission,
                    detail={"superviseur_id": superviseur.pk, "site_id": site.pk},
                )

            visit, visit_created = Visit.objects.get_or_create(
                mission=mission,
                defaults={"auteur": superviseur, "statut": Visit.Statut.BROUILLON},
            )
            if visit_created:
                self._fill_visit(spec, visit, site, superviseur, users)

    def _fill_visit(self, spec, visit, site, superviseur, users):
        now = timezone.now()
        debut = now - timezone.timedelta(days=spec["debut"], hours=9)
        soumission = (
            now - timezone.timedelta(days=spec["soumission"], hours=11)
            if "soumission" in spec else None
        )
        decision = (
            now - timezone.timedelta(days=spec["decision"], hours=15)
            if "decision" in spec else None
        )

        nom_technicien = f"{superviseur.first_name} {superviseur.last_name}"
        is_draft = spec["statut"] == Visit.Statut.BROUILLON

        if spec["form"] == AUDIT:
            reponses = self._build_audit_reponses(spec, nom_technicien, debut, is_draft)
        else:
            reponses = self._build_installation_reponses(spec, nom_technicien, site, debut, is_draft)

        visit.statut = spec["statut"]
        visit.reponses = reponses
        visit.date_debut = debut
        visit.responsable_absent = spec.get("responsable_absent", False)
        if visit.responsable_absent:
            visit.motif_absence_responsable = "Responsable de site en congé."

        if not is_draft:
            visit.date_soumission = soumission
            jitter = random.Random(spec["key"]).uniform(-0.01, 0.01)
            visit.gps_latitude = f"{float(site.latitude) + jitter:.6f}"
            visit.gps_longitude = f"{float(site.longitude) + jitter:.6f}"
            visit.signature_superviseur = ContentFile(
                make_signature_png(spec["key"] + "-sup"), name="signature_superviseur.png"
            )
            if not visit.responsable_absent:
                visit.signature_responsable = ContentFile(
                    make_signature_png(spec["key"] + "-resp"), name="signature_responsable.png"
                )

        validateur = users.get(spec["validateur"]) if spec.get("validateur") else None
        if validateur is not None:
            visit.decision_par = validateur
            visit.decision_le = decision
            visit.commentaire_rejet = spec.get("commentaire_rejet", "")

        visit.save()

        if not is_draft:
            self._create_photos(spec, visit, site)

        self._write_logs(spec, visit, superviseur, validateur, debut, soumission, decision)

    def _build_audit_reponses(self, spec, nom_technicien, debut, is_draft):
        nb_cameras = spec.get("nb_cameras", 0)
        rng = random.Random(spec["key"])
        cameras = []
        for i in range(nb_cameras):
            marque = rng.choice(CAMERA_MARQUES)
            cameras.append(
                {
                    "_index": str(i),
                    "marque": marque,
                    "modele": f"{marque[:2].upper()}-{rng.randint(1000, 9999)}",
                    "serie": f"SN{rng.randint(100000, 999999)}",
                    "etat": rng.choice(CAMERA_ETATS),
                }
            )
        reponses = {
            "nom_technicien": nom_technicien,
            "date_audit": debut.date().isoformat(),
            "nombre_cameras": str(nb_cameras),
            "cameras": cameras,
            "enregistreur": "Enregistreur NVR 16 voies",
            "anomalies": "Câblage extérieur endommagé par les intempéries." if spec.get("anomalies") else "",
            "observation": "" if is_draft else "Visite effectuée sans incident notable.",
        }
        if not is_draft:
            reponses["signature"] = make_signature_data_url(spec["key"] + "-schema")
        return reponses

    def _build_installation_reponses(self, spec, nom_technicien, site, debut, is_draft):
        rng = random.Random(spec["key"])
        jitter = rng.uniform(-0.01, 0.01)
        reponses = {
            "nom_technicien": nom_technicien,
            "date_intervention": debut.date().isoformat(),
            "position_gps": {
                "lat": f"{float(site.latitude) + jitter:.6f}",
                "lng": f"{float(site.longitude) + jitter:.6f}",
            },
            "observations": "" if is_draft else "Installation posée et testée, accès au site facile.",
        }
        if not is_draft:
            reponses["signature"] = make_signature_data_url(spec["key"] + "-schema")
        return reponses

    def _create_photos(self, spec, visit, site):
        if spec["form"] == AUDIT:
            nb_cameras = spec.get("nb_cameras", 0)
            for i in range(nb_cameras):
                field_key = repeat_row_name("cameras", str(i), "photo_camera")
                nb_photos = 1 if i % 3 else 2
                for p in range(nb_photos):
                    self._attach_photo(visit, field_key, f"Photo caméra {i + 1}", site, f"{spec['key']}-cam{i}-{p}")
        else:
            for field_key, legende in [
                ("photo_facade", "Photo façade"),
                ("photo_installation", "Photo installation"),
                ("photo_compteur", "Photo compteur"),
                ("photo_cablage", "Photo câblage"),
            ]:
                self._attach_photo(visit, field_key, legende, site, f"{spec['key']}-{field_key}")

    def _attach_photo(self, visit, field_key, legende, site, seed):
        content = make_photo_jpeg(legende, site.nom, seed)
        VisitPhoto.objects.create(
            visit=visit,
            field_key=field_key,
            legende=legende,
            image=ContentFile(content, name=f"{field_key}.jpg"),
        )

    def _write_logs(self, spec, visit, superviseur, validateur, debut, soumission, decision):
        self._log_at(superviseur, "debut_visite", visit, debut, {"mission_id": visit.mission_id})

        statut = spec["statut"]
        if statut == Visit.Statut.BROUILLON:
            return

        self._log_at(
            superviseur, "soumission_visite", visit, soumission, {"mission_id": visit.mission_id}
        )

        if statut == Visit.Statut.A_CORRIGER:
            self._log_at(
                validateur, "rejet_visite", visit, decision,
                {"mission_id": visit.mission_id, "commentaire": spec.get("commentaire_rejet", "")},
            )
            return

        if statut == Visit.Statut.SOUMISE:
            return

        self._log_at(validateur, "validation_visite", visit, decision, {"mission_id": visit.mission_id})

        if statut in (Visit.Statut.PUBLIEE, Visit.Statut.DEPUBLIEE):
            publication = decision + timezone.timedelta(hours=2)
            self._log_at(
                validateur, "publication_visite", visit, publication, {"mission_id": visit.mission_id}
            )

        if statut == Visit.Statut.DEPUBLIEE:
            depublication = decision + timezone.timedelta(hours=4)
            self._log_at(
                validateur, "depublication_visite", visit, depublication, {"mission_id": visit.mission_id}
            )

    def _log_at(self, user, action, obj, when, detail):
        entry = log(user, action, obj, detail=detail)
        ActivityLog.objects.filter(pk=entry.pk).update(created_at=when)

    def _print_summary(self, users):
        self.stdout.write(self.style.SUCCESS("Jeu de données de démonstration prêt."))
        self.stdout.write(f"Mot de passe commun : {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write("Comptes :")
        self.stdout.write("  admin             — administrateur (superuser)")
        self.stdout.write("  manager1          — manager (manage_forms, validate_visits)")
        self.stdout.write("  manager2          — manager (validate_visits)")
        for username, first_name, last_name in SUPERVISEURS:
            self.stdout.write(f"  {username:<17} — superviseur ({first_name} {last_name})")
        self.stdout.write("  client_bnda       — client (BNDA)")
        self.stdout.write("  client_exemple    — client (Banque Exemple)")
