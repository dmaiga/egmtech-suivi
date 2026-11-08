from django.urls import path

from . import views

app_name = "facturation"

urlpatterns = [
    path("", views.contact_list, name="contact-list"),
    path("contacts/nouveau/", views.contact_create, name="contact-create"),
    path("contacts/<int:pk>/modifier/", views.contact_update, name="contact-update"),
    path("contacts/<int:pk>/desactiver/", views.contact_deactivate, name="contact-deactivate"),
    path("contacts/<int:pk>/reactiver/", views.contact_reactivate, name="contact-reactivate"),
    path("produits/", views.produit_list, name="produit-list"),
    path("produits/nouveau/", views.produit_create, name="produit-create"),
    path("produits/<int:pk>/modifier/", views.produit_update, name="produit-update"),
    path("produits/<int:pk>/desactiver/", views.produit_deactivate, name="produit-deactivate"),
    path("produits/<int:pk>/reactiver/", views.produit_reactivate, name="produit-reactivate"),
    path("profil/", views.profil_edit, name="profil"),
    path("profil/<str:champ>/", views.profil_image, name="profil-image"),
]
