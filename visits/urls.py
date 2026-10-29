from django.urls import path

from . import views

app_name = "visits"

urlpatterns = [
    path("", views.mission_list, name="mission-list"),
    path("nouveau/", views.mission_create, name="mission-create"),
    path("options/", views.mission_options, name="mission-options"),
    path("formulaires/<int:pk>/", views.mission_form_detail, name="attached-form-detail"),
    path("<int:mission_pk>/commencer/", views.visit_start, name="visit-start"),
    path("visites/<int:pk>/", views.visit_edit, name="visit-edit"),
    path("mes-visites/", views.my_visits, name="my-visits"),
    path("mes-visites/<int:pk>/", views.my_visit_detail, name="my-visit-detail"),
    path("visites/<int:pk>/enregistrer/", views.visit_save, name="visit-save"),
    path("visites/<int:pk>/soumettre/", views.visit_submit, name="visit-submit"),
    path("visites/<int:pk>/confirmation/", views.visit_confirmation, name="visit-confirmation"),
    path("visites/<int:pk>/ligne/ajouter/", views.repeat_row_add, name="repeat-row-add"),
    path("ligne/retirer/", views.repeat_row_remove, name="repeat-row-remove"),
    path("photos/<int:pk>/supprimer/", views.photo_delete, name="photo-delete"),
    path("visites/<int:pk>/pdf/", views.visit_pdf, name="visit-pdf"),
    path("clients/<int:client_pk>/export/", views.client_export, name="client-export"),
    path("clients/<int:client_pk>/sites/<int:site_pk>/export/", views.site_export, name="site-export"),
]
