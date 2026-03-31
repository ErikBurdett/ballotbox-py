from django.urls import path

from . import public_views

app_name = "elections"

urlpatterns = [
    path("races/", public_views.races_list_texas, name="races_list_texas"),
    path("races/<uuid:public_id>/", public_views.race_detail, name="race_detail"),
    path("", public_views.candidates_directory, name="candidates_directory"),
]

