from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.utils.cache import add_never_cache_headers


class AuthPagesMiddleware:
    """Cohérence connexion / déconnexion.

    - Les pages d'un utilisateur connecté ne sont pas gardées en cache par le navigateur :
      après déconnexion, le bouton retour ou un onglet resté ouvert ne réaffiche pas
      l'espace connecté.
    - Une requête HTMX renvoyée vers la connexion (session expirée) recharge la page
      entière au lieu d'injecter le formulaire de connexion dans un morceau de page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        login_url = resolve_url(settings.LOGIN_URL)
        if (
            request.headers.get("HX-Request")
            and response.status_code in (301, 302)
            and response.get("Location", "").startswith(login_url)
        ):
            redirect = HttpResponse(status=204)
            redirect["HX-Redirect"] = response["Location"]
            return redirect

        if request.user.is_authenticated and not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        return response
