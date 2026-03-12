from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("officials/", views.officials, name="officials"),
    path("candidates/", views.candidates, name="candidates"),
    path("filters/", views.filters, name="filters"),
]

