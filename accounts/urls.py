from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.RoleAwareLoginView.as_view(), name="login"),
    path("deconnexion/", views.AppLogoutView.as_view(), name="logout"),
]
