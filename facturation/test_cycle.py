"""Cycle de vie des documents : détail, actions de statut, conversion, duplication, filtres de la liste (lot 3b)."""

from datetime import date
from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from clients.models import Client
from core.models import ActivityLog

from . import services
from .forms import FiltreDocumentsForm
from .models import ContactClient, Document, HistoriqueStatut
from .templatetags.facturation_format import fcfa

T = Document.Type
S = Document.Statut
LIGNES = [
    {"designation": "Caméra dôme", "quantite": 2, "prix_unitaire": 125_000},
    {"designation": "Pose", "quantite": 1, "prix_unitaire": 150_000},
]  # HT 400 000, TVA 18 % : 72 000, TTC 472 000

# Requêtes SQL mesurées pour un manager ayant la seule permission manage_invoices.
# Liste filtrée : session, utilisateur, 2 de permissions, contacts du filtre, comptage, page.
NB_REQUETES_LISTE_FILTREE = 7
# Détail : session, utilisateur, 2 de permissions, document (et devis d'origine), lignes,
# historique (avec utilisateurs), factures issues du devis (devis uniquement).
NB_REQUETES_DETAIL_DEVIS = 8
NB_REQUETES_DETAIL_FACTURE = 7

# Chemin de statuts par les seules transitions autorisées.
CHEMINS = {
    S.BROUILLON: [], S.ENVOYE: [S.ENVOYE], S.ACCEPTE: [S.ENVOYE, S.ACCEPTE], S.REFUSE: [S.ENVOYE, S.REFUSE],
    S.EMISE: [S.EMISE], S.PAYEE: [S.EMISE, S.PAYEE], S.ANNULEE: [S.EMISE, S.ANNULEE],
}
TYPE_DU_STATUT = {
    S.BROUILLON: T.DEVIS, S.ENVOYE: T.DEVIS, S.ACCEPTE: T.DEVIS, S.REFUSE: T.DEVIS,
    S.EMISE: T.FACTURE, S.PAYEE: T.FACTURE, S.ANNULEE: T.FACTURE,
}

# Action -> (type, statut de départ autorisé, statut d'arrivée, message attendu).
ACTIONS = {
    "emettre": [(T.DEVIS, S.BROUILLON, S.ENVOYE, "envoyé"), (T.FACTURE, S.BROUILLON, S.EMISE, "émise")],
    "accepter": [(T.DEVIS, S.ENVOYE, S.ACCEPTE, "accepté")],
    "refuser": [(T.DEVIS, S.ENVOYE, S.REFUSE, "refusé")],
    "payer": [(T.FACTURE, S.EMISE, S.PAYEE, "marquée payée")],
    "annuler": [(T.FACTURE, S.EMISE, S.ANNULEE, "annulée")],
}


def _jour(jour):
    """Fixe la date du jour (émission dans services.py, expiration dans models.py)."""
    return mock.patch("django.utils.timezone.localdate", return_value=jour)


