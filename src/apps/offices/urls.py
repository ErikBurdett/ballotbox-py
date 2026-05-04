from django.urls import path

from . import office_views, public_views

app_name = "offices"

urlpatterns = [
    path("officials/groundwater-districts/", public_views.groundwater_officials_directory, name="groundwater_officials_directory"),
    path("officials/", public_views.officials_directory, name="officials_directory"),
    path("offices/<uuid:public_id>/", office_views.office_detail, name="office_detail"),
]

