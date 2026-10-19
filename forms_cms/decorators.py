from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def manage_forms_required(view_func):
    """Autorise les superusers et les utilisateurs ayant la permission forms_cms.manage_forms.

    Utilisateur anonyme -> redirection vers la page de connexion.
    Utilisateur connecté sans la permission -> 403.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if user.is_superuser or user.has_perm("forms_cms.manage_forms"):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied

    return _wrapped_view
