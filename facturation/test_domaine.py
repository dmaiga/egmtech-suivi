"""Domaine de la facturation : montants, cycle de vie, numérotation, conversion, duplication."""

import threading
from datetime import date
from decimal import Decimal
from fractions import Fraction
from unittest import mock

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature

from accounts.models import User
from core.models import ActivityLog

from . import services
from .exceptions import ConversionImpossible, DocumentNonModifiable, ErreurFacturation, MontantInvalide, TransitionInterdite
from .models import (
    PRIX_UNITAIRE_MAX,
    QUANTITE_MAX,
    ContactClient,
    Document,
    HistoriqueStatut,
    LigneDocument,
    Produit,
    ProfilEmetteur,
    SequenceNumero,
)

S = Document.Statut
T = Document.Type
LIGNES = [
    {"designation": "Caméra dôme", "quantite": 2, "prix_unitaire": 125_000},
    {"designation": "Pose", "quantite": 1, "prix_unitaire": 150_000},
]  # HT 400 000


def _localdate(jour):
    """Remplace timezone.localdate() vu par les services (date d'émission)."""
    return mock.patch("facturation.services.timezone.localdate", return_value=jour)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="factu", password="x", role=User.Role.MANAGER)
        cls.contact = ContactClient.objects.create(nom="Societe Alpha", telephone="76 12 34 56", adresse="Bamako")

    def brouillon(self, type_document=T.DEVIS, lignes=LIGNES, **kwargs):
        return services.creer_brouillon(type_document, self.contact, self.user, lignes=lignes, **kwargs)

    def document(self, type_document, statut):
        """Document amené au statut voulu par les seules transitions autorisées."""
        doc = self.brouillon(type_document)
        chemins = {
            S.BROUILLON: [], S.ENVOYE: [S.ENVOYE], S.ACCEPTE: [S.ENVOYE, S.ACCEPTE], S.REFUSE: [S.ENVOYE, S.REFUSE],
            S.EMISE: [S.EMISE], S.PAYEE: [S.EMISE, S.PAYEE], S.ANNULEE: [S.EMISE, S.ANNULEE],
        }
        for etape in chemins[statut]:
            services.changer_statut(doc, etape, self.user)
        return doc


# ---------------------------------------------------------------------------
# Montants
# ---------------------------------------------------------------------------

