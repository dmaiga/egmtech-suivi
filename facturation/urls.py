from django.urls import path

from . import views

app_name = "facturation"

urlpatterns = [
    path("", views.contact_list, name="contact-list"),
    path("contacts/nouveau/", views.contact_create, name="contact-create"),
    path("contacts/<int:pk>/modifier/", views.contact_update, name="contact-update"),
    path("contacts/<int:pk>/desactiver/", views.contact_deactivate, name="contact-deactivate"),
    path("contacts/<int:pk>/reactiver/", views.contact_reactivate, name="contact-reactivate"),
    path("profil/", views.profil_edit, name="profil"),
    path("profil/<str:champ>/", views.profil_image, name="profil-image"),
]
