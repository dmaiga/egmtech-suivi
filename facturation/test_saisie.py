"""Interface de saisie : produits, liste des documents, création et édition d'un brouillon (lot 3a)."""

import re
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from clients.models import Client

from . import services
from .exceptions import ErreurFacturation, MontantInvalide
from .models import (
    LIGNES_MAX,
    PRIX_UNITAIRE_MAX,
    QUANTITE_MAX,
    TAUX_TVA_MAX,
    ContactClient,
    Document,
    LigneDocument,
    Produit,
    ProfilEmetteur,
)
from .templatetags.facturation_format import date_fr, fcfa

T = Document.Type
S = Document.Statut
LIGNES = [
    {"designation": "Caméra dôme", "quantite": 2, "prix_unitaire": 125_000},
    {"designation": "Pose", "quantite": 1, "prix_unitaire": 150_000},
]
HX = {"HTTP_HX_REQUEST": "true"}

# Requêtes SQL d'une page, mesurées pour un manager ayant la seule permission manage_invoices
# (session, utilisateur, permissions, page). Elles ne dépendent pas du nombre de lignes affichées.
NB_REQUETES_LISTE = 6
NB_REQUETES_EDITION = 8


def _utilisateur(username="factu", role=User.Role.MANAGER, permission=True):
    user = User.objects.create_user(username=username, password="x", role=role)
    if permission:
        user.user_permissions.add(Permission.objects.get(codename="manage_invoices"))
    return user