class ArrondiTests(TestCase):
    def test_cas_de_reference(self):
        cas = [(400_000, 18, 72_000), (25, 10, 5), (15, 18, 5), (5, 18, 0), (1275, 18, 230)]
        for ht, taux, tva in cas:
            with self.subTest(ht=ht, taux=taux):
                self.assertEqual(services.calculer_tva(ht, taux), tva)

    def test_demi_vers_le_haut_et_juste_en_dessous(self):
        self.assertEqual(services.arrondir_au_multiple_de_5(250, 100), 5)    # 2,5 -> 5
        self.assertEqual(services.arrondir_au_multiple_de_5(249, 100), 0)    # 2,49 -> 0
        self.assertEqual(services.arrondir_au_multiple_de_5(750, 100), 10)   # 7,5 -> 10
        self.assertEqual(services.arrondir_au_multiple_de_5(749, 100), 5)    # 7,49 -> 5
        self.assertEqual(services.arrondir_au_multiple_de_5(0, 100), 0)
        self.assertEqual(services.arrondir_au_multiple_de_5(7_200_000, 100), 72_000)  # exact : inchangé

    def test_conforme_a_un_calcul_exact_sur_tous_les_taux(self):
        """Comparaison avec un calcul en fractions exactes : plus proche multiple de 5, demi vers le haut."""
        for ht in range(0, 2005, 5):
            for taux in range(0, 101):
                exact = Fraction(ht * taux, 100)
                attendu = int((exact / 5 + Fraction(1, 2)) // 1) * 5
                tva = services.calculer_tva(ht, taux)
                if tva != attendu:
                    self.fail(f"HT {ht} à {taux} % : {tva} au lieu de {attendu}")
                self.assertEqual(tva % 5, 0)
                self.assertLessEqual(abs(tva - exact), Fraction(5, 2))

    def test_taux_zero_et_cent(self):
        self.assertEqual(services.calculer_totaux([400_000], 0), (400_000, 0, 400_000))
        self.assertEqual(services.calculer_totaux([400_000], 100), (400_000, 400_000, 800_000))
        self.assertEqual(services.calculer_totaux([5], 100), (5, 5, 10))

    def test_grands_montants_sans_perte(self):
        ht = PRIX_UNITAIRE_MAX * QUANTITE_MAX
        self.assertEqual(services.calculer_tva(ht, 18), ht * 18 // 100)

    def test_entrees_non_entieres_refusees(self):
        for valeur in (2.5, Decimal("25"), "25", True, None):
            with self.subTest(valeur=valeur), self.assertRaises(MontantInvalide):
                services.calculer_tva(valeur, 18)
        for taux in (-1, 101, 18.0, Decimal("18"), True):
            with self.subTest(taux=taux), self.assertRaises(MontantInvalide):
                services.calculer_tva(400_000, taux)
        with self.assertRaises(MontantInvalide):
            services.arrondir_au_multiple_de_5(-5, 100)


class QuantitePrixTests(Base):
    def test_quantites_invalides(self):
        for quantite in (0, -1, 1.5, Decimal("2"), "2", True, None, QUANTITE_MAX + 1):
            with self.subTest(quantite=quantite), self.assertRaises(MontantInvalide):
                services.verifier_quantite(quantite)
        self.assertEqual(services.verifier_quantite(1), 1)
        self.assertEqual(services.verifier_quantite(QUANTITE_MAX), QUANTITE_MAX)

    def test_prix_invalides(self):
        for prix in (0, -5, 3, 7, 12.5, 10.0, Decimal("10"), "10", True, None, PRIX_UNITAIRE_MAX + 5):
            with self.subTest(prix=prix), self.assertRaises(MontantInvalide):
                services.verifier_prix_unitaire(prix)
        for prix in (5, 10, 125_000, PRIX_UNITAIRE_MAX):
            self.assertEqual(services.verifier_prix_unitaire(prix), prix)

    def test_ligne_invalide_refusee_et_document_inchange(self):
        doc = self.brouillon()
        for quantite, prix in ((0, 1000), (1, 1002), (1, 0), (1.5, 1000)):
            with self.subTest(quantite=quantite, prix=prix), self.assertRaises(MontantInvalide):
                services.ajouter_ligne(doc, self.user, "X", quantite, prix)
        doc.refresh_from_db()
        self.assertEqual(doc.lignes.count(), 2)
        self.assertEqual(doc.total_ht, 400_000)

    def test_validateurs_de_saisie(self):
        produit = Produit(designation="Câble", prix_unitaire=1002)
        with self.assertRaises(ValidationError) as ctx:
            produit.full_clean()
        self.assertIn("prix_unitaire", ctx.exception.message_dict)
        ligne = LigneDocument(document=self.brouillon(), rang=9, designation="X", quantite=0, prix_unitaire=7, total=0)
        with self.assertRaises(ValidationError) as ctx:
            ligne.full_clean()
        self.assertIn("quantite", ctx.exception.message_dict)
        self.assertIn("prix_unitaire", ctx.exception.message_dict)

    def test_la_base_refuse_un_prix_non_multiple_de_5_ou_un_total_faux(self):
        doc = self.brouillon()
        ligne = doc.lignes.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LigneDocument.objects.filter(pk=ligne.pk).update(prix_unitaire=125_002, total=250_004)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LigneDocument.objects.filter(pk=ligne.pk).update(total=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Produit.objects.bulk_create([Produit(designation="X", prix_unitaire=7)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=doc.pk).update(total_ttc=1)


# ---------------------------------------------------------------------------
# Brouillons et lignes
# ---------------------------------------------------------------------------

class BrouillonTests(Base):
    def test_devis_cree_sans_intervention_reprend_le_profil(self):
        profil = ProfilEmetteur.get()
        profil.taux_tva_defaut, profil.validite_devis_jours = 18, 30
        profil.save()
        doc = self.brouillon()
        self.assertEqual((doc.type, doc.statut, doc.numero), (T.DEVIS, S.BROUILLON, None))
        self.assertEqual(doc.taux_tva, 18)
        self.assertEqual(doc.validite_jours, 30)
        self.assertEqual((doc.total_ht, doc.total_tva, doc.total_ttc), (400_000, 72_000, 472_000))
        self.assertEqual([l.rang for l in doc.lignes.all()], [1, 2])
        self.assertEqual(doc.lignes.get(rang=1).total, 250_000)
        self.assertEqual(doc.cree_par, self.user)
        self.assertTrue(ActivityLog.objects.filter(action="creation_document", object_id=str(doc.pk)).exists())

    def test_taux_et_validite_suivent_le_profil_au_moment_de_la_creation(self):
        profil = ProfilEmetteur.get()
        profil.taux_tva_defaut, profil.validite_devis_jours = 0, 45
        profil.save()
        doc = self.brouillon()
        self.assertEqual((doc.taux_tva, doc.validite_jours), (0, 45))
        self.assertEqual((doc.total_ht, doc.total_tva, doc.total_ttc), (400_000, 0, 400_000))
        profil.taux_tva_defaut = 18
        profil.save()
        doc.refresh_from_db()
        self.assertEqual(doc.taux_tva, 0)  # un document existant ne suit pas le profil

    def test_facture_sans_validite(self):
        doc = self.brouillon(T.FACTURE)
        self.assertIsNone(doc.validite_jours)
        with self.assertRaises(ErreurFacturation):
            services.modifier_brouillon(doc, self.user, validite_jours=10)

    def test_contact_copie_et_modifiable_en_brouillon(self):
        doc = self.brouillon()
        self.assertEqual((doc.contact_nom, doc.contact_telephone, doc.contact_adresse),
                         ("Societe Alpha", "76 12 34 56", "Bamako"))
        autre = ContactClient.objects.create(nom="Beta", telephone="70", adresse="Kati")
        services.modifier_brouillon(doc, self.user, contact=autre)
        self.assertEqual((doc.contact, doc.contact_nom, doc.contact_adresse), (autre, "Beta", "Kati"))

    def test_taux_et_validite_modifiables_en_brouillon_avec_recalcul(self):
        doc = self.brouillon()
        services.modifier_brouillon(doc, self.user, taux_tva=0, validite_jours=60, objet="Vidéosurveillance")
        self.assertEqual((doc.taux_tva, doc.validite_jours, doc.objet), (0, 60, "Vidéosurveillance"))
        self.assertEqual((doc.total_tva, doc.total_ttc), (0, 400_000))
        for valeurs in ({"taux_tva": 101}, {"taux_tva": -1}, {"validite_jours": 0}, {"numero": "X"}):
            with self.subTest(valeurs=valeurs), self.assertRaises(ErreurFacturation):
                services.modifier_brouillon(doc, self.user, **valeurs)

    def test_totaux_recalcules_apres_chaque_modification_de_lignes(self):
        doc = self.brouillon(lignes=[])
        self.assertEqual((doc.total_ht, doc.total_ttc), (0, 0))
        ligne = services.ajouter_ligne(doc, self.user, "Pose", 1, 1275)
        self.assertEqual((doc.total_ht, doc.total_tva, doc.total_ttc), (1275, 230, 1505))
        services.modifier_ligne(ligne, self.user, quantite=2)
        doc.refresh_from_db()
        self.assertEqual((doc.total_ht, doc.total_tva), (2550, 460))
        services.ajouter_ligne(doc, self.user, "Câble", 3, 5)
        self.assertEqual(doc.total_ht, 2565)
        services.supprimer_ligne(ligne, self.user)
        doc.refresh_from_db()
        self.assertEqual((doc.total_ht, doc.total_tva, doc.total_ttc), (15, 5, 20))
        self.assertEqual([l.rang for l in doc.lignes.all()], [1])
        services.remplacer_lignes(doc, self.user, LIGNES)
        self.assertEqual((doc.total_ht, doc.total_ttc), (400_000, 472_000))

    def test_suppression_de_ligne_renumerote(self):
        doc = self.brouillon(lignes=LIGNES + [{"designation": "Câble", "quantite": 1, "prix_unitaire": 5}])
        services.supprimer_ligne(doc.lignes.get(rang=1), self.user)
        self.assertEqual(list(doc.lignes.values_list("rang", "designation")), [(1, "Pose"), (2, "Câble")])

    def test_ligne_sans_designation_refusee(self):
        with self.assertRaises(ErreurFacturation):
            self.brouillon(lignes=[{"designation": "  ", "quantite": 1, "prix_unitaire": 5}])
        self.assertFalse(Document.objects.exists())  # création entière annulée

    def test_suppression_d_un_brouillon(self):
        doc = self.brouillon()
        pk = doc.pk
        services.supprimer_brouillon(doc, self.user)
        self.assertFalse(Document.objects.filter(pk=pk).exists())
        self.assertFalse(LigneDocument.objects.filter(document_id=pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action="suppression_document", object_id=str(pk)).exists())


class ProduitTests(Base):
    def test_produit_copie_dans_la_ligne_sans_lien_vivant(self):
        produit = services.creer_produit("Caméra bullet", 95_000, self.user)
        doc = self.brouillon(lignes=[])
        ligne = services.ajouter_produit(doc, self.user, produit, quantite=3)
        self.assertEqual((ligne.designation, ligne.prix_unitaire, ligne.total, ligne.produit),
                         ("Caméra bullet", 95_000, 285_000, produit))
        services.modifier_produit(produit, self.user, designation="Autre", prix_unitaire=100_000)
        ligne.refresh_from_db()
        self.assertEqual((ligne.designation, ligne.prix_unitaire), ("Caméra bullet", 95_000))

    def test_prix_produit_valide(self):
        for prix in (0, 7, 9.5):
            with self.subTest(prix=prix), self.assertRaises(MontantInvalide):
                services.creer_produit("X", prix, self.user)
        produit = services.creer_produit("X", 10, self.user)
        with self.assertRaises(MontantInvalide):
            services.modifier_produit(produit, self.user, prix_unitaire=12)

    def test_desactivation_jamais_suppression(self):
        produit = services.creer_produit("Câble", 500, self.user)
        services.changer_activation_produit(produit, False, self.user)
        produit.refresh_from_db()
        self.assertFalse(produit.actif)
        with self.assertRaises(ErreurFacturation):
            services.ajouter_produit(self.brouillon(), self.user, produit)
        with self.assertRaises(ValidationError):
            produit.delete()
        with self.assertRaises(ValidationError):
            Produit.objects.all().delete()
        self.assertTrue(Produit.objects.filter(pk=produit.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action="desactivation_produit").exists())


# ---------------------------------------------------------------------------
# Émission, numérotation
# ---------------------------------------------------------------------------

class EmissionTests(Base):
    def test_emission_fige_le_document(self):
        doc = self.brouillon()
        # Totaux volontairement faux en base : l'émission doit les recalculer.
        Document.objects.filter(pk=doc.pk).update(total_ht=5, total_tva=0, total_ttc=5)
        self.contact.nom, self.contact.telephone, self.contact.adresse = "Alpha SA", "66 00", "Kayes"
        self.contact.save()
        with _localdate(date(2026, 3, 10)):
            services.emettre(doc, self.user)
        self.assertEqual((doc.statut, doc.numero), (S.ENVOYE, "DEV-2026-0001"))
        self.assertEqual((doc.total_ht, doc.total_tva, doc.total_ttc), (400_000, 72_000, 472_000))
        self.assertEqual((doc.contact_nom, doc.contact_telephone, doc.contact_adresse), ("Alpha SA", "66 00", "Kayes"))
        self.assertEqual(doc.date_emission, date(2026, 3, 10))
        self.assertEqual(doc.date_validite, date(2026, 4, 9))  # 10 mars + 30 jours

    def test_contact_fige_apres_emission(self):
        doc = self.document(T.FACTURE, S.EMISE)
        self.contact.nom, self.contact.adresse = "Nouveau nom", "Ségou"
        self.contact.save()
        doc.refresh_from_db()
        self.assertEqual((doc.contact_nom, doc.contact_adresse), ("Societe Alpha", "Bamako"))
        self.assertIsNone(doc.date_validite)

    def test_document_sans_ligne_non_emis(self):
        doc = self.brouillon(lignes=[])
        with self.assertRaises(ErreurFacturation):
            services.emettre(doc, self.user)
        doc.refresh_from_db()
        self.assertEqual((doc.statut, doc.numero), (S.BROUILLON, None))
        self.assertFalse(SequenceNumero.objects.exists())


class NumerotationTests(Base):
    def test_suites_par_type_sans_trou(self):
        with _localdate(date(2026, 5, 1)):
            numeros = [services.emettre(self.brouillon(T.DEVIS), self.user).numero for _ in range(3)]
            factures = [services.emettre(self.brouillon(T.FACTURE), self.user).numero for _ in range(2)]
        self.assertEqual(numeros, ["DEV-2026-0001", "DEV-2026-0002", "DEV-2026-0003"])
        self.assertEqual(factures, ["FAC-2026-0001", "FAC-2026-0002"])

    def test_brouillons_supprimes_ne_consomment_pas_de_numero(self):
        services.supprimer_brouillon(self.brouillon(), self.user)
        with _localdate(date(2026, 5, 1)):
            self.assertEqual(services.emettre(self.brouillon(), self.user).numero, "DEV-2026-0001")

    def test_remise_a_zero_chaque_annee(self):
        with _localdate(date(2026, 12, 31)):
            services.emettre(self.brouillon(), self.user)
            dernier_2026 = services.emettre(self.brouillon(), self.user).numero
        with _localdate(date(2027, 1, 1)):
            premier_2027 = services.emettre(self.brouillon(), self.user).numero
            facture_2027 = services.emettre(self.brouillon(T.FACTURE), self.user).numero
        self.assertEqual((dernier_2026, premier_2027, facture_2027), ("DEV-2026-0002", "DEV-2027-0001", "FAC-2027-0001"))
        self.assertEqual(SequenceNumero.objects.get(type=T.DEVIS, annee=2026).dernier, 2)

    def test_pas_de_trou_si_l_emission_echoue_apres_l_attribution(self):
        doc = self.brouillon()
        with _localdate(date(2026, 5, 1)):
            with mock.patch.object(services, "_historiser", side_effect=RuntimeError("panne")):
                with self.assertRaises(RuntimeError):
                    services.emettre(doc, self.user)
            doc.refresh_from_db()
            self.assertEqual((doc.statut, doc.numero), (S.BROUILLON, None))
            self.assertEqual(services.emettre(doc, self.user).numero, "DEV-2026-0001")

    def test_la_base_refuse_un_numero_en_double(self):
        doc = self.document(T.DEVIS, S.ENVOYE)
        autre = self.brouillon()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=autre.pk).update(statut=S.ENVOYE, numero=doc.numero)

    def test_la_base_refuse_un_brouillon_numerote_ou_un_emis_sans_numero(self):
        brouillon = self.brouillon()
        emis = self.document(T.DEVIS, S.ENVOYE)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=brouillon.pk).update(numero="DEV-2099-0001")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=emis.pk).update(numero=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.filter(pk=emis.pk).update(statut=S.EMISE)  # statut de facture sur un devis


@skipUnlessDBFeature("has_select_for_update")
class ConcurrenceTests(TransactionTestCase):
    """Vrais accès simultanés (threads, une connexion chacun). Ignoré sur SQLite (pas de verrou de ligne)."""

    NB = 8

    def setUp(self):
        self.user = User.objects.create_user(username="factu", password="x", role=User.Role.MANAGER)
        self.contact = ContactClient.objects.create(nom="Alpha")

    def _en_parallele(self, fonction, arguments):
        barriere = threading.Barrier(len(arguments))
        resultats, erreurs = [], []

        def tache(argument):
            try:
                barriere.wait()
                resultats.append(fonction(argument))
            except ErreurFacturation as exc:
                erreurs.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=tache, args=(a,)) for a in arguments]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return resultats, erreurs

    def test_numerotation_simultanee_sans_trou_ni_doublon(self):
        # Aucune séquence au départ : la création concurrente de la première ligne est aussi testée.
        self.assertFalse(SequenceNumero.objects.exists())
        brouillons = [services.creer_brouillon(T.DEVIS, self.contact, self.user, lignes=LIGNES) for _ in range(self.NB)]
        with _localdate(date(2026, 6, 1)):
            resultats, erreurs = self._en_parallele(lambda doc: services.emettre(doc, self.user).numero, brouillons)
        self.assertEqual(erreurs, [])
        self.assertEqual(sorted(resultats), [f"DEV-2026-{i:04d}" for i in range(1, self.NB + 1)])
        self.assertEqual(SequenceNumero.objects.get(type=T.DEVIS, annee=2026).dernier, self.NB)
        self.assertEqual(HistoriqueStatut.objects.filter(nouveau_statut=S.ENVOYE).count(), self.NB)

    def test_numerotation_simultanee_sur_une_sequence_existante(self):
        SequenceNumero.objects.create(type=T.FACTURE, annee=2026, dernier=41)
        brouillons = [services.creer_brouillon(T.FACTURE, self.contact, self.user, lignes=LIGNES) for _ in range(self.NB)]
        with _localdate(date(2026, 6, 1)):
            resultats, erreurs = self._en_parallele(lambda doc: services.emettre(doc, self.user).numero, brouillons)
        self.assertEqual(erreurs, [])
        self.assertEqual(sorted(resultats), [f"FAC-2026-{i:04d}" for i in range(42, 42 + self.NB)])

    def test_conversion_simultanee_une_seule_facture(self):
        devis = services.creer_brouillon(T.DEVIS, self.contact, self.user, lignes=LIGNES)
        services.changer_statut(devis, S.ENVOYE, self.user)
        services.changer_statut(devis, S.ACCEPTE, self.user)
        resultats, erreurs = self._en_parallele(lambda _: services.convertir_en_facture(devis, self.user), range(4))
        self.assertEqual(len(resultats), 1)
        self.assertEqual(len(erreurs), 3)
        self.assertTrue(all(isinstance(e, ConversionImpossible) for e in erreurs))
        self.assertEqual(Document.objects.filter(source=devis).count(), 1)


