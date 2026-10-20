from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sites/<int:pk>/", views.site_detail, name="site-detail"),
    path("sites/<int:pk>/export/", views.site_export, name="site-export"),
    path("visites/", views.visit_list, name="visit-list"),
    path("visites/<int:pk>/", views.visit_detail, name="visit-detail"),
    path("visites/<int:pk>/pdf/", views.visit_pdf, name="visit-pdf"),
    path("export/", views.client_export, name="client-export"),
]
