from django.urls import path

from . import views

app_name = "revue"

urlpatterns = [
    path("", views.revue_list, name="list"),
    path("<int:pk>/", views.revue_detail, name="detail"),
    path("messages/", views.echange_inbox, name="inbox"),
    path("messages/nouveau/", views.echange_nouveau, name="echange-nouveau"),
    path("messages/<int:pk>/", views.echange_detail, name="echange"),
    path("messages/<int:pk>/statut/", views.echange_statut, name="echange-statut"),
    path("<int:pk>/valider/", views.visit_validate, name="validate"),
    path("<int:pk>/rejeter/", views.visit_reject, name="reject"),
    path("<int:pk>/publier/", views.visit_publish, name="publish"),
    path("<int:pk>/depublier/", views.visit_unpublish, name="unpublish"),
]
