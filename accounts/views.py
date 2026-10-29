from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from visits.models import Mission, Visit
from core.services import log
from .forms import AuditorCreationForm
from .models import User


@login_required
def auditor_list(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    auditors = User.objects.filter(role=User.Role.SUPERVISEUR).order_by("last_name", "first_name", "username")
    return render(request, "accounts/auditor_list.html", {"page_obj": Paginator(auditors, 20).get_page(request.GET.get("page"))})


@login_required
def auditor_detail(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    auditor = get_object_or_404(User, pk=pk, role=User.Role.SUPERVISEUR)
    missions = Mission.objects.filter(superviseur=auditor).select_related("site", "site__client", "attached_form").order_by("-created_at")
    return render(request, "accounts/auditor_detail.html", {"auditor": auditor, "missions": missions[:10], "mission_count": missions.count()})


@login_required
def auditor_create(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = AuditorCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        auditor = form.save()
        log(request.user, "creation_auditeur", auditor)
        messages.success(request, f"Auditeur {auditor.get_full_name()} créé. Il peut maintenant recevoir des missions.")
        return redirect("accounts:auditor-detail", pk=auditor.pk)
    return render(request, "accounts/auditor_form.html", {"form": form})


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
