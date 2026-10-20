from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from visits.models import Mission, Visit
from .models import User


def _default_url_for(user):
    if user.is_client():
        return reverse("portal:dashboard")
    return reverse("visits:mission-list")


class RoleAwareLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        return _default_url_for(self.request.user)


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")

    def post(self, request, *args, **kwargs):
        messages.info(request, "Vous avez été déconnecté avec succès.")
        return super().post(request, *args, **kwargs)


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect(_default_url_for(request.user))
    return redirect("accounts:login")


def app_home(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if request.user.is_client():
        return redirect("portal:dashboard")
    if request.user.is_superviseur():
        return redirect("visits:mission-list")

    # Manager / Administrateur : tableau de bord Accueil
    now = timezone.now()
    visites_a_revoir = Visit.objects.filter(statut=Visit.Statut.SOUMISE).count()
    visites_a_corriger = Visit.objects.filter(statut=Visit.Statut.A_CORRIGER).count()
    missions_en_cours = (
        Mission.objects.exclude(visits__statut=Visit.Statut.PUBLIEE).distinct().count()
    )
    visites_publiees_mois = Visit.objects.filter(
        statut=Visit.Statut.PUBLIEE,
        date_soumission__year=now.year,
        date_soumission__month=now.month,
    ).count()

    dernieres_soumises = (
        Visit.objects.filter(statut=Visit.Statut.SOUMISE)
        .select_related(
            "mission",
            "mission__attached_form",
            "mission__site",
            "mission__site__client",
            "auteur",
        )
        .order_by("-date_soumission")[:5]
    )

    context = {
        "visites_a_revoir": visites_a_revoir,
        "visites_a_corriger": visites_a_corriger,
        "missions_en_cours": missions_en_cours,
        "visites_publiees_mois": visites_publiees_mois,
        "dernieres_soumises": dernieres_soumises,
    }
    return render(request, "accounts/app_home.html", context)