def _utilisateur(username="factu", permission=True, role=User.Role.MANAGER, **kwargs):
    user = User.objects.create_user(username=username, password="x", role=role, **kwargs)
    if permission:
        user.user_permissions.add(Permission.objects.get(codename="manage_invoices"))
    return user


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class BaseCycle(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _utilisateur(first_name="Awa", last_name="Traoré")
        cls.contact = ContactClient.objects.create(nom="Societe Alpha", telephone="76 12 34 56", adresse="ACI 2000, Bamako")
        cls.autre_contact = ContactClient.objects.create(nom="Banque Beta", telephone="20 22 00 00")

    def setUp(self):
        self.client.force_login(self.user)

    def brouillon(self, type_document=T.DEVIS, contact=None, lignes=LIGNES, **kwargs):
        return services.creer_brouillon(type_document, contact or self.contact, self.user, lignes=lignes, **kwargs)

    def document(self, statut, type_document=None, **kwargs):
        doc = self.brouillon(type_document or TYPE_DU_STATUT[statut], **kwargs)
        for etape in CHEMINS[statut]:
            services.changer_statut(doc, etape, self.user)
        return doc

    def url(self, nom, doc):
        return reverse(f"facturation:{nom}", args=[doc.pk])

    def etat(self, doc):
        """Statut, numéro et nombre d'entrées d'historique en base."""
        doc = Document.objects.get(pk=doc.pk)
        return doc.statut, doc.numero, doc.historique.count()


# ---------------------------------------------------------------------------
# Accès
# ---------------------------------------------------------------------------

class AccesCycleTests(BaseCycle):
    ACTIONS_POST = ["document-emettre", "document-accepter", "document-refuser", "document-payer",
                    "document-annuler", "document-convertir", "document-dupliquer"]

    def test_sans_permission_403_et_rien_ne_change(self):
        devis = self.document(S.ENVOYE)
        brouillon = self.brouillon()
        avant = (self.etat(devis), self.etat(brouillon), Document.objects.count())
        client_portail = Client.objects.create(nom="Portail")
        refuses = [
            _utilisateur("mgr_sans", permission=False),
            _utilisateur("aud_sans", permission=False, role=User.Role.SUPERVISEUR),
            User.objects.create_user(username="cli", password="x", role=User.Role.CLIENT, client=client_portail),
        ]
        for user in refuses:
            self.client.force_login(user)
            with self.subTest(user=user.username, vue="document-detail"):
                self.assertEqual(self.client.get(self.url("document-detail", devis)).status_code, 403)
            for nom in self.ACTIONS_POST:
                cible = brouillon if nom == "document-emettre" else devis
                with self.subTest(user=user.username, vue=nom):
                    self.assertEqual(self.client.post(self.url(nom, cible)).status_code, 403)
        self.assertEqual((self.etat(devis), self.etat(brouillon), Document.objects.count()), avant)

    def test_anonyme_redirige_vers_la_connexion(self):
        devis = self.document(S.ENVOYE)
        self.client.logout()
        for methode, nom in [("get", "document-detail")] + [("post", n) for n in self.ACTIONS_POST]:
            with self.subTest(vue=nom):
                response = getattr(self.client, methode)(self.url(nom, devis))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertEqual(self.etat(devis)[0], S.ENVOYE)

    def test_get_refuse_sur_les_actions(self):
        devis = self.document(S.ENVOYE)
        for nom in self.ACTIONS_POST:
            with self.subTest(vue=nom):
                self.assertEqual(self.client.get(self.url(nom, devis)).status_code, 405)
        self.assertEqual(self.etat(devis), (S.ENVOYE, devis.numero, 2))
        self.assertEqual(Document.objects.count(), 1)

    def test_document_inconnu_404(self):
        for methode, nom in [("get", "document-detail")] + [("post", n) for n in self.ACTIONS_POST]:
            with self.subTest(vue=nom):
                url = reverse(f"facturation:{nom}", args=[999_999])
                self.assertEqual(getattr(self.client, methode)(url).status_code, 404)


# ---------------------------------------------------------------------------
# Page de détail
# ---------------------------------------------------------------------------

class DetailTests(BaseCycle):
    def test_contenu_d_un_devis_envoye(self):
        with _jour(date(2026, 3, 2)):
            devis = self.document(S.ENVOYE, objet="Vidéosurveillance agence", lieu_livraison="Agence ACI")
        # Le contact change après l'envoi : le détail montre les valeurs figées.
        self.contact.nom, self.contact.telephone = "Nouveau nom", "00 00 00 00"
        self.contact.save()
        with _jour(date(2026, 3, 10)):
            response = self.client.get(self.url("document-detail", devis))
        self.assertEqual(response.status_code, 200)
        for texte in [
            f"Devis {devis.numero}", "Envoyé", "Societe Alpha", "76 12 34 56", "ACI 2000, Bamako",
            "Vidéosurveillance agence", "Agence ACI", "02/03/2026", "01/04/2026", "18 %",
            "Caméra dôme", "Pose", fcfa(125_000), fcfa(250_000),
            fcfa(400_000), fcfa(72_000), fcfa(472_000), "Awa Traoré", "Brouillon vers Envoyé",
        ]:
            with self.subTest(texte=texte):
                self.assertContains(response, texte)
        self.assertNotContains(response, "Nouveau nom")
        self.assertNotContains(response, "Expiré")
        self.assertEqual([h.nouveau_statut for h in response.context["historique"]], [S.BROUILLON, S.ENVOYE])

    def test_badge_expire_calcule_a_la_date_du_jour(self):
        with _jour(date(2026, 1, 1)):
            devis = self.document(S.ENVOYE)  # valable jusqu'au 31/01/2026
        with _jour(date(2026, 1, 31)):
            self.assertNotContains(self.client.get(self.url("document-detail", devis)), "Expiré")
        with _jour(date(2026, 2, 1)):
            response = self.client.get(self.url("document-detail", devis))
            self.assertContains(response, "Expiré")
            self.assertContains(self.client.get(reverse("facturation:document-list")), "Expiré")
        self.assertEqual(self.etat(devis)[0], S.ENVOYE)  # jamais stocké

    def test_brouillon_redirige_vers_son_edition(self):
        doc = self.brouillon()
        self.assertRedirects(self.client.get(self.url("document-detail", doc)), self.url("document-edit", doc))

    def test_liste_numero_vers_le_detail_brouillon_vers_l_edition(self):
        emis = self.document(S.EMISE)
        brouillon = self.brouillon()
        response = self.client.get(reverse("facturation:document-list"))
        self.assertContains(response, f'href="{self.url("document-detail", emis)}"')
        self.assertContains(response, f'href="{self.url("document-edit", brouillon)}"')
        self.assertNotContains(response, f'href="{self.url("document-detail", brouillon)}"')

    def test_champs_libres_echappes(self):
        attaque = "<script>alert(1)</script>"
        self.contact.adresse = attaque
        self.contact.save()
        doc = self.document(S.EMISE, objet=attaque, lieu_livraison=attaque,
                            lignes=[{"designation": attaque, "quantite": 1, "prix_unitaire": 5}])
        response = self.client.get(self.url("document-detail", doc))
        self.assertNotContains(response, attaque)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;", count=4)

    def _mesurer(self, doc):
        url = self.url("document-detail", doc)
        self.client.get(url)  # premières requêtes de session hors mesure
        return url

    def test_nombre_de_requetes_constant_devis(self):
        petit = self.document(S.ENVOYE)
        url = self._mesurer(petit)
        with self.assertNumQueries(NB_REQUETES_DETAIL_DEVIS):
            self.client.get(url)
        # Beaucoup de lignes, plus d'historique, plusieurs factures liées.
        lignes = [{"designation": f"Article {i}", "quantite": 1, "prix_unitaire": 5} for i in range(40)]
        grand = self.document(S.ACCEPTE, lignes=lignes)
        services.changer_statut(services.emettre(services.convertir_en_facture(grand, self.user), self.user),
                                S.ANNULEE, self.user)
        services.convertir_en_facture(grand, self.user)
        with self.assertNumQueries(NB_REQUETES_DETAIL_DEVIS):
            response = self.client.get(self.url("document-detail", grand))
        self.assertEqual((len(response.context["lignes"]), len(response.context["factures"])), (40, 2))

    def test_nombre_de_requetes_constant_facture(self):
        petite = self.document(S.EMISE)
        url = self._mesurer(petite)
        with self.assertNumQueries(NB_REQUETES_DETAIL_FACTURE):
            self.client.get(url)
        devis = self.document(S.ACCEPTE)
        lignes = [{"designation": f"Article {i}", "quantite": 1, "prix_unitaire": 5} for i in range(40)]
        facture = services.convertir_en_facture(devis, self.user)
        services.remplacer_lignes(facture, self.user, lignes)
        services.changer_statut(services.emettre(facture, self.user), S.PAYEE, self.user)
        with self.assertNumQueries(NB_REQUETES_DETAIL_FACTURE):
            response = self.client.get(self.url("document-detail", facture))
        self.assertEqual((len(response.context["lignes"]), len(response.context["historique"])), (40, 3))


# ---------------------------------------------------------------------------
# Actions de statut
# ---------------------------------------------------------------------------

class ActionsTests(BaseCycle):
    def test_chaque_action_en_succes(self):
        for action, cas in ACTIONS.items():
            for type_document, depart, arrivee, libelle in cas:
                with self.subTest(action=action, type=type_document):
                    doc = self.document(depart, type_document=type_document)
                    historique_avant = doc.historique.count()
                    response = self.client.post(self.url(f"document-{action}", doc))
                    doc.refresh_from_db()
                    self.assertEqual(doc.statut, arrivee)
                    self.assertRedirects(response, self.url("document-detail", doc))
                    self.assertEqual(_messages(response), [f"{doc.get_type_display()} {doc.numero} {libelle}."])
                    self.assertEqual(doc.historique.count(), historique_avant + 1)
                    derniere = doc.historique.last()
                    self.assertEqual((derniere.ancien_statut, derniere.nouveau_statut, derniere.utilisateur),
                                     (depart, arrivee, self.user))
                    self.assertTrue(ActivityLog.objects.filter(
                        action="transition_document", object_id=str(doc.pk), detail__nouveau=arrivee).exists())

    def test_chaque_action_depuis_un_etat_interdit(self):
        # Tous les états existants : brouillon des deux types, puis chaque statut de son type.
        etats = [(T.DEVIS, S.BROUILLON), (T.FACTURE, S.BROUILLON)] + [
            (TYPE_DU_STATUT[s], s) for s in S.values if s != S.BROUILLON
        ]
        for action, cas in ACTIONS.items():
            autorises = {(t, d) for t, d, _, _ in cas}
            for type_document, statut in etats:
                if (type_document, statut) in autorises:
                    continue
                with self.subTest(action=action, type=type_document, statut=statut):
                    doc = self.document(statut, type_document=type_document)
                    avant = self.etat(doc)
                    response = self.client.post(self.url(f"document-{action}", doc))
                    self.assertEqual(self.etat(doc), avant)
                    doc.refresh_from_db()
                    page = "document-edit" if doc.est_brouillon else "document-detail"
                    self.assertRedirects(response, self.url(page, doc), fetch_redirect_response=False)
                    message = " ".join(_messages(response))
                    self.assertIn("Action impossible", message)
                    self.assertIn(f"« {doc.get_statut_display()} »", message)

    def test_double_soumission(self):
        for action, cas in ACTIONS.items():
            type_document, depart, arrivee, _ = cas[0]
            with self.subTest(action=action):
                doc = self.document(depart, type_document=type_document)
                url = self.url(f"document-{action}", doc)
                self.client.post(url)
                etat = self.etat(doc)
                response = self.client.post(url)
                self.assertEqual(self.etat(doc), etat)
                self.assertEqual(etat[0], arrivee)
                self.assertRedirects(response, self.url("document-detail", doc))
                self.assertIn("Action impossible", " ".join(_messages(response)))

    def test_emission_d_un_document_vide_message_lisible(self):
        doc = self.brouillon(lignes=())
        response = self.client.post(self.url("document-emettre", doc))
        self.assertRedirects(response, self.url("document-edit", doc))
        self.assertEqual(_messages(response), ["Un document sans ligne ne peut pas être émis."])
        self.assertEqual(self.etat(doc), (S.BROUILLON, None, 1))

    def test_action_sur_un_document_supprime_entre_temps(self):
        doc = self.brouillon()
        with mock.patch("facturation.services._verrouiller", side_effect=Document.DoesNotExist):
            response = self.client.post(self.url("document-emettre", doc))
        self.assertRedirects(response, reverse("facturation:document-list"))
        self.assertEqual(_messages(response), ["Ce document n'existe plus."])

    def test_boutons_selon_les_transitions_permises(self):
        attendus = {
            S.ENVOYE: {"document-accepter", "document-refuser", "document-dupliquer"},
            S.ACCEPTE: {"document-convertir", "document-dupliquer"},
            S.REFUSE: {"document-dupliquer"},
            S.EMISE: {"document-payer", "document-annuler", "document-dupliquer"},
            S.PAYEE: {"document-dupliquer"},
            S.ANNULEE: {"document-dupliquer"},
        }
        tous = set().union(*attendus.values()) | {"document-emettre"}
        for statut, boutons in attendus.items():
            with self.subTest(statut=statut):
                doc = self.document(statut)
                contenu = self.client.get(self.url("document-detail", doc)).content.decode()
                for nom in tous:
                    present = f'action="{self.url(nom, doc)}"' in contenu
                    self.assertEqual(present, nom in boutons, nom)

    def test_confirmation_navigateur_pour_emettre_refuser_annuler(self):
        devis_brouillon = self.brouillon()
        facture_brouillon = self.brouillon(T.FACTURE)
        envoye = self.document(S.ENVOYE)
        emise = self.document(S.EMISE)
        for page, doc, action in [
            ("document-edit", devis_brouillon, "document-emettre"),
            ("document-edit", facture_brouillon, "document-emettre"),
            ("document-detail", envoye, "document-refuser"),
            ("document-detail", emise, "document-annuler"),
        ]:
            with self.subTest(action=action, type=doc.type):
                contenu = self.client.get(self.url(page, doc)).content.decode()
                debut = contenu.index(f'action="{self.url(action, doc)}"')
                self.assertIn("return confirm(", contenu[debut:contenu.index(">", debut)])
                self.assertIn("csrfmiddlewaretoken", contenu[debut:debut + 400])
        contenu = self.client.get(self.url("document-detail", envoye)).content.decode()
        debut = contenu.index(f'action="{self.url("document-accepter", envoye)}"')
        self.assertNotIn("confirm(", contenu[debut:contenu.index(">", debut)])


# ---------------------------------------------------------------------------
# Conversion et duplication
# ---------------------------------------------------------------------------

class ConversionVueTests(BaseCycle):
    def test_conversion_et_liens_dans_les_deux_sens(self):
        devis = self.document(S.ACCEPTE)
        response = self.client.post(self.url("document-convertir", devis))
        facture = Document.objects.get(type=T.FACTURE)
        self.assertEqual((facture.source, facture.statut), (devis, S.BROUILLON))
        self.assertRedirects(response, self.url("document-edit", facture))
        self.assertIn(f"depuis le devis {devis.numero}", " ".join(_messages(response)))

        edition = self.client.get(self.url("document-edit", facture))
        self.assertContains(edition, f'href="{self.url("document-detail", devis)}"')
        detail_devis = self.client.get(self.url("document-detail", devis))
        self.assertContains(detail_devis, f'href="{self.url("document-edit", facture)}"')

        services.emettre(facture, self.user)
        detail_facture = self.client.get(self.url("document-detail", facture))
        self.assertContains(detail_facture, "Devis d'origine")
        self.assertContains(detail_facture, f'href="{self.url("document-detail", devis)}"')
        detail_devis = self.client.get(self.url("document-detail", devis))
        self.assertContains(detail_devis, f'href="{self.url("document-detail", facture)}"')
        self.assertContains(detail_devis, facture.numero)

    def test_facture_active_pas_de_nouvelle_conversion(self):
        devis = self.document(S.ACCEPTE)
        url = self.url("document-convertir", devis)
        self.client.post(url)
        detail = self.client.get(self.url("document-detail", devis))
        self.assertNotContains(detail, f'action="{url}"')
        self.assertNotIn("convertir", detail.context["actions"])

        response = self.client.post(url)  # double clic ou second utilisateur
        self.assertRedirects(response, self.url("document-detail", devis))
        self.assertIn("déjà une facture en cours", " ".join(_messages(response)))
        self.assertEqual(devis.factures.count(), 1)

        # Une fois la facture annulée, la conversion est de nouveau offerte.
        facture = devis.factures.get()
        services.changer_statut(services.emettre(facture, self.user), S.ANNULEE, self.user)
        self.assertContains(self.client.get(self.url("document-detail", devis)), f'action="{url}"')

    def test_conversion_refusee_hors_devis_accepte(self):
        for statut in (S.ENVOYE, S.REFUSE, S.EMISE):
            with self.subTest(statut=statut):
                doc = self.document(statut)
                response = self.client.post(self.url("document-convertir", doc))
                self.assertRedirects(response, self.url("document-detail", doc))
                self.assertEqual(_messages(response), ["Seul un devis accepté peut être converti en facture."])
        self.assertFalse(Document.objects.filter(source__isnull=False).exists())


class DuplicationVueTests(BaseCycle):
    def test_duplication_vers_l_edition_du_nouveau_brouillon(self):
        for statut in (S.ENVOYE, S.PAYEE):
            with self.subTest(statut=statut):
                original = self.document(statut, objet="Objet copié")
                avant = self.etat(original)
                response = self.client.post(self.url("document-dupliquer", original))
                copie = Document.objects.exclude(pk=original.pk).latest("pk")
                self.assertRedirects(response, self.url("document-edit", copie))
                self.assertEqual((copie.type, copie.statut, copie.objet, copie.lignes.count()),
                                 (original.type, S.BROUILLON, "Objet copié", 2))
                self.assertIn(f"Copie de {original.numero}", " ".join(_messages(response)))
                self.assertEqual(self.etat(original), avant)


# ---------------------------------------------------------------------------
# Filtres de la liste
# ---------------------------------------------------------------------------

class FiltresListeTests(BaseCycle):
    def setUp(self):
        super().setUp()
        with _jour(date(2026, 1, 10)):
            self.devis_janvier = self.document(S.ENVOYE, objet="Caméras agence")  # valable au 09/02
        with _jour(date(2026, 3, 5)):
            self.facture_mars = self.document(S.PAYEE, contact=self.autre_contact, objet="Contrôle d'accès")
            self.devis_accepte = self.document(S.ACCEPTE, objet="Alarme")
        self.brouillon_devis = self.brouillon(objet="Brouillon caméras")
        self.brouillon_facture = self.brouillon(T.FACTURE, contact=self.autre_contact)

    def lister(self, **params):
        with _jour(date(2026, 3, 20)):
            response = self.client.get(reverse("facturation:document-list"), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_sans_filtre_tout_est_visible_brouillons_compris(self):
        response = self.lister()
        self.assertEqual(response.context["page_obj"].paginator.count, 5)
        self.assertContains(response, "5 documents")
        self.assertFalse(response.context["filtres_actifs"])
        self.assertNotContains(response, "Réinitialiser")

    def test_filtres_un_a_un(self):
        cas = [
            ({"type": "devis"}, {self.devis_janvier, self.devis_accepte, self.brouillon_devis}),
            ({"type": "facture"}, {self.facture_mars, self.brouillon_facture}),
            ({"statut": "brouillon"}, {self.brouillon_devis, self.brouillon_facture}),
            ({"statut": "payee"}, {self.facture_mars}),
            ({"statut": "envoye"}, {self.devis_janvier}),
            ({"statut": "expire"}, {self.devis_janvier}),
            ({"contact": self.autre_contact.pk}, {self.facture_mars, self.brouillon_facture}),
            ({"du": "2026-03-01"}, {self.facture_mars, self.devis_accepte}),
            ({"au": "2026-01-31"}, {self.devis_janvier}),
            ({"du": "2026-03-05", "au": "2026-03-05"}, {self.facture_mars, self.devis_accepte}),
            ({"q": "caméras"}, {self.devis_janvier, self.brouillon_devis}),
            ({"q": self.facture_mars.numero}, {self.facture_mars}),
            ({"q": "beta"}, {self.facture_mars, self.brouillon_facture}),
        ]
        for params, attendus in cas:
            with self.subTest(params=params):
                response = self.lister(**params)
                self.assertEqual(set(response.context["documents"]), attendus)
                self.assertTrue(response.context["filtres_actifs"])
                self.assertContains(response, "Réinitialiser")
                self.assertContains(response, f'{len(attendus)} document')

    def test_filtres_combines(self):
        cas = [
            ({"type": "devis", "q": "caméras"}, {self.devis_janvier, self.brouillon_devis}),
            ({"type": "devis", "statut": "brouillon", "q": "caméras"}, {self.brouillon_devis}),
            ({"contact": self.contact.pk, "du": "2026-03-01", "au": "2026-03-31"}, {self.devis_accepte}),
            ({"type": "facture", "statut": "expire"}, set()),
            ({"du": "2026-04-01", "au": "2026-03-01"}, set()),
        ]
        for params, attendus in cas:
            with self.subTest(params=params):
                self.assertEqual(set(self.lister(**params).context["documents"]), attendus)

    def test_expire_selon_la_date_du_jour(self):
        url = reverse("facturation:document-list")
        with _jour(date(2026, 2, 9)):  # dernier jour de validité
            self.assertEqual(list(self.client.get(url, {"statut": "expire"}).context["documents"]), [])
        with _jour(date(2026, 2, 10)):
            response = self.client.get(url, {"statut": "expire"})
            self.assertEqual(list(response.context["documents"]), [self.devis_janvier])
        self.assertEqual(self.etat(self.devis_janvier)[0], S.ENVOYE)

    def test_recherche_sur_le_nom_affiche_du_contact(self):
        # Après un renommage, l'émis reste trouvé par son nom figé, le brouillon par le nom actuel.
        self.contact.nom = "Alpha Renommée"
        self.contact.save()
        self.assertEqual(set(self.lister(q="renommée").context["documents"]), {self.brouillon_devis})
        self.assertEqual(set(self.lister(q="societe alpha").context["documents"]),
                         {self.devis_janvier, self.devis_accepte})

    def test_valeurs_invalides_ignorees_sans_erreur(self):
        invalides = [
            {"type": "avoir"}, {"statut": "perdu"}, {"contact": "abc"}, {"contact": "999999"},
            {"du": "2026-13-45"}, {"au": "demain"}, {"q": "x" * 500}, {"page": "zzz"}, {"page": "-1"},
        ]
        for params in invalides:
            with self.subTest(params=params):
                response = self.lister(**params)
                self.assertEqual(response.context["page_obj"].paginator.count, 5)
                self.assertFalse(response.context["filtres_actifs"])
        # Une valeur invalide n'empêche pas les autres filtres et disparaît du formulaire affiché.
        response = self.lister(type="devis", statut="perdu", du="31/31/2026")
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertEqual(response.context["query"], "type=devis")
        self.assertNotContains(response, "perdu")
        self.assertNotContains(response, "31/31/2026")

    def test_liste_des_contacts_du_filtre(self):
        inactif = ContactClient.objects.create(nom="Gamma Ancien")
        self.brouillon(contact=inactif)
        inactif.actif = False
        inactif.save()
        ContactClient.objects.create(nom="Sans document")
        choix = dict(self.lister().context["filtre_form"].fields["contact"].choices)
        self.assertEqual(set(choix.values()), {"Tous les contacts", "Societe Alpha", "Banque Beta", "Gamma Ancien (désactivé)"})

    def test_pagination_garde_les_filtres(self):
        for _ in range(25):
            self.brouillon(objet="Lot caméras")
        response = self.lister(type="devis", q="caméras", statut="brouillon")
        self.assertEqual(response.context["page_obj"].paginator.count, 26)
        self.assertContains(response, "26 documents correspondant aux filtres")
        query = "type=devis&amp;statut=brouillon&amp;q=cam%C3%A9ras"
        self.assertContains(response, f'href="?page=2&amp;{query}"')
        page2 = self.lister(type="devis", q="caméras", statut="brouillon", page=2)
        self.assertEqual(len(page2.context["documents"]), 6)
        self.assertContains(page2, f'href="?page=1&amp;{query}"')

    def test_formulaire_reaffiche_les_filtres(self):
        response = self.lister(type="facture", du="2026-03-01", q="accès")
        self.assertContains(response, 'value="2026-03-01"')
        self.assertContains(response, 'value="accès"')
        self.assertContains(response, '<option value="facture" selected>')

    def test_recherche_echappee(self):
        attaque = "<script>alert(1)</script>"
        response = self.lister(q=attaque)
        self.assertNotContains(response, attaque)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, "Aucun document trouvé")

    def test_nombre_de_requetes_constant_avec_filtres(self):
        url = reverse("facturation:document-list")
        params = {"type": "devis", "statut": "envoye", "contact": self.contact.pk,
                  "du": "2026-01-01", "au": "2026-12-31", "q": "a"}
        self.client.get(url)  # premières requêtes de session hors mesure
        with self.assertNumQueries(NB_REQUETES_LISTE_FILTREE):
            self.client.get(url, params)
        for i in range(30):
            with _jour(date(2026, 2, 1)):
                self.document(S.ENVOYE, objet=f"Lot {i}",
                              lignes=[{"designation": f"L{j}", "quantite": 1, "prix_unitaire": 5} for j in range(5)])
        with self.assertNumQueries(NB_REQUETES_LISTE_FILTREE):
            response = self.client.get(url, params)
        self.assertEqual(len(response.context["documents"]), 20)
        with self.assertNumQueries(NB_REQUETES_LISTE_FILTREE):
            self.client.get(url, {"statut": "expire", "page": "2"})


class FiltreFormTests(TestCase):
    def test_criteres_et_chaine_de_requete(self):
        contact = ContactClient.objects.create(nom="Alpha")
        form = FiltreDocumentsForm(
            {"type": "devis", "statut": "expire", "contact": str(contact.pk), "du": "2026-01-02", "q": "  cam  "},
            contacts=[contact],
        )
        self.assertEqual(form.criteres(), {
            "type_document": "devis", "statut": "expire", "contact_id": contact.pk,
            "du": date(2026, 1, 2), "q": "cam",
        })
        self.assertEqual(form.query_string(), f"type=devis&statut=expire&contact={contact.pk}&du=2026-01-02&q=cam")
        with self.assertNumQueries(0):
            FiltreDocumentsForm({"contact": str(contact.pk)}, contacts=[contact]).criteres()


class ServicesCycleTests(BaseCycle):
    def test_actions_possibles(self):
        attendus = {
            S.BROUILLON: {"emettre"}, S.ENVOYE: {"accepter", "refuser", "dupliquer"},
            S.ACCEPTE: {"convertir", "dupliquer"}, S.REFUSE: {"dupliquer"},
            S.EMISE: {"payer", "annuler", "dupliquer"}, S.PAYEE: {"dupliquer"}, S.ANNULEE: {"dupliquer"},
        }
        for statut, actions in attendus.items():
            with self.subTest(statut=statut):
                self.assertEqual(services.actions_possibles(self.document(statut)), actions)

    def test_conversion_offerte_selon_les_factures_issues(self):
        devis = self.document(S.ACCEPTE)
        annulee = Document(type=T.FACTURE, statut=S.ANNULEE)
        for statut in (S.BROUILLON, S.EMISE, S.PAYEE):
            with self.subTest(statut=statut):
                facture = Document(type=T.FACTURE, statut=statut)
                self.assertNotIn("convertir", services.actions_possibles(devis, [annulee, facture]))
        self.assertIn("convertir", services.actions_possibles(devis, [annulee]))

    def test_action_inconnue_refusee(self):
        doc = self.document(S.ENVOYE)
        with self.assertRaises(services.TransitionInterdite):
            services.appliquer_action(doc, "supprimer", self.user)
        self.assertEqual(self.etat(doc), (S.ENVOYE, doc.numero, 2))

    def test_filtrer_documents_sans_critere(self):
        self.document(S.ENVOYE)
        self.brouillon()
        self.assertEqual(services.filtrer_documents().count(), 2)
        self.assertEqual(HistoriqueStatut.objects.count(), 3)
