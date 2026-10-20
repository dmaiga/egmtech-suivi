from django.urls import NoReverseMatch, reverse

from accounts.models import User


def _safe_reverse(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


def navigation(request):
    """Context processor fournissant la navigation dynamique selon le rôle."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "nav_items": [],
            "navigation_items": [],
            "user_role_label": "",
        }

    # Libellé lisible du rôle utilisateur
    if user.is_superuser:
        role_label = "Administrateur"
    elif user.role == User.Role.MANAGER:
        role_label = "Manager"
    elif user.role == User.Role.SUPERVISEUR:
        role_label = "Superviseur"
    elif user.role == User.Role.CLIENT:
        role_label = "Client"
    else:
        role_label = "Utilisateur"

    current_path = request.path
    items = []

    # Navigation Manager (et superuser)
    if user.is_superuser or user.role == User.Role.MANAGER:
        # Accueil
        accueil_url = _safe_reverse("app-home")
        if accueil_url:
            items.append({
                "label": "Accueil",
                "url": accueil_url,
                "is_active": current_path == accueil_url,
                "icon": "home",
            })

        # Revue (seulement si permission validate_visits ou superuser)
        if user.is_superuser or user.has_perm("visits.validate_visits"):
            revue_url = _safe_reverse("revue:list")
            if revue_url:
                items.append({
                    "label": "Revue",
                    "url": revue_url,
                    "is_active": current_path.startswith(revue_url),
                    "icon": "clipboard-check",
                })

        # Missions
        missions_url = _safe_reverse("visits:mission-list")
        if missions_url:
            revue_prefix = _safe_reverse("revue:list") or "/app/revue/"
            items.append({
                "label": "Missions",
                "url": missions_url,
                "is_active": (
                    current_path.startswith(missions_url)
                    and not current_path.startswith(revue_prefix)
                ),
                "icon": "briefcase",
            })

        # Clients (seulement si manager ou superuser)
        clients_url = _safe_reverse("clients:list")
        if clients_url:
            items.append({
                "label": "Clients",
                "url": clients_url,
                "is_active": current_path.startswith(clients_url),
                "icon": "users",
            })

        # Formulaires (si permission manage_forms ou superuser)
        if user.is_superuser or user.has_perm("forms_cms.manage_forms"):
            forms_url = _safe_reverse("forms_cms:list")
            if forms_url:
                items.append({
                    "label": "Formulaires",
                    "url": forms_url,
                    "is_active": current_path.startswith(forms_url),
                    "icon": "document-text",
                })

    # Navigation Superviseur
    elif user.role == User.Role.SUPERVISEUR:
        missions_url = _safe_reverse("visits:mission-list")
        if missions_url:
            items.append({
                "label": "Mes missions",
                "url": missions_url,
                "is_active": (
                    current_path == missions_url
                    or (
                        current_path.startswith(missions_url)
                        and not current_path.startswith("/app/missions/visites/")
                    )
                ),
                "icon": "briefcase",
            })
            my_visits_url = _safe_reverse("my-visits") or _safe_reverse("visits:my-visits") or "/app/mes-visites/"
            items.append({
                "label": "Mes visites",
                "url": my_visits_url,
                "is_active": current_path.startswith("/app/mes-visites/"),
                "icon": "clipboard-list",
            })

    # Navigation Client
    elif user.role == User.Role.CLIENT:
        dashboard_url = _safe_reverse("portal:dashboard")
        visits_url = _safe_reverse("portal:visit-list")
        if dashboard_url:
            items.append({
                "label": "Avancement",
                "url": dashboard_url,
                "is_active": (current_path == dashboard_url or current_path.startswith("/portail/sites/")),
                "icon": "chart-bar",
            })
        if visits_url:
            items.append({
                "label": "Visites",
                "url": visits_url,
                "is_active": current_path.startswith("/portail/visites/"),
                "icon": "clipboard-check",
            })

    return {
        "nav_items": items,
        "navigation_items": items,
        "user_role_label": role_label,
    }
