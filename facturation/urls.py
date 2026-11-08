from django.urls import path

from . import views, views_documents

app_name = "facturation"

urlpatterns = [
    path("", views_documents.document_list, name="document-list"),
    path("documents/nouveau/<str:type_document>/", views_documents.document_create, name="document-create"),
    path("documents/<int:pk>/modifier/", views_documents.document_edit, name="document-edit"),
    path("documents/<int:pk>/supprimer/", views_documents.document_delete, name="document-delete"),
    path("documents/<int:pk>/lignes/ajouter/", views_documents.ligne_add, name="ligne-add"),
    path("documents/<int:pk>/lignes/ajouter-produit/", views_documents.ligne_add_produit, name="ligne-add-produit"),
    path("documents/<int:pk>/lignes/<int:ligne_pk>/modifier/", views_documents.ligne_update, name="ligne-update"),
    path("documents/<int:pk>/lignes/<int:ligne_pk>/supprimer/", views_documents.ligne_delete, name="ligne-delete"),
    path("contacts/", views.contact_list, name="contact-list"),
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
