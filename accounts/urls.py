from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.RoleAwareLoginView.as_view(), name="login"),
    path("deconnexion/", views.AppLogoutView.as_view(), name="logout"),
    path("auditeurs/", views.auditor_list, name="auditor-list"),
    path("auditeurs/nouveau/", views.auditor_create, name="auditor-create"),
    path("auditeurs/<int:pk>/", views.auditor_detail, name="auditor-detail"),
]
