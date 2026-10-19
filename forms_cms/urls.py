from django.urls import path

from . import views

app_name = "forms_cms"

urlpatterns = [
    path("", views.FormTemplateListView.as_view(), name="list"),
    path("nouveau/", views.FormTemplateImportView.as_view(), name="import"),
    path("<int:pk>/basculer/", views.form_template_toggle, name="template-toggle"),
    path("clients/<int:client_pk>/attacher/", views.client_attach_form, name="client-attach"),
    path(
        "clients/<int:client_pk>/attaches/<int:pk>/basculer/",
        views.attached_form_toggle,
        name="attached-toggle",
    ),
    path(
        "clients/<int:client_pk>/attaches/<int:pk>/previsions/",
        views.expected_visits_update,
        name="expected-update",
    ),
]