# ---------------------------------------------------------------------------
# Cycle de vie
# ---------------------------------------------------------------------------

AUTORISEES = {
    (T.DEVIS, S.BROUILLON, S.ENVOYE), (T.DEVIS, S.ENVOYE, S.ACCEPTE), (T.DEVIS, S.ENVOYE, S.REFUSE),
    (T.FACTURE, S.BROUILLON, S.EMISE), (T.FACTURE, S.EMISE, S.PAYEE), (T.FACTURE, S.EMISE, S.ANNULEE),
}
STATUTS = {T.DEVIS: [S.BROUILLON, S.ENVOYE, S.ACCEPTE, S.REFUSE], T.FACTURE: [S.BROUILLON, S.EMISE, S.PAYEE, S.ANNULEE]}


class TransitionsTests(Base):
    def test_chaque_transition_autorisee(self):
        for type_document, depart, arrivee in sorted(AUTORISEES):
            with self.subTest(type=type_document, depart=depart, arrivee=arrivee):
                doc = self.document(type_document, depart)
                services.changer_statut(doc, arrivee, self.user)
                self.assertEqual(doc.statut, arrivee)
                derniere = doc.historique.last()
                self.assertEqual((derniere.ancien_statut, derniere.nouveau_statut, derniere.utilisateur),
                                 (depart, arrivee, self.user))

    def test_chaque_transition_interdite(self):
        tous = list(S.values) + ["inconnu"]
        for type_document, statuts in STATUTS.items():
            for depart in statuts:
                for arrivee in tous:
                    if (type_document, depart, arrivee) in AUTORISEES:
                        continue
                    with self.subTest(type=type_document, depart=depart, arrivee=arrivee):
                        doc = self.document(type_document, depart)
                        nb_historique = doc.historique.count()
                        with self.assertRaises(TransitionInterdite):
                            services.changer_statut(doc, arrivee, self.user)
                        doc.refresh_from_db()
                        self.assertEqual(doc.statut, depart)
                        self.assertEqual(doc.historique.count(), nb_historique)

    def test_historique_a_chaque_etape(self):
        doc = self.brouillon(T.FACTURE)
        services.emettre(doc, self.user)
        services.changer_statut(doc, S.PAYEE, self.user)
        self.assertEqual(
            list(doc.historique.values_list("ancien_statut", "nouveau_statut")),
            [("", S.BROUILLON), (S.BROUILLON, S.EMISE), (S.EMISE, S.PAYEE)],
        )
        self.assertEqual(ActivityLog.objects.filter(action="transition_document", object_id=str(doc.pk)).count(), 2)


