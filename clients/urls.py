from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("nouveau/", views.ClientCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<int:client_pk>/sites/nouveau/", views.site_create, name="site-create"),
    path("<int:client_pk>/sites/<int:pk>/modifier/", views.SiteUpdateView.as_view(), name="site-update"),
    path("<int:client_pk>/sites/<int:pk>/supprimer/", views.site_delete, name="site-delete"),
    path("<int:client_pk>/comptes/nouveau/", views.client_user_create, name="user-create"),
    path("<int:client_pk>/comptes/<int:user_pk>/revoquer/", views.client_user_revoke, name="user-revoke"),
]
