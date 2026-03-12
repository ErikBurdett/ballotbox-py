from django.urls import path

from . import public_views

app_name = "geo"

urlpatterns = [
    path("jurisdictions/<uuid:public_id>/", public_views.jurisdiction_detail, name="jurisdiction_detail"),
    path("districts/<uuid:public_id>/", public_views.district_detail, name="district_detail"),
]

