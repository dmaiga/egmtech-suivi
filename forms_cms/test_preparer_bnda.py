from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from clients.models import Client, Site
from forms_cms.models import AttachedForm, ExpectedVisits
from visits.models import Mission


class PreparerBndaTests(TestCase):
    def setUp(self):
        call_command("installer_formulaire_bnda", verbosity=0)
        self.manager = get_user_model().objects.create_user("chef", email="chef@egmtech.co", role="manager")
        self.bnda = Client.objects.create(nom="BNDA")
        self.medine = Site.objects.create(client=self.bnda, code="03", nom="Médine")
        self.kati = Site.objects.create(client=self.bnda, code="16", nom="Kati")
        self.autre = Client.objects.create(nom="Autre banque")
        self.site_autre = Site.objects.create(client=self.autre, code="03", nom="Médine")

    def _run(self, *args):
        call_command("preparer_bnda", "--par", "chef@egmtech.co", *args, stdout=StringIO())

    def test_attache_une_fois_et_prevoit_une_visite_par_agence_sans_mission(self):
        self._run()
        attached = AttachedForm.objects.get(client=self.bnda)
        self.assertEqual(attached.nom, "Audit CCTV BNDA")
        prevues = ExpectedVisits.objects.filter(attached_form=attached)
        self.assertEqual({p.site for p in prevues}, {self.medine, self.kati})
        self.assertTrue(all(p.nombre_prevu == 1 for p in prevues))
        self.assertFalse(Mission.objects.exists())

    def test_relance_sans_doublon_ni_ecrasement(self):
        self._run()
        ExpectedVisits.objects.filter(site=self.kati).update(nombre_prevu=3)
        Site.objects.create(client=self.bnda, code="47", nom="Zégoua")
        self._run()
        self.assertEqual(AttachedForm.objects.filter(client=self.bnda).count(), 1)
        self.assertEqual(ExpectedVisits.objects.get(site=self.kati).nombre_prevu, 3)
        self.assertEqual(ExpectedVisits.objects.filter(site__client=self.bnda).count(), 3)

    def test_ne_touche_pas_a_un_autre_client(self):
        self._run()
        self.assertFalse(AttachedForm.objects.filter(client=self.autre).exists())
        self.assertFalse(ExpectedVisits.objects.filter(site=self.site_autre).exists())

    def test_client_inconnu_refuse(self):
        with self.assertRaises(CommandError):
            self._run("--client", "Inconnu")
