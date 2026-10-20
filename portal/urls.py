from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sites/<int:pk>/", views.site_detail, name="site-detail"),
    path("visites/<int:pk>/", views.visit_detail, name="visit-detail"),
]
