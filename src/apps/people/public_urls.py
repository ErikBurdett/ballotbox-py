from django.urls import path

from . import public_views

app_name = "people"

urlpatterns = [
    path("<uuid:public_id>/", public_views.person_detail, name="person_detail"),
]