class ImmutabiliteTests(Base):
    def test_document_emis_non_modifiable_par_les_services(self):
        for statut in (S.ENVOYE, S.ACCEPTE, S.REFUSE, S.EMISE, S.PAYEE, S.ANNULEE):
            type_document = T.DEVIS if statut in STATUTS[T.DEVIS] else T.FACTURE
            with self.subTest(statut=statut):
                doc = self.document(type_document, statut)
                ligne = doc.lignes.first()
                avant = (doc.total_ttc, doc.taux_tva, doc.lignes.count())
                appels = [
                    lambda: services.modifier_brouillon(doc, self.user, taux_tva=0),
                    lambda: services.modifier_brouillon(doc, self.user, objet="Autre"),
                    lambda: services.ajouter_ligne(doc, self.user, "X", 1, 5),
                    lambda: services.modifier_ligne(ligne, self.user, quantite=9),
                    lambda: services.supprimer_ligne(ligne, self.user),
                    lambda: services.remplacer_lignes(doc, self.user, []),
                    lambda: services.supprimer_brouillon(doc, self.user),
                ]
                for appel in appels:
                    with self.assertRaises(DocumentNonModifiable):
                        appel()
                doc.refresh_from_db()
                self.assertEqual((doc.total_ttc, doc.taux_tva, doc.lignes.count()), avant)

    def test_document_emis_protege_au_niveau_du_modele(self):
        doc = self.document(T.FACTURE, S.EMISE)
        ligne = doc.lignes.first()
        doc.objet = "Modifié en douce"
        with self.assertRaises(DocumentNonModifiable):
            doc.save()
        doc.refresh_from_db()
        doc.taux_tva = 0
        with self.assertRaises(DocumentNonModifiable):
            doc.save()
        doc.refresh_from_db()
        with self.assertRaises(DocumentNonModifiable):
            doc.delete()
        with self.assertRaises(DocumentNonModifiable):
            Document.objects.filter(pk=doc.pk).delete()
        ligne.quantite = 9
        with self.assertRaises(DocumentNonModifiable):
            ligne.save()
        with self.assertRaises(DocumentNonModifiable):
            ligne.delete()
        with self.assertRaises(DocumentNonModifiable):
            LigneDocument.objects.filter(document=doc).delete()
        with self.assertRaises(DocumentNonModifiable):
            LigneDocument.objects.create(document=doc, rang=9, designation="X", quantite=1, prix_unitaire=5, total=5)
        self.assertTrue(Document.objects.filter(pk=doc.pk, objet="").exists())

    def test_seuls_les_brouillons_se_suppriment_en_masse(self):
        self.brouillon()
        self.document(T.DEVIS, S.ENVOYE)
        with self.assertRaises(DocumentNonModifiable):
            Document.objects.all().delete()
        self.assertEqual(Document.objects.count(), 2)
        Document.objects.filter(statut=S.BROUILLON).delete()
        self.assertEqual(Document.objects.count(), 1)


