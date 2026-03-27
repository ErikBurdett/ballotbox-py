from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("source-records/<uuid:public_id>/", views.source_record_detail, name="source_record_detail"),
    path("officials/", views.officials, name="officials"),
    path("candidates/", views.candidates, name="candidates"),
    path("filters/", views.filters, name="filters"),
]

