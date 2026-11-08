import os
from io import BytesIO
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import User
from clients.models import Client
from core.context_processors import navigation
from core.images import optimiser_image_png
from core.models import ActivityLog
from core.testing import TempMediaRootMixin

from . import services
from .forms import ProfilEmetteurForm
from .models import ContactClient, ProfilEmetteur


def _image(fmt="PNG", mode="RGBA", taille=(40, 30), couleur=(200, 0, 0, 120)):
    buf = BytesIO()
    if mode == "RGB" and len(couleur) == 4:
        couleur = couleur[:3]
    Image.new(mode, taille, couleur).save(buf, fmt)
    return buf.getvalue()


def _utilisateur_facturation(username="factu", role=User.Role.MANAGER):
    user = User.objects.create_user(username=username, password="x", role=role)
    user.user_permissions.add(Permission.objects.get(codename="manage_invoices"))
    return user


class AccesTests(TempMediaRootMixin, TestCase):
    """Chaque vue refuse l'accès sans la permission facturation.manage_invoices."""

    @classmethod
    def setUpTestData(cls):
        cls.contact = ContactClient.objects.create(nom="Contact test")
        cls.autorise = _utilisateur_facturation()
        cls.manager = User.objects.create_user(username="mgr", password="x", role=User.Role.MANAGER)
        cls.manager.user_permissions.add(
            Permission.objects.get(codename="validate_visits"),
            Permission.objects.get(codename="manage_forms"),
        )
        cls.auditeur = User.objects.create_user(username="aud", password="x", role=User.Role.SUPERVISEUR)
        client = Client.objects.create(nom="Client portail")
        cls.client_user = User.objects.create_user(
            username="cli", password="x", role=User.Role.CLIENT, client=client
        )

    def _urls_get(self):
        return [
            reverse("facturation:contact-list"),
            reverse("facturation:contact-create"),
            reverse("facturation:contact-update", args=[self.contact.pk]),
            reverse("facturation:profil"),
        ]

    def _urls_post(self):
        return [
            reverse("facturation:contact-create"),
            reverse("facturation:contact-update", args=[self.contact.pk]),
            reverse("facturation:contact-deactivate", args=[self.contact.pk]),
            reverse("facturation:contact-reactivate", args=[self.contact.pk]),
            reverse("facturation:profil"),
        ]

    def test_anonyme_redirige_vers_la_connexion(self):
        for url in self._urls_get() + [reverse("facturation:profil-image", args=["logo"])]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_sans_permission_403_pour_chaque_vue(self):
        for user in (self.manager, self.auditeur, self.client_user):
            self.client.force_login(user)
            for url in self._urls_get() + [reverse("facturation:profil-image", args=["logo"])]:
                with self.subTest(user=user.username, methode="GET", url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            for url in self._urls_post():
                with self.subTest(user=user.username, methode="POST", url=url):
                    self.assertEqual(self.client.post(url, {"nom": "Pirate"}).status_code, 403)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.nom, "Contact test")
        self.assertTrue(self.contact.actif)
        self.assertFalse(ContactClient.objects.filter(nom="Pirate").exists())

    def test_avec_permission_les_pages_repondent(self):
        self.client.force_login(self.autorise)
        for url in self._urls_get():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_superuser_accede_sans_permission_explicite(self):
        admin = User.objects.create_superuser(username="root", password="x")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("facturation:contact-list")).status_code, 200)

    def test_desactivation_refuse_le_get(self):
        self.client.force_login(self.autorise)
        url = reverse("facturation:contact-deactivate", args=[self.contact.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_menu_facturation_visible_uniquement_avec_la_permission(self):
        factory = RequestFactory()

        def labels(user):
            request = factory.get(reverse("facturation:contact-list"))
            request.user = user
            return {item["label"]: item for item in navigation(request)["nav_items"]}

        self.assertNotIn("Facturation", labels(self.manager))
        self.assertNotIn("Facturation", labels(self.auditeur))
        self.assertNotIn("Facturation", labels(self.client_user))
        item = labels(self.autorise)["Facturation"]
        self.assertEqual(item["url"], reverse("facturation:document-list"))
        self.assertTrue(item["is_active"])

    def test_menu_facturation_suit_la_permission_quel_que_soit_le_role(self):
        factory = RequestFactory()
        auditeur = _utilisateur_facturation("aud_factu", role=User.Role.SUPERVISEUR)
        request = factory.get("/app/missions/")
        request.user = User.objects.get(pk=auditeur.pk)  # cache de permissions vierge
        labels = [item["label"] for item in navigation(request)["nav_items"]]
        self.assertEqual(labels, ["Mes missions", "Mes visites", "Facturation"])


class ProfilEmetteurSingletonTests(TestCase):
    def test_get_cree_le_profil_avec_les_valeurs_par_defaut(self):
        self.assertFalse(ProfilEmetteur.objects.exists())
        profil = ProfilEmetteur.get()
        self.assertEqual(ProfilEmetteur.objects.count(), 1)
        self.assertEqual(profil.taux_tva_defaut, 18)
        self.assertEqual(profil.validite_devis_jours, 30)
        self.assertEqual(profil.delai_relance_jours, 7)

    def test_get_retourne_toujours_le_meme_profil(self):
        premier = ProfilEmetteur.get()
        premier.raison_sociale = "EGM Tech"
        premier.save()
        second = ProfilEmetteur.get()
        self.assertEqual(second.pk, premier.pk)
        self.assertEqual(second.raison_sociale, "EGM Tech")
        self.assertEqual(ProfilEmetteur.objects.count(), 1)

    def test_impossible_de_creer_un_second_profil(self):
        ProfilEmetteur.get()
        with self.assertRaises(ValidationError):
            ProfilEmetteur.objects.create(raison_sociale="Doublon")
        self.assertEqual(ProfilEmetteur.objects.count(), 1)

    def test_la_base_refuse_un_second_profil(self):
        ProfilEmetteur.get()
        # bulk_create contourne save() : c'est la contrainte d'unicité qui doit tenir.
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfilEmetteur.objects.bulk_create([ProfilEmetteur(raison_sociale="Doublon")])
        self.assertEqual(ProfilEmetteur.objects.count(), 1)

    def test_impossible_de_supprimer_le_profil(self):
        profil = ProfilEmetteur.get()
        with self.assertRaises(ValidationError):
            profil.delete()
        with self.assertRaises(ValidationError):
            ProfilEmetteur.objects.all().delete()
        self.assertEqual(ProfilEmetteur.objects.count(), 1)


class ProfilEmetteurValidationTests(TestCase):
    CHAMPS = {
        "taux_tva_defaut": (0, 100),
        "validite_devis_jours": (1, 365),
        "delai_relance_jours": (1, 90),
    }

    def _form(self, **valeurs):
        data = {"taux_tva_defaut": 18, "validite_devis_jours": 30, "delai_relance_jours": 7}
        data.update(valeurs)
        return ProfilEmetteurForm(data, instance=ProfilEmetteur.get())

    def test_valeurs_par_defaut_valides(self):
        self.assertTrue(self._form().is_valid())

    def test_bornes_acceptees(self):
        for champ, (mini, maxi) in self.CHAMPS.items():
            for valeur in (mini, maxi):
                with self.subTest(champ=champ, valeur=valeur):
                    form = self._form(**{champ: valeur})
                    self.assertTrue(form.is_valid(), form.errors)

    def test_valeurs_hors_bornes_refusees(self):
        for champ, (mini, maxi) in self.CHAMPS.items():
            for valeur in (mini - 1, -1, maxi + 1, "", "abc", "2.5"):
                with self.subTest(champ=champ, valeur=valeur):
                    form = self._form(**{champ: valeur})
                    self.assertFalse(form.is_valid())
                    self.assertIn(champ, form.errors)

    def test_la_base_refuse_un_nombre_hors_bornes(self):
        ProfilEmetteur.get()
        # Au-dessus du maximum : un négatif lèverait DataError sur MariaDB (colonne non signée).
        for champ, (_, maxi) in self.CHAMPS.items():
            with self.subTest(champ=champ):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    ProfilEmetteur.objects.update(**{champ: maxi + 1})

    def test_taux_zero_accepte_c_est_une_exoneration(self):
        form = self._form(taux_tva_defaut=0)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(ProfilEmetteur.get().taux_tva_defaut, 0)

    def test_la_base_refuse_un_delai_nul(self):
        ProfilEmetteur.get()
        for champ in ("validite_devis_jours", "delai_relance_jours"):
            with self.subTest(champ=champ):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    ProfilEmetteur.objects.update(**{champ: 0})

    def test_modification_par_la_page_et_journal(self):
        user = _utilisateur_facturation()
        self.client.force_login(user)
        response = self.client.post(reverse("facturation:profil"), {
            "raison_sociale": "EGM Tech", "taux_tva_defaut": 18,
            "validite_devis_jours": 45, "delai_relance_jours": 10,
        })
        self.assertRedirects(response, reverse("facturation:profil"))
        profil = ProfilEmetteur.get()
        self.assertEqual(profil.raison_sociale, "EGM Tech")
        self.assertEqual(profil.validite_devis_jours, 45)
        entree = ActivityLog.objects.get(action="modification_profil_emetteur")
        self.assertEqual(entree.user, user)
        self.assertIn("validite_devis_jours", entree.detail["champs"])

    def test_page_affiche_les_erreurs_sans_enregistrer(self):
        self.client.force_login(_utilisateur_facturation())
        response = self.client.post(reverse("facturation:profil"), {
            "taux_tva_defaut": 101, "validite_devis_jours": 30, "delai_relance_jours": 7,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("taux_tva_defaut", response.context["form"].errors)
        self.assertEqual(ProfilEmetteur.get().taux_tva_defaut, 18)
        self.assertFalse(ActivityLog.objects.filter(action="modification_profil_emetteur").exists())


class ContactClientTests(TestCase):
    def setUp(self):
        self.user = _utilisateur_facturation()
        self.client.force_login(self.user)

    def test_creation(self):
        response = self.client.post(reverse("facturation:contact-create"), {
            "nom": "Societe Alpha", "telephone": "+223 76 12 34 56", "email": "alpha@example.com",
            "adresse": "Bamako", "notes": "Paie a 30 jours",
        })
        self.assertRedirects(response, reverse("facturation:contact-list"))
        contact = ContactClient.objects.get(nom="Societe Alpha")
        self.assertTrue(contact.actif)
        self.assertIsNotNone(contact.created_at)
        self.assertEqual(contact.telephone, "+223 76 12 34 56")
        self.assertTrue(ActivityLog.objects.filter(
            action="creation_contact_facturation", object_id=str(contact.pk), user=self.user
        ).exists())

    def test_creation_sans_nom_refusee(self):
        response = self.client.post(reverse("facturation:contact-create"), {"nom": "", "email": "pas-un-email"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("nom", response.context["form"].errors)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(ContactClient.objects.exists())

    def test_modification(self):
        contact = ContactClient.objects.create(nom="Beta")
        response = self.client.post(
            reverse("facturation:contact-update", args=[contact.pk]), {"nom": "Beta SARL", "telephone": "70000000"}
        )
        self.assertRedirects(response, reverse("facturation:contact-list"))
        contact.refresh_from_db()
        self.assertEqual(contact.nom, "Beta SARL")
        self.assertTrue(ActivityLog.objects.filter(action="modification_contact_facturation").exists())

    def test_recherche_par_nom_ou_telephone(self):
        alpha = ContactClient.objects.create(nom="Societe Alpha", telephone="76 11 22 33")
        beta = ContactClient.objects.create(nom="Beta Services", telephone="66 99 88 77")
        url = reverse("facturation:contact-list")

        def resultats(**params):
            return list(self.client.get(url, params).context["contacts"])

        self.assertEqual(resultats(), [beta, alpha])
        self.assertEqual(resultats(q="alpha"), [alpha])
        self.assertEqual(resultats(q="ALPHA"), [alpha])
        self.assertEqual(resultats(q="99 88"), [beta])
        self.assertEqual(resultats(q="  beta  "), [beta])
        self.assertEqual(resultats(q="introuvable"), [])

    def test_recherche_telephone_ignore_espaces_points_et_tirets(self):
        espaces = ContactClient.objects.create(nom="Espaces", telephone="76 12 34 56")
        mixte = ContactClient.objects.create(nom="Mixte", telephone="+223 66.12-34 56")
        autre = ContactClient.objects.create(nom="Autre", telephone="70 00 00 00")
        url = reverse("facturation:contact-list")

        def resultats(q):
            return set(self.client.get(url, {"q": q}).context["contacts"])

        self.assertEqual(resultats("76123456"), {espaces})
        self.assertEqual(resultats("76.12-34 56"), {espaces})
        self.assertEqual(resultats("12-34"), {espaces, mixte})
        self.assertEqual(resultats("6612"), {mixte})
        self.assertEqual(resultats("+22366"), {mixte})
        self.assertNotIn(autre, resultats("1234"))
        # Une recherche faite seulement de séparateurs ne filtre pas sur le téléphone.
        self.assertEqual(resultats(" - "), set())

    def test_desactivation_sans_suppression(self):
        contact = ContactClient.objects.create(nom="Gamma", telephone="65000000")
        response = self.client.post(reverse("facturation:contact-deactivate", args=[contact.pk]))
        self.assertRedirects(response, reverse("facturation:contact-list"))
        contact.refresh_from_db()
        self.assertFalse(contact.actif)
        self.assertTrue(ActivityLog.objects.filter(
            action="desactivation_contact_facturation", object_id=str(contact.pk)
        ).exists())

        url = reverse("facturation:contact-list")
        self.assertNotIn(contact, self.client.get(url).context["contacts"])
        self.assertNotIn(contact, self.client.get(url, {"q": "Gamma"}).context["contacts"])
        self.assertIn(contact, self.client.get(url, {"q": "Gamma", "inactifs": "1"}).context["contacts"])

    def test_desactiver_deux_fois_ne_journalise_qu_une_fois(self):
        contact = ContactClient.objects.create(nom="Delta")
        url = reverse("facturation:contact-deactivate", args=[contact.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(ActivityLog.objects.filter(action="desactivation_contact_facturation").count(), 1)

    def test_reactivation(self):
        contact = ContactClient.objects.create(nom="Epsilon", actif=False)
        self.client.post(reverse("facturation:contact-reactivate", args=[contact.pk]))
        contact.refresh_from_db()
        self.assertTrue(contact.actif)

    def test_contact_inconnu_404(self):
        self.assertEqual(self.client.get(reverse("facturation:contact-update", args=[999999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("facturation:contact-deactivate", args=[999999])).status_code, 404)


class ProfilImagesTests(TempMediaRootMixin, TestCase):
    def setUp(self):
        self.user = _utilisateur_facturation()
        self.client.force_login(self.user)
        self.url = reverse("facturation:profil")

    def _envoyer(self, **fichiers):
        data = {"taux_tva_defaut": 18, "validite_devis_jours": 30, "delai_relance_jours": 7}
        data.update(fichiers)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data)

    def _chemin(self, fichier):
        return os.path.join(self.media_root, fichier.name)

    def test_logo_converti_en_png_avec_transparence_dans_le_media_temporaire(self):
        response = self._envoyer(logo=SimpleUploadedFile("logo.png", _image(), content_type="image/png"))
        self.assertRedirects(response, self.url)
        profil = ProfilEmetteur.get()
        self.assertTrue(profil.logo.name.startswith("facturation/profil/"))
        self.assertTrue(profil.logo.name.endswith(".png"))
        self.assertTrue(os.path.isfile(self._chemin(profil.logo)))
        with Image.open(self._chemin(profil.logo)) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.mode, "RGBA")
        page = self.client.get(self.url)
        self.assertContains(page, reverse("facturation:profil-image", args=["logo"]))
        self.assertNotContains(page, profil.logo.name)

    def test_cachet_jpeg_accepte(self):
        jpeg = _image(fmt="JPEG", mode="RGB")
        self._envoyer(cachet=SimpleUploadedFile("cachet.jpg", jpeg, content_type="image/jpeg"))
        profil = ProfilEmetteur.get()
        with Image.open(self._chemin(profil.cachet)) as img:
            self.assertEqual((img.format, img.mode), ("PNG", "RGB"))

    def test_fichier_qui_n_est_pas_une_image_refuse(self):
        response = self._envoyer(logo=SimpleUploadedFile("logo.png", b"pas une image", content_type="image/png"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("logo", response.context["form"].errors)
        self.assertFalse(ProfilEmetteur.get().logo)

    def test_image_trop_lourde_refusee(self):
        with mock.patch.object(services, "IMAGE_PROFIL_MAX_BYTES", 10):
            response = self._envoyer(logo=SimpleUploadedFile("logo.png", _image(), content_type="image/png"))
        self.assertIn("logo", response.context["form"].errors)
        self.assertFalse(ProfilEmetteur.get().logo)

    def test_remplacement_supprime_l_ancien_fichier(self):
        self._envoyer(logo=SimpleUploadedFile("a.png", _image(), content_type="image/png"))
        ancien = self._chemin(ProfilEmetteur.get().logo)
        self._envoyer(logo=SimpleUploadedFile("b.png", _image(couleur=(0, 0, 255, 255)), content_type="image/png"))
        nouveau = self._chemin(ProfilEmetteur.get().logo)
        self.assertNotEqual(ancien, nouveau)
        self.assertFalse(os.path.exists(ancien))
        self.assertTrue(os.path.isfile(nouveau))

    def test_retirer_le_logo(self):
        self._envoyer(logo=SimpleUploadedFile("a.png", _image(), content_type="image/png"))
        chemin = self._chemin(ProfilEmetteur.get().logo)
        self._envoyer(retirer_logo="on")
        self.assertFalse(ProfilEmetteur.get().logo)
        self.assertFalse(os.path.exists(chemin))

    def test_envoyer_et_retirer_en_meme_temps_refuse(self):
        response = self._envoyer(
            logo=SimpleUploadedFile("a.png", _image(), content_type="image/png"), retirer_logo="on"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("retirer_logo", response.context["form"].errors)

    def test_apercu_protege_par_la_permission(self):
        self._envoyer(logo=SimpleUploadedFile("a.png", _image(), content_type="image/png"))
        url = reverse("facturation:profil-image", args=["logo"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))

        sans_droit = User.objects.create_user(username="mgr2", password="x", role=User.Role.MANAGER)
        self.client.force_login(sans_droit)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_logo_inaccessible_par_l_url_des_medias(self):
        self._envoyer(logo=SimpleUploadedFile("a.png", _image(), content_type="image/png"))
        nom = ProfilEmetteur.get().logo.name
        admin = User.objects.create_superuser(username="root", password="x")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("private-media", args=[nom])).status_code, 404)

    def test_apercu_absent_ou_champ_inconnu_404(self):
        self.assertEqual(self.client.get(reverse("facturation:profil-image", args=["cachet"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("facturation:profil-image", args=["autre"])).status_code, 404)


class OptimiserImagePngTests(TestCase):
    def test_reduit_et_garde_la_transparence(self):
        fichier = BytesIO(_image(taille=(3000, 1500)))
        resultat = optimiser_image_png(fichier, 600)
        with Image.open(BytesIO(resultat.read())) as img:
            self.assertEqual(img.size, (600, 300))
            self.assertEqual(img.mode, "RGBA")

    def test_fichier_invalide(self):
        with self.assertRaises(ValueError):
            optimiser_image_png(BytesIO(b"\x89PNG tronque"), 600)
