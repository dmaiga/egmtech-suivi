from django.urls import path
from . import views

urlpatterns = [
    path("", views.my_visits, name="my-visits"),
    path("<int:pk>/", views.my_visit_detail, name="my-visit-detail"),
]
