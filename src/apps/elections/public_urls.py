from django.urls import path

from . import public_views

app_name = "elections"

urlpatterns = [
    path("runoffs/texas/", public_views.runoffs_texas, name="runoffs_texas"),
    path("races/", public_views.races_list_texas, name="races_list_texas"),
    path("races/<uuid:public_id>/", public_views.race_detail, name="race_detail"),
    path("groundwater-districts/", public_views.groundwater_candidates_directory, name="groundwater_candidates_directory"),
    path("", public_views.candidates_directory, name="candidates_directory"),
]

