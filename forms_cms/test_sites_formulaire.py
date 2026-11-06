"""Formulaire attaché à certains sites seulement d'un client."""

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from clients.models import Client, Site
from forms_cms.models import AttachedForm, ExpectedVisits, FormTemplate
from forms_cms.services import attach_template_to_client
from visits.models import Mission

SCHEMA = {"sections": [{"title": "S", "fields": [{"key": "a", "label": "A", "type": "text", "required": False}]}]}


class FormulaireParSiteTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="mgr", password="x", role=User.Role.MANAGER)
        self.manager.user_permissions.add(Permission.objects.get(codename="manage_forms"))
        self.auditeur = User.objects.create_user(username="aud", password="x", role=User.Role.SUPERVISEUR)
        self.client.force_login(self.manager)
        self.banque = Client.objects.create(nom="Banque")
        self.s1, self.s2, self.s3, self.s4 = (
            Site.objects.create(client=self.banque, code=f"S{i}", nom=f"Site {i}") for i in range(1, 5)
        )
        self.audit = FormTemplate.objects.create(nom="Audit", schema=SCHEMA)
        self.suivi = FormTemplate.objects.create(nom="Suivi", schema=SCHEMA)
        self.autre = Client.objects.create(nom="Autre")
        self.site_autre = Site.objects.create(client=self.autre, code="X", nom="Site autre client")
        self.attach_url = reverse("forms_cms:client-attach", args=[self.banque.pk])

    def _attacher(self, template, sites=None):
        data = {"template_id": template.pk, "perimetre": "1"}
        if sites is None:
            data["tous_les_sites"] = "1"
        else:
            data["sites"] = [s.pk for s in sites]
        self.client.post(self.attach_url, data)
        return AttachedForm.objects.get(client=self.banque, template=template)

    def _creer_missions(self, attached, sites):
        return self.client.post(reverse("visits:mission-create"), {
            "superviseur": self.auditeur.pk, "client_id": self.banque.pk,
            "attached_form": attached.pk, "sites": [s.pk for s in sites],
        })

    def test_audit_sur_un_site_et_suivi_sur_trois(self):
        audit = self._attacher(self.audit, [self.s1])
        suivi = self._attacher(self.suivi, [self.s2, self.s3, self.s4])
        self.assertFalse(audit.tous_les_sites)
        self.assertEqual(list(audit.sites_concernes()), [self.s1])
        self.assertEqual(set(suivi.sites_concernes()), {self.s2, self.s3, self.s4})

        response = self._creer_missions(audit, [self.s2])
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "n&#x27;est pas prévu pour : Site 2", status_code=400)
        self.assertFalse(Mission.objects.exists())

        self.assertEqual(self._creer_missions(audit, [self.s1]).status_code, 302)
        self.assertEqual(self._creer_missions(suivi, [self.s2, self.s3]).status_code, 302)
        self.assertEqual(Mission.objects.count(), 3)

    def test_par_defaut_tous_les_sites_y_compris_les_nouveaux(self):
        attached = self._attacher(self.audit)
        self.assertTrue(attached.tous_les_sites)
        nouveau = Site.objects.create(client=self.banque, code="S5", nom="Site 5")
        self.assertIn(nouveau, attached.sites_concernes())
        restreint = self._attacher(self.suivi, [self.s1])
        self.assertNotIn(nouveau, restreint.sites_concernes())

    def test_aucun_site_coche_refuse(self):
        self.client.post(self.attach_url, {"template_id": self.audit.pk, "perimetre": "1"})
        self.assertFalse(AttachedForm.objects.exists())

    def test_site_dun_autre_client_ignore(self):
        self.client.post(self.attach_url, {"template_id": self.audit.pk, "perimetre": "1", "sites": [self.s1.pk, self.site_autre.pk]})
        attached = AttachedForm.objects.get(client=self.banque)
        self.assertEqual(list(attached.sites.all()), [self.s1])
        self.assertFalse(attached.concerne(self.site_autre))

    def _url(self, name, attached, *extra):
        return reverse(f"forms_cms:{name}", args=[self.banque.pk, attached.pk, *extra])

    def test_retirer_un_site_supprime_sa_prevision(self):
        attached = self._attacher(self.audit)
        self.client.post(self._url("expected-update", attached),
                         {f"nombre_prevu_{self.s1.pk}": "1", f"nombre_prevu_{self.s2.pk}": "1"})
        self.client.post(self._url("attached-site-remove", attached, self.s2.pk))
        attached.refresh_from_db()
        self.assertFalse(attached.tous_les_sites)  # « tous » devient la liste moins ce site
        self.assertEqual(set(attached.sites.all()), {self.s1, self.s3, self.s4})
        self.assertEqual(list(ExpectedVisits.objects.filter(attached_form=attached).values_list("site_id", flat=True)), [self.s1.pk])

    def test_dernier_site_ne_peut_pas_etre_retire(self):
        attached = self._attacher(self.audit, [self.s1])
        self.client.post(self._url("attached-site-remove", attached, self.s1.pk))
        self.assertEqual(list(attached.sites.all()), [self.s1])

    def test_retirer_site_dun_autre_client_404(self):
        attached = self._attacher(self.audit, [self.s1, self.s2])
        response = self.client.post(self._url("attached-site-remove", attached, self.site_autre.pk))
        self.assertEqual(response.status_code, 404)

    def test_ajouter_des_sites(self):
        attached = self._attacher(self.audit, [self.s1])
        self.client.post(self._url("attached-sites-add", attached), {"sites": [self.s3.pk, self.site_autre.pk]})
        self.assertEqual(set(attached.sites.all()), {self.s1, self.s3})
        self.client.post(self._url("attached-sites-add", attached), {"tous_les_sites": "1"})
        attached.refresh_from_db()
        self.assertTrue(attached.tous_les_sites)

    def test_supprimer_sans_mission_archiver_avec_missions(self):
        attached = self._attacher(self.audit, [self.s1])
        response = self.client.get(reverse("clients:detail", args=[self.banque.pk]))
        self.assertContains(response, self._url("attached-delete", attached))
        self.assertNotContains(response, "Désactiver pour ce client")

        Mission.objects.create(superviseur=self.auditeur, site=self.s1, attached_form=attached, created_by=self.manager)
        response = self.client.get(reverse("clients:detail", args=[self.banque.pk]))
        self.assertNotContains(response, self._url("attached-delete", attached))
        self.assertContains(response, "Archiver")
        self.client.post(self._url("attached-delete", attached))
        self.assertTrue(AttachedForm.objects.filter(pk=attached.pk).exists())

        Mission.objects.all().delete()
        self.client.post(self._url("attached-delete", attached))
        self.assertFalse(AttachedForm.objects.filter(pk=attached.pk).exists())

    def test_supprimer_formulaire_dun_autre_client_404(self):
        autre_form = attach_template_to_client(self.manager, self.autre, self.audit)
        response = self.client.post(reverse("forms_cms:attached-delete", args=[self.banque.pk, autre_form.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(AttachedForm.objects.filter(pk=autre_form.pk).exists())

    def test_previsions_seules_ne_changent_pas_les_sites(self):
        attached = attach_template_to_client(self.manager, self.banque, self.audit, [self.s1, self.s2])
        url = reverse("forms_cms:expected-update", args=[self.banque.pk, attached.pk])
        self.client.post(url, {f"nombre_prevu_{self.s1.pk}": "1"})
        attached.refresh_from_db()
        self.assertEqual(set(attached.sites.all()), {self.s1, self.s2})

    def test_options_de_mission_limitees_aux_sites_du_formulaire(self):
        audit = self._attacher(self.audit, [self.s1])
        self._attacher(self.suivi, [self.s2, self.s3])
        url = reverse("visits:mission-options")
        response = self.client.get(url, {"client_id": self.banque.pk, "attached_form": audit.pk})
        sites = [site.pk for _, groupe in response.context["groupes"] for site in groupe]
        self.assertEqual(sites, [self.s1.pk])
        # Formulaire d'un autre client : ignoré, on retombe sur la liste complète du client.
        autre_form = attach_template_to_client(self.manager, self.autre, self.audit)
        response = self.client.get(url, {"client_id": self.banque.pk, "attached_form": autre_form.pk})
        sites = {site.pk for _, groupe in response.context["groupes"] for site in groupe}
        self.assertEqual(sites, {self.s1.pk, self.s2.pk, self.s3.pk, self.s4.pk})

    def test_fiche_client_naffiche_que_les_sites_du_formulaire(self):
        attached = self._attacher(self.audit, [self.s1])
        response = self.client.get(reverse("clients:detail", args=[self.banque.pk]))
        self.assertContains(response, "1 site")
        self.assertContains(response, f'name="nombre_prevu_{self.s1.pk}"')
        self.assertNotContains(response, f'name="nombre_prevu_{self.s2.pk}"')
        self.assertContains(response, f'sites-dialog-{attached.pk}')  # bouton « Ajouter un site »
        self.assertNotContains(response, self._url("attached-site-remove", attached, self.s1.pk))  # dernier site