# ---------------------------------------------------------------------------
# Expiration, conversion, duplication
# ---------------------------------------------------------------------------

class ExpirationTests(Base):
    def _devis_envoye_le(self, jour):
        doc = self.brouillon()
        with _localdate(jour):
            services.emettre(doc, self.user)
        return doc  # validité de 30 jours (profil par défaut)

    def test_expiration_calculee_jamais_stockee(self):
        doc = self._devis_envoye_le(date(2026, 1, 1))  # valable jusqu'au 31 janvier
        with mock.patch("facturation.models.timezone.localdate", return_value=date(2026, 1, 31)):
            self.assertFalse(doc.est_expire)
            self.assertNotIn(doc, Document.objects.expires())
        with mock.patch("facturation.models.timezone.localdate", return_value=date(2026, 2, 1)):
            self.assertTrue(doc.est_expire)
            self.assertIn(doc, Document.objects.expires())
        self.assertEqual(Document.objects.get(pk=doc.pk).statut, S.ENVOYE)

    def test_seul_un_devis_envoye_expire(self):
        accepte = self.document(T.DEVIS, S.ACCEPTE)
        facture = self.document(T.FACTURE, S.EMISE)
        brouillon = self.brouillon()
        with mock.patch("facturation.models.timezone.localdate", return_value=date(2099, 1, 1)):
            for doc in (accepte, facture, brouillon):
                self.assertFalse(doc.est_expire)
            self.assertFalse(Document.objects.expires().exists())

    def test_devis_expire_peut_encore_etre_accepte_ou_refuse(self):
        for arrivee in (S.ACCEPTE, S.REFUSE):
            with self.subTest(arrivee=arrivee):
                doc = self._devis_envoye_le(date(2020, 1, 1))
                self.assertTrue(doc.est_expire)
                services.changer_statut(doc, arrivee, self.user)
                self.assertEqual(doc.statut, arrivee)
                self.assertFalse(doc.est_expire)


