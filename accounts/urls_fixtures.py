"""URLconf utilisé uniquement par les tests pour exercer role_required en conditions réelles."""
from django.urls import include, path

from .tests import manager_only_view

urlpatterns = [
    path("fake-manager-only/", manager_only_view, name="fake-manager-only"),
    path("comptes/", include("accounts.urls")),
]
