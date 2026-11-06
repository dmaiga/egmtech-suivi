from django.urls import path

from . import views

app_name = "forms_cms"

urlpatterns = [
    path("", views.FormTemplateListView.as_view(), name="list"),
    path("nouveau/", views.form_builder, name="builder-new"),
    path("nouveau/json/", views.FormTemplateImportView.as_view(), name="import"),
    path("<int:pk>/editer/", views.form_builder, name="builder-edit"),
    path("<int:pk>/apercu/", views.form_template_preview, name="template-preview"),
    path("<int:pk>/basculer/", views.form_template_toggle, name="template-toggle"),
    path("clients/<int:client_pk>/attacher/", views.client_attach_form, name="client-attach"),
    path(
        "clients/<int:client_pk>/attaches/<int:pk>/basculer/",
        views.attached_form_toggle,
        name="attached-toggle",
    ),
    path("clients/<int:client_pk>/attaches/<int:pk>/supprimer/", views.attached_form_delete, name="attached-delete"),
    path("clients/<int:client_pk>/attaches/<int:pk>/sites/ajouter/", views.attached_sites_add, name="attached-sites-add"),
    path(
        "clients/<int:client_pk>/attaches/<int:pk>/sites/<int:site_pk>/retirer/",
        views.attached_site_remove,
        name="attached-site-remove",
    ),
    path(
        "clients/<int:client_pk>/attaches/<int:pk>/previsions/",
        views.expected_visits_update,
        name="expected-update",
    ),
]