class ConversionTests(Base):
    def test_devis_accepte_devient_facture_brouillon(self):
        devis = self.brouillon(objet="Vidéosurveillance", lieu_livraison="Agence ACI")
        services.modifier_brouillon(devis, self.user, taux_tva=10)
        services.emettre(devis, self.user)
        services.changer_statut(devis, S.ACCEPTE, self.user)
        avant = Document.objects.filter(pk=devis.pk).values().get()
        profil = ProfilEmetteur.get()
        profil.taux_tva_defaut = 18
        profil.save()

        facture = services.convertir_en_facture(devis, self.user)

        self.assertEqual((facture.type, facture.statut, facture.numero, facture.source), (T.FACTURE, S.BROUILLON, None, devis))
        self.assertEqual((facture.objet, facture.lieu_livraison, facture.contact), ("Vidéosurveillance", "Agence ACI", self.contact))
        self.assertEqual(facture.taux_tva, 10)  # taux du devis, pas du profil
        self.assertIsNone(facture.validite_jours)
        self.assertEqual(
            list(facture.lignes.values_list("rang", "designation", "quantite", "prix_unitaire", "total")),
            list(devis.lignes.values_list("rang", "designation", "quantite", "prix_unitaire", "total")),
        )
        self.assertEqual((facture.total_ht, facture.total_tva, facture.total_ttc), (400_000, 40_000, 440_000))
        self.assertEqual(Document.objects.filter(pk=devis.pk).values().get(), avant)  # devis intact
        self.assertEqual(list(facture.historique.values_list("ancien_statut", "nouveau_statut")), [("", S.BROUILLON)])
        self.assertTrue(ActivityLog.objects.filter(action="conversion_devis", object_id=str(facture.pk)).exists())

    def test_seul_un_devis_accepte_se_convertit(self):
        for type_document, statut in [(T.DEVIS, S.BROUILLON), (T.DEVIS, S.ENVOYE), (T.DEVIS, S.REFUSE),
                                      (T.FACTURE, S.EMISE)]:
            with self.subTest(type=type_document, statut=statut), self.assertRaises(ConversionImpossible):
                services.convertir_en_facture(self.document(type_document, statut), self.user)

    def test_une_seule_facture_active_et_l_annulation_libere_le_devis(self):
        devis = self.document(T.DEVIS, S.ACCEPTE)
        premiere = services.convertir_en_facture(devis, self.user)
        with self.assertRaises(ConversionImpossible):
            services.convertir_en_facture(devis, self.user)  # facture brouillon en cours
        services.emettre(premiere, self.user)
        with self.assertRaises(ConversionImpossible):
            services.convertir_en_facture(devis, self.user)  # facture émise
        services.changer_statut(premiere, S.ANNULEE, self.user)
        seconde = services.convertir_en_facture(devis, self.user)
        self.assertEqual(services.facture_active(devis), seconde)
        services.emettre(seconde, self.user)
        services.changer_statut(seconde, S.PAYEE, self.user)
        with self.assertRaises(ConversionImpossible):
            services.convertir_en_facture(devis, self.user)  # facture payée
        self.assertEqual(devis.factures.count(), 2)

    def test_supprimer_la_facture_brouillon_libere_le_devis(self):
        devis = self.document(T.DEVIS, S.ACCEPTE)
        services.supprimer_brouillon(services.convertir_en_facture(devis, self.user), self.user)
        self.assertIsNotNone(services.convertir_en_facture(devis, self.user))

    def test_devis_source_protege(self):
        devis = self.document(T.DEVIS, S.ACCEPTE)
        services.convertir_en_facture(devis, self.user)
        with self.assertRaises(DocumentNonModifiable):
            devis.delete()


