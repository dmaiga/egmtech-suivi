"""Garde-fous contre les requêtes N+1 : le nombre de requêtes d'une page liste
ne doit pas augmenter avec le nombre de sites, missions ou visites."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clients.models import Client, Site
from forms_cms.models import AttachedForm, FormTemplate
from visits.models import Mission, Visit, VisitPhoto

from .tests import SIMPLE_SCHEMA


class PasDeRequetesNPlusUnTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("mgr", password="x", role=User.Role.MANAGER, is_superuser=True)
        self.sup = User.objects.create_user("sup", password="x", role=User.Role.SUPERVISEUR)
        self.client_obj = Client.objects.create(nom="Banque")
        self.client_user = User.objects.create_user("cli", password="x", role=User.Role.CLIENT, client=self.client_obj)
        template = FormTemplate.objects.create(nom="T", schema=SIMPLE_SCHEMA, actif=True)
        self.form = AttachedForm.objects.create(client=self.client_obj, template=template, nom="F", schema=SIMPLE_SCHEMA)
        self.n = 0

    def _ajouter(self, nombre):
        for _ in range(nombre):
            self.n += 1
            site = Site.objects.create(client=self.client_obj, code=str(self.n), nom=f"Site {self.n}")
            mission = Mission.objects.create(superviseur=self.sup, site=site, attached_form=self.form, created_by=self.manager)
            for statut in (Visit.Statut.SOUMISE, Visit.Statut.PUBLIEE):
                visit = Visit.objects.create(mission=mission, auteur=self.sup, statut=statut, date_debut=timezone.now())
                VisitPhoto.objects.create(visit=visit, field_key="photo", image="visites/photos/x.jpg")

    def _requetes(self, user, url):
        self.client.force_login(user)
        self.client.get(url)  # premier appel : caches de session, permissions...
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(ctx.captured_queries)

    def test_nombre_de_requetes_constant(self):
        pages = [
            (self.manager, reverse("visits:mission-list")),
            (self.manager, reverse("revue:list")),
            (self.manager, reverse("clients:detail", args=[self.client_obj.pk])),
            (self.sup, reverse("visits:mission-list")),
            (self.sup, reverse("my-visits")),
            (self.client_user, reverse("portal:dashboard")),
            (self.client_user, reverse("portal:visit-list")),
        ]
        self._ajouter(2)
        avant = {url + user.username: self._requetes(user, url) for user, url in pages}
        self._ajouter(8)
        for user, url in pages:
            with self.subTest(page=url, user=user.username):
                self.assertEqual(self._requetes(user, url), avant[url + user.username])
