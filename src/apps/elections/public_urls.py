from django.urls import path

from . import public_views

app_name = "elections"

urlpatterns = [
    path("", public_views.candidates_directory, name="candidates_directory"),
]