class DuplicationTests(Base):
    def test_dupliquer_un_devis_emis(self):
        original = self.brouillon(objet="Objet", lieu_livraison="Lieu")
        services.emettre(original, self.user)
        profil = ProfilEmetteur.get()
        profil.taux_tva_defaut, profil.validite_devis_jours = 0, 15
        profil.save()

        copie = services.dupliquer(original, self.user)

        self.assertNotEqual(copie.pk, original.pk)
        self.assertEqual((copie.type, copie.statut, copie.numero, copie.source), (T.DEVIS, S.BROUILLON, None, None))
        self.assertEqual((copie.objet, copie.lieu_livraison, copie.contact), ("Objet", "Lieu", self.contact))
        self.assertEqual((copie.taux_tva, copie.validite_jours), (0, 15))  # repris du profil
        self.assertEqual(list(copie.lignes.values_list("designation", "quantite", "prix_unitaire")),
                         list(original.lignes.values_list("designation", "quantite", "prix_unitaire")))
        self.assertEqual((copie.total_ttc, copie.date_emission), (400_000, None))
        original.refresh_from_db()
        self.assertEqual(original.statut, S.ENVOYE)
        self.assertEqual(original.lignes.count(), 2)
        self.assertEqual(list(copie.historique.values_list("ancien_statut", "nouveau_statut")), [("", S.BROUILLON)])
        self.assertTrue(ActivityLog.objects.filter(action="duplication_document", object_id=str(copie.pk)).exists())

    def test_dupliquer_une_facture_issue_d_un_devis_n_a_pas_de_source(self):
        devis = self.document(T.DEVIS, S.ACCEPTE)
        facture = services.convertir_en_facture(devis, self.user)
        copie = services.dupliquer(facture, self.user)
        self.assertEqual((copie.type, copie.source, copie.validite_jours), (T.FACTURE, None, None))
        # La copie ne compte pas comme facture du devis.
        self.assertEqual(services.facture_active(devis), facture)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminTests(Base):
    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = User.objects.create_superuser(username="root", password="x")
        self.document_admin = admin.site._registry[Document]

    def test_documents_non_brouillon_en_lecture_seule_sans_suppression(self):
        brouillon = self.brouillon()
        emis = self.document(T.FACTURE, S.EMISE)
        self.assertFalse(self.document_admin.has_add_permission(self.request))
        self.assertTrue(self.document_admin.has_change_permission(self.request, brouillon))
        self.assertFalse(self.document_admin.has_change_permission(self.request, emis))
        self.assertTrue(self.document_admin.has_view_permission(self.request, emis))
        for doc in (brouillon, emis):
            self.assertFalse(self.document_admin.has_delete_permission(self.request, doc))
        for modele in (SequenceNumero, HistoriqueStatut):
            modele_admin = admin.site._registry[modele]
            self.assertFalse(modele_admin.has_change_permission(self.request))
            self.assertFalse(modele_admin.has_delete_permission(self.request))
        self.assertFalse(admin.site._registry[Produit].has_delete_permission(self.request))

    def test_modification_d_un_brouillon_par_l_admin_passe_par_le_service(self):
        doc = self.brouillon()
        self.client.force_login(self.request.user)
        url = f"/admin/facturation/document/{doc.pk}/change/"
        response = self.client.post(url, {
            "contact": self.contact.pk, "objet": "Par l'admin", "lieu_livraison": "", "taux_tva": 0,
            "validite_jours": 30,
            "lignes-TOTAL_FORMS": 2, "lignes-INITIAL_FORMS": 2, "lignes-MIN_NUM_FORMS": 0, "lignes-MAX_NUM_FORMS": 1000,
            "historique-TOTAL_FORMS": 1, "historique-INITIAL_FORMS": 1,
            "historique-MIN_NUM_FORMS": 0, "historique-MAX_NUM_FORMS": 1000,
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context.get("errors"))
        doc.refresh_from_db()
        self.assertEqual((doc.objet, doc.taux_tva, doc.total_tva, doc.total_ttc), ("Par l'admin", 0, 0, 400_000))
        self.assertTrue(ActivityLog.objects.filter(action="modification_document", object_id=str(doc.pk)).exists())