def _total(response, identifiant):
    """Texte d'un total du fragment (#total-ht, #total-tva, #total-ttc)."""
    trouve = re.search(rf'id="{identifiant}"[^>]*>([^<]*)<', response.content.decode())
    return trouve.group(1) if trouve else None


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class BaseSaisie(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _utilisateur()
        cls.contact = ContactClient.objects.create(nom="Societe Alpha", telephone="76 12 34 56")

    def setUp(self):
        self.client.force_login(self.user)

    def brouillon(self, type_document=T.DEVIS, lignes=LIGNES, **kwargs):
        return services.creer_brouillon(type_document, self.contact, self.user, lignes=lignes, **kwargs)

    def emis(self, type_document=T.FACTURE):
        return services.emettre(self.brouillon(type_document), self.user)


# ---------------------------------------------------------------------------
# Accès
# ---------------------------------------------------------------------------

class AccesSaisieTests(BaseSaisie):
    def _urls(self):
        doc = self.brouillon()
        ligne = doc.lignes.first()
        produit = Produit.objects.create(designation="Câble", prix_unitaire=500)
        get = [
            reverse("facturation:document-list"),
            reverse("facturation:document-create", args=["devis"]),
            reverse("facturation:document-create", args=["facture"]),
            reverse("facturation:document-edit", args=[doc.pk]),
            reverse("facturation:document-delete", args=[doc.pk]),
            reverse("facturation:produit-list"),
            reverse("facturation:produit-create"),
            reverse("facturation:produit-update", args=[produit.pk]),
        ]
        post = get + [
            reverse("facturation:ligne-add", args=[doc.pk]),
            reverse("facturation:ligne-add-produit", args=[doc.pk]),
            reverse("facturation:ligne-update", args=[doc.pk, ligne.pk]),
            reverse("facturation:ligne-delete", args=[doc.pk, ligne.pk]),
            reverse("facturation:produit-deactivate", args=[produit.pk]),
            reverse("facturation:produit-reactivate", args=[produit.pk]),
        ]
        return doc, get, post

    def test_sans_permission_403_partout_et_rien_ne_change(self):
        doc, get, post = self._urls()
        client_portail = Client.objects.create(nom="Portail")
        refuses = [
            _utilisateur("mgr_sans", permission=False),
            _utilisateur("aud_sans", role=User.Role.SUPERVISEUR, permission=False),
            User.objects.create_user(username="cli", password="x", role=User.Role.CLIENT, client=client_portail),
        ]
        for user in refuses:
            self.client.force_login(user)
            for url in get:
                with self.subTest(user=user.username, methode="GET", url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            for url in post:
                with self.subTest(user=user.username, methode="POST", url=url):
                    self.assertEqual(self.client.post(url, {"nouvelle-designation": "X"}).status_code, 403)
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())
        self.assertEqual(doc.lignes.count(), 2)
        self.assertTrue(Produit.objects.get().actif)

    def test_anonyme_redirige(self):
        _, get, _ = self._urls()
        self.client.logout()
        for url in get:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_pages_accessibles_avec_la_permission(self):
        _, get, _ = self._urls()
        for url in get:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_get_refuse_sur_les_actions_en_post(self):
        doc, _, post = self._urls()
        actions = [u for u in post if "/lignes/" in u or "activer" in u]
        self.assertEqual(len(actions), 6)
        for url in actions:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_type_de_document_inconnu_404(self):
        self.assertEqual(self.client.get(reverse("facturation:document-create", args=["avoir"])).status_code, 404)


# ---------------------------------------------------------------------------
# Produits
# ---------------------------------------------------------------------------

class ProduitsVuesTests(BaseSaisie):
    def test_creation_avec_separateurs_de_milliers(self):
        response = self.client.post(reverse("facturation:produit-create"), {"designation": "Caméra", "prix_unitaire": "1 250 000"})
        self.assertRedirects(response, reverse("facturation:produit-list"))
        produit = Produit.objects.get()
        self.assertEqual((produit.designation, produit.prix_unitaire, produit.actif), ("Caméra", 1_250_000, True))

    def test_prix_invalides_message_clair(self):
        cas = {
            "1002": "multiple de 5",
            "0": "compris entre 5",
            "-5": "compris entre 5",
            "12.5": "nombre entier",
            "abc": "nombre entier",
            str(PRIX_UNITAIRE_MAX + 5): "compris entre 5",
        }
        for saisie, attendu in cas.items():
            with self.subTest(saisie=saisie):
                response = self.client.post(reverse("facturation:produit-create"), {"designation": "X", "prix_unitaire": saisie})
                self.assertEqual(response.status_code, 200)
                erreurs = " ".join(response.context["form"].errors["prix_unitaire"])
                self.assertIn(attendu, erreurs.lower())
        self.assertFalse(Produit.objects.exists())

    def test_modification(self):
        produit = Produit.objects.create(designation="Câble", prix_unitaire=500)
        response = self.client.post(reverse("facturation:produit-update", args=[produit.pk]), {"designation": "Câble RJ45", "prix_unitaire": "750"})
        self.assertRedirects(response, reverse("facturation:produit-list"))
        produit.refresh_from_db()
        self.assertEqual((produit.designation, produit.prix_unitaire), ("Câble RJ45", 750))

    def test_desactivation_puis_reactivation_jamais_de_suppression(self):
        produit = Produit.objects.create(designation="Câble", prix_unitaire=500)
        self.client.post(reverse("facturation:produit-deactivate", args=[produit.pk]))
        produit.refresh_from_db()
        self.assertFalse(produit.actif)
        liste = reverse("facturation:produit-list")
        self.assertNotIn(produit, self.client.get(liste).context["produits"])
        self.assertIn(produit, self.client.get(liste, {"inactifs": "1"}).context["produits"])
        self.client.post(reverse("facturation:produit-reactivate", args=[produit.pk]))
        produit.refresh_from_db()
        self.assertTrue(produit.actif)

    def test_recherche_sur_la_designation(self):
        camera = Produit.objects.create(designation="Caméra dôme", prix_unitaire=5)
        Produit.objects.create(designation="Câble", prix_unitaire=5)
        resultats = list(self.client.get(reverse("facturation:produit-list"), {"q": "dôme"}).context["produits"])
        self.assertEqual(resultats, [camera])


# ---------------------------------------------------------------------------
# Liste et création
# ---------------------------------------------------------------------------

class ListeDocumentsTests(BaseSaisie):
    def test_du_plus_recent_au_plus_ancien_avec_numero_ou_brouillon(self):
        ancien = self.emis(T.DEVIS)
        recent = self.brouillon(T.FACTURE)
        response = self.client.get(reverse("facturation:document-list"))
        self.assertEqual(list(response.context["documents"]), [recent, ancien])
        self.assertContains(response, ancien.numero)
        self.assertContains(response, "Brouillon")
        self.assertContains(response, fcfa(ancien.total_ttc))

    def test_nombre_de_requetes_constant(self):
        url = reverse("facturation:document-list")
        self.brouillon()
        self.client.get(url)  # premières requêtes de session hors mesure
        with self.assertNumQueries(NB_REQUETES_LISTE):
            self.client.get(url)
        for _ in range(25):
            self.brouillon()
        with self.assertNumQueries(NB_REQUETES_LISTE):
            response = self.client.get(url)
        self.assertEqual(len(response.context["documents"]), 20)  # pagination

    def test_champs_libres_echappes(self):
        self.brouillon(objet="<script>alert(1)</script>")
        response = self.client.get(reverse("facturation:document-list"))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")


class CreationDocumentTests(BaseSaisie):
    def test_taux_et_validite_preremplis_depuis_le_profil(self):
        profil = ProfilEmetteur.get()
        profil.taux_tva_defaut, profil.validite_devis_jours = 12, 45
        profil.save()
        form = self.client.get(reverse("facturation:document-create", args=["devis"])).context["form"]
        self.assertEqual((form.initial["taux_tva"], form.initial["validite_jours"]), (12, 45))
        facture = self.client.get(reverse("facturation:document-create", args=["facture"])).context["form"]
        self.assertNotIn("validite_jours", facture.fields)

    def test_creation_puis_redirection_vers_l_edition(self):
        response = self.client.post(reverse("facturation:document-create", args=["devis"]), {
            "contact": self.contact.pk, "objet": "Vidéosurveillance", "lieu_livraison": "ACI 2000",
            "taux_tva": "18", "validite_jours": "30",
        })
        doc = Document.objects.get()
        self.assertRedirects(response, reverse("facturation:document-edit", args=[doc.pk]))
        self.assertEqual((doc.type, doc.statut, doc.objet, doc.cree_par), (T.DEVIS, S.BROUILLON, "Vidéosurveillance", self.user))
        self.assertEqual(list(doc.historique.values_list("nouveau_statut", flat=True)), [S.BROUILLON])

    def test_taux_zero_saisi_volontairement(self):
        self.client.post(reverse("facturation:document-create", args=["facture"]), {"contact": self.contact.pk, "taux_tva": "0"})
        doc = Document.objects.get()
        self.assertEqual((doc.type, doc.taux_tva, doc.validite_jours), (T.FACTURE, 0, None))

    def test_taux_obligatoire_et_borne(self):
        for taux in ("", "101", "-1", "abc"):
            with self.subTest(taux=taux):
                response = self.client.post(reverse("facturation:document-create", args=["facture"]), {"contact": self.contact.pk, "taux_tva": taux})
                self.assertEqual(response.status_code, 200)
                self.assertIn("taux_tva", response.context["form"].errors)
        self.assertFalse(Document.objects.exists())

    def test_contact_inactif_non_propose_et_refuse(self):
        inactif = ContactClient.objects.create(nom="Ancien client", actif=False)
        response = self.client.get(reverse("facturation:document-create", args=["devis"]))
        self.assertNotIn(inactif, response.context["form"].fields["contact"].queryset)
        self.assertContains(response, reverse("facturation:contact-create"))
        response = self.client.post(reverse("facturation:document-create", args=["devis"]), {
            "contact": inactif.pk, "taux_tva": "18", "validite_jours": "30",
        })
        self.assertIn("contact", response.context["form"].errors)
        self.assertFalse(Document.objects.exists())


# ---------------------------------------------------------------------------
# Édition d'un brouillon
# ---------------------------------------------------------------------------

class EditionEnteteTests(BaseSaisie):
    def test_modification_de_l_en_tete_et_recalcul(self):
        doc = self.brouillon()
        response = self.client.post(reverse("facturation:document-edit", args=[doc.pk]), {
            "contact": self.contact.pk, "objet": "Nouvel objet", "lieu_livraison": "", "taux_tva": "0", "validite_jours": "60",
        })
        self.assertRedirects(response, reverse("facturation:document-edit", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual((doc.objet, doc.taux_tva, doc.validite_jours, doc.total_tva, doc.total_ttc), ("Nouvel objet", 0, 60, 0, 400_000))

    def test_sans_modification(self):
        doc = self.brouillon()
        response = self.client.post(reverse("facturation:document-edit", args=[doc.pk]), {
            "contact": self.contact.pk, "objet": "", "lieu_livraison": "", "taux_tva": "18", "validite_jours": "30",
        }, follow=True)
        self.assertIn("Aucune modification.", _messages(response))

    def test_contact_desactive_depuis_reste_affiche_mais_pas_un_autre(self):
        doc = self.brouillon()
        self.contact.actif = False
        self.contact.save()
        autre_inactif = ContactClient.objects.create(nom="Autre", actif=False)
        form = self.client.get(reverse("facturation:document-edit", args=[doc.pk])).context["entete_form"]
        self.assertIn(self.contact, form.fields["contact"].queryset)
        self.assertNotIn(autre_inactif, form.fields["contact"].queryset)

    def test_nombre_de_requetes_constant(self):
        doc = self.brouillon()
        url = reverse("facturation:document-edit", args=[doc.pk])
        Produit.objects.create(designation="Câble", prix_unitaire=500)
        self.client.get(url)
        with self.assertNumQueries(NB_REQUETES_EDITION):
            self.client.get(url)
        services.remplacer_lignes(doc, self.user, LIGNES * 15)
        with self.assertNumQueries(NB_REQUETES_EDITION):
            response = self.client.get(url)
        self.assertEqual(len(response.context["lignes"]), 30)

    def test_champs_libres_echappes(self):
        doc = self.brouillon(objet="<b>gras</b>", lignes=[{"designation": "<img src=x onerror=alert(1)>", "quantite": 1, "prix_unitaire": 5}])
        response = self.client.get(reverse("facturation:document-edit", args=[doc.pk]))
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")
        self.assertNotContains(response, "<b>gras</b>")
        self.assertContains(response, "&lt;img src=x onerror=alert(1)&gt;")


class LignesHtmxTests(BaseSaisie):
    def setUp(self):
        super().setUp()
        self.doc = self.brouillon()

    def _verifier_totaux(self, response):
        """Les totaux affichés sont ceux du service, recalculés à partir des lignes en base."""
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "facturation/_lignes.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.doc.refresh_from_db()
        ht, tva, ttc = services.calculer_totaux(self.doc.lignes.values_list("total", flat=True), self.doc.taux_tva)
        self.assertEqual((self.doc.total_ht, self.doc.total_tva, self.doc.total_ttc), (ht, tva, ttc))
        self.assertEqual(_total(response, "total-ht"), fcfa(ht))
        self.assertEqual(_total(response, "total-tva"), fcfa(tva))
        self.assertEqual(_total(response, "total-ttc"), fcfa(ttc))
        return ht, tva, ttc

    def test_ajout_d_une_ligne_libre(self):
        response = self.client.post(reverse("facturation:ligne-add", args=[self.doc.pk]), {
            "nouvelle-designation": "Câblage", "nouvelle-quantite": "3", "nouvelle-prix_unitaire": "1 275",
        }, **HX)
        self.assertEqual(self._verifier_totaux(response), (403_825, 72_690, 476_515))
        self.assertEqual(self.doc.lignes.last().designation, "Câblage")

    def test_ajout_depuis_un_produit_actif(self):
        produit = Produit.objects.create(designation="Enregistreur", prix_unitaire=95_000)
        Produit.objects.create(designation="Ancien", prix_unitaire=5, actif=False)
        response = self.client.post(reverse("facturation:ligne-add-produit", args=[self.doc.pk]), {"produit": produit.pk}, **HX)
        self._verifier_totaux(response)
        ligne = self.doc.lignes.last()
        self.assertEqual((ligne.designation, ligne.quantite, ligne.prix_unitaire, ligne.produit), ("Enregistreur", 1, 95_000, produit))
        self.assertNotIn("Ancien", [str(p) for p in response.context["ajout_produit_form"].fields["produit"].queryset])

    def test_produit_inactif_refuse(self):
        inactif = Produit.objects.create(designation="Ancien", prix_unitaire=5, actif=False)
        response = self.client.post(reverse("facturation:ligne-add-produit", args=[self.doc.pk]), {"produit": inactif.pk}, **HX)
        self.assertEqual(response.status_code, 200)
        self.assertIn("produit", response.context["ajout_produit_form"].errors)
        self.assertEqual(self.doc.lignes.count(), 2)

    def test_modification_d_une_ligne(self):
        ligne = self.doc.lignes.get(rang=1)
        response = self.client.post(reverse("facturation:ligne-update", args=[self.doc.pk, ligne.pk]), {
            f"ligne-{ligne.pk}-designation": "Caméra bullet", f"ligne-{ligne.pk}-quantite": "4", f"ligne-{ligne.pk}-prix_unitaire": "100000",
        }, **HX)
        self.assertEqual(self._verifier_totaux(response), (550_000, 99_000, 649_000))
        ligne.refresh_from_db()
        self.assertEqual((ligne.designation, ligne.quantite, ligne.total), ("Caméra bullet", 4, 400_000))

    def test_suppression_d_une_ligne(self):
        ligne = self.doc.lignes.get(rang=1)
        response = self.client.post(reverse("facturation:ligne-delete", args=[self.doc.pk, ligne.pk]), **HX)
        self.assertEqual(self._verifier_totaux(response), (150_000, 27_000, 177_000))
        self.assertEqual(list(self.doc.lignes.values_list("rang", "designation")), [(1, "Pose")])

    def test_erreurs_a_la_ligne_ajoutee_sans_erreur_500(self):
        cas = [
            ({"nouvelle-designation": "X", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": "1002"}, "prix_unitaire", "multiple de 5"),
            ({"nouvelle-designation": "X", "nouvelle-quantite": "0", "nouvelle-prix_unitaire": "5"}, "quantite", "comprise entre"),
            ({"nouvelle-designation": "X", "nouvelle-quantite": str(QUANTITE_MAX + 1), "nouvelle-prix_unitaire": "5"}, "quantite", "comprise entre"),
            ({"nouvelle-designation": "X", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": str(PRIX_UNITAIRE_MAX + 5)}, "prix_unitaire", "compris entre"),
            ({"nouvelle-designation": "", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": "5"}, "designation", "obligatoire"),
        ]
        for donnees, champ, attendu in cas:
            with self.subTest(champ=champ, donnees=donnees):
                response = self.client.post(reverse("facturation:ligne-add", args=[self.doc.pk]), donnees, **HX)
                self.assertEqual(response.status_code, 200)
                erreurs = " ".join(response.context["ajout_form"].errors[champ]).lower()
                self.assertIn(attendu, erreurs)
                self.assertContains(response, response.context["ajout_form"].errors[champ][0])
        self.assertEqual(self.doc.lignes.count(), 2)
        self._verifier_totaux(response)

    def test_erreur_affichee_sur_la_ligne_modifiee(self):
        ligne = self.doc.lignes.get(rang=2)
        response = self.client.post(reverse("facturation:ligne-update", args=[self.doc.pk, ligne.pk]), {
            f"ligne-{ligne.pk}-designation": "Pose", f"ligne-{ligne.pk}-quantite": "1", f"ligne-{ligne.pk}-prix_unitaire": "7",
        }, **HX)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        bloc = html[html.index(f'id="ligne-{ligne.pk}"'):]
        bloc = bloc[: bloc.index("</li>")]
        self.assertIn("multiple de 5", bloc)
        self.assertIn('value="7"', bloc)  # la saisie erronée est conservée
        ligne.refresh_from_db()
        self.assertEqual(ligne.prix_unitaire, 150_000)

    def test_maximum_de_lignes(self):
        services.remplacer_lignes(self.doc, self.user, [{"designation": "X", "quantite": 1, "prix_unitaire": 5}] * LIGNES_MAX)
        response = self.client.post(reverse("facturation:ligne-add", args=[self.doc.pk]), {
            "nouvelle-designation": "Une de trop", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": "5",
        }, **HX)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"dépasser {LIGNES_MAX} lignes", " ".join(response.context["ajout_form"].non_field_errors()))
        self.assertEqual(self.doc.lignes.count(), LIGNES_MAX)

    def test_sans_htmx_redirection_ou_page_complete(self):
        url = reverse("facturation:ligne-add", args=[self.doc.pk])
        response = self.client.post(url, {"nouvelle-designation": "X", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": "5"})
        self.assertRedirects(response, reverse("facturation:document-edit", args=[self.doc.pk]))
        response = self.client.post(url, {"nouvelle-designation": "X", "nouvelle-quantite": "1", "nouvelle-prix_unitaire": "7"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "facturation/document_edit.html")
        self.assertContains(response, "multiple de 5")

    def test_ligne_d_un_autre_document_404(self):
        autre = self.brouillon()
        ligne_autre = autre.lignes.first()
        response = self.client.post(reverse("facturation:ligne-delete", args=[self.doc.pk, ligne_autre.pk]), **HX)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(autre.lignes.count(), 2)


class DocumentEmisNonModifiableTests(BaseSaisie):
    def test_edition_et_suppression_refusees_avec_message(self):
        doc = self.emis()
        liste = reverse("facturation:document-list")
        for methode, url in [
            ("get", reverse("facturation:document-edit", args=[doc.pk])),
            ("post", reverse("facturation:document-edit", args=[doc.pk])),
            ("get", reverse("facturation:document-delete", args=[doc.pk])),
            ("post", reverse("facturation:document-delete", args=[doc.pk])),
            ("post", reverse("facturation:ligne-add", args=[doc.pk])),
            ("post", reverse("facturation:ligne-add-produit", args=[doc.pk])),
            ("post", reverse("facturation:ligne-update", args=[doc.pk, doc.lignes.first().pk])),
            ("post", reverse("facturation:ligne-delete", args=[doc.pk, doc.lignes.first().pk])),
        ]:
            with self.subTest(methode=methode, url=url):
                response = getattr(self.client, methode)(url, {"contact": self.contact.pk, "taux_tva": "0"})
                self.assertRedirects(response, liste)
                self.assertIn("n'est plus un brouillon", " ".join(_messages(response)))
        doc.refresh_from_db()
        self.assertEqual((doc.statut, doc.taux_tva, doc.lignes.count()), (S.EMISE, 18, 2))

    def test_action_htmx_redirigee_par_en_tete(self):
        doc = self.emis()
        response = self.client.post(reverse("facturation:ligne-delete", args=[doc.pk, doc.lignes.first().pk]), **HX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], reverse("facturation:document-list"))
        self.assertEqual(doc.lignes.count(), 2)


class SuppressionBrouillonTests(BaseSaisie):
    def test_confirmation_puis_suppression(self):
        doc = self.brouillon()
        url = reverse("facturation:document-delete", args=[doc.pk])
        response = self.client.get(url)
        self.assertContains(response, "Supprimer le brouillon")
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(response, reverse("facturation:document-list"))
        self.assertFalse(Document.objects.filter(pk=doc.pk).exists())


# ---------------------------------------------------------------------------
# Services ajoutés ou retouchés (lot 3a)
# ---------------------------------------------------------------------------

class ContactInactifTests(BaseSaisie):
    def test_creation_refusee_pour_un_contact_inactif(self):
        inactif = ContactClient.objects.create(nom="Ancien", actif=False)
        with self.assertRaises(ErreurFacturation):
            services.creer_brouillon(T.DEVIS, inactif, self.user)
        self.assertFalse(Document.objects.exists())

    def test_brouillon_ne_peut_pas_passer_a_un_autre_contact_inactif(self):
        doc = self.brouillon()
        inactif = ContactClient.objects.create(nom="Ancien", actif=False)
        with self.assertRaises(ErreurFacturation):
            services.modifier_brouillon(doc, self.user, contact=inactif)

    def test_emission_conversion_et_duplication_restent_permises(self):
        a_emettre = self.brouillon()
        a_modifier = self.brouillon()
        devis = self.brouillon()
        services.emettre(devis, self.user)
        services.changer_statut(devis, S.ACCEPTE, self.user)
        self.contact.actif = False
        self.contact.save()
        self.assertEqual(services.emettre(a_emettre, self.user).statut, S.ENVOYE)
        services.modifier_brouillon(a_modifier, self.user, objet="Toujours modifiable", contact=self.contact)
        self.assertEqual(a_modifier.objet, "Toujours modifiable")
        self.assertEqual(services.convertir_en_facture(devis, self.user).contact, self.contact)
        self.assertEqual(services.dupliquer(devis, self.user).contact, self.contact)

    def test_taux_et_validite_saisis_a_la_creation(self):
        doc = services.creer_brouillon(T.DEVIS, self.contact, self.user, taux_tva=0, validite_jours=10)
        self.assertEqual((doc.taux_tva, doc.validite_jours), (0, 10))
        with self.assertRaises(MontantInvalide):
            services.creer_brouillon(T.DEVIS, self.contact, self.user, taux_tva=101)


class BornesTests(BaseSaisie):
    def test_bornes_des_montants(self):
        self.assertEqual(services.verifier_prix_unitaire(10**10), 10**10)
        self.assertEqual(services.verifier_quantite(10**5), 10**5)
        for appel in (lambda: services.verifier_prix_unitaire(10**10 + 5), lambda: services.verifier_quantite(10**5 + 1)):
            with self.assertRaises(MontantInvalide):
                appel()

    def test_au_plus_200_lignes(self):
        une = {"designation": "X", "quantite": 1, "prix_unitaire": 5}
        doc = self.brouillon(lignes=[une] * LIGNES_MAX)
        with self.assertRaises(ErreurFacturation):
            services.ajouter_ligne(doc, self.user, "X", 1, 5)
        with self.assertRaises(ErreurFacturation):
            services.remplacer_lignes(doc, self.user, [une] * (LIGNES_MAX + 1))
        with self.assertRaises(ErreurFacturation):
            self.brouillon(lignes=[une] * (LIGNES_MAX + 1))
        self.assertEqual(doc.lignes.count(), LIGNES_MAX)

    def test_le_ht_maximal_tient_dans_la_colonne(self):
        """Pire cas : 200 lignes au prix et à la quantité maximum, TVA de 100 %, enregistré et relu."""
        ht_max = LIGNES_MAX * QUANTITE_MAX * PRIX_UNITAIRE_MAX
        _, ttc_max = services.calculer_totaux([ht_max], TAUX_TVA_MAX)[1:]
        _, capacite = connection.ops.integer_field_range("PositiveBigIntegerField")
        capacite_signee = 2**63 - 1  # BIGINT signé : la plus petite capacité des trois moteurs
        self.assertLess(ttc_max, min(capacite, capacite_signee))
        maximum = {"designation": "Max", "quantite": QUANTITE_MAX, "prix_unitaire": PRIX_UNITAIRE_MAX}
        doc = self.brouillon(lignes=[maximum] * LIGNES_MAX, taux_tva=TAUX_TVA_MAX)
        doc.refresh_from_db()
        self.assertEqual((doc.total_ht, doc.total_ttc), (ht_max, ttc_max))

    def test_la_base_applique_les_nouvelles_bornes(self):
        ligne = self.brouillon().lignes.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LigneDocument.objects.filter(pk=ligne.pk).update(prix_unitaire=10**10 + 5, total=10**10 + 5, quantite=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LigneDocument.objects.filter(pk=ligne.pk).update(quantite=10**5 + 1, prix_unitaire=5, total=(10**5 + 1) * 5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Produit.objects.bulk_create([Produit(designation="X", prix_unitaire=10**10 + 5)])


# ---------------------------------------------------------------------------
# Présentation, outils, textes
# ---------------------------------------------------------------------------

class FiltresTests(SimpleTestCase):
    def test_fcfa(self):
        nbsp = " "
        self.assertEqual(fcfa(1_234_500), f"1{nbsp}234{nbsp}500{nbsp}FCFA")
        self.assertEqual(fcfa(0), f"0{nbsp}FCFA")
        self.assertEqual(fcfa(5), f"5{nbsp}FCFA")
        self.assertEqual(fcfa(999), f"999{nbsp}FCFA")
        self.assertEqual(fcfa(1000), f"1{nbsp}000{nbsp}FCFA")
        self.assertEqual(fcfa(-1500), f"-1{nbsp}500{nbsp}FCFA")
        self.assertEqual(fcfa(4 * 10**17), f"400{nbsp}000{nbsp}000{nbsp}000{nbsp}000{nbsp}000{nbsp}FCFA")
        for valeur in (None, "", "1234", 12.5, True):
            with self.subTest(valeur=valeur):
                self.assertEqual(fcfa(valeur), "")

    def test_date_fr(self):
        self.assertEqual(date_fr(date(2026, 3, 9)), "09/03/2026")
        self.assertEqual(date_fr(datetime(2026, 12, 31, 23, 59)), "31/12/2026")
        self.assertEqual(date_fr(datetime(2026, 1, 1, 0, 30, tzinfo=dt_timezone.utc)), "01/01/2026")  # Bamako = UTC
        for valeur in (None, "", "2026-01-01"):
            self.assertEqual(date_fr(valeur), "")


class OutilsEtTextesTests(SimpleTestCase):
    def test_barre_de_debogage_inactive_pendant_les_tests(self):
        self.assertFalse(settings.DEBUG_TOOLBAR)
        self.assertNotIn("debug_toolbar", settings.INSTALLED_APPS)
        self.assertNotIn("debug_toolbar.middleware.DebugToolbarMiddleware", settings.MIDDLEWARE)

    def test_textes_des_gabarits_sans_tiret_long_ni_superviseur(self):
        dossier = Path(settings.BASE_DIR) / "templates" / "facturation"
        for gabarit in sorted(dossier.glob("*.html")):
            texte = gabarit.read_text()
            with self.subTest(gabarit=gabarit.name):
                self.assertNotIn("—", texte)
                self.assertNotIn("–", texte)
                self.assertNotIn("uperviseur", texte)
                self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-➿]", texte), "emoji")
