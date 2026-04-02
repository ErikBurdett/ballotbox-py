from django.contrib import admin
from django.urls import include, path

from apps.core.admin_export import staff_csv_export

urlpatterns = [
    path(
        "admin/data-export/<slug:export_key>/",
        staff_csv_export,
        name="admin_data_export",
    ),
    path("admin/", admin.site.urls),
    path("", include("apps.submissions.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.offices.urls")),
    path("candidates/", include("apps.elections.public_urls")),
    path("people/", include("apps.people.public_urls")),
    path("", include("apps.geo.public_urls")),
    path("search/", include("apps.search.urls")),
    path("api/", include("apps.api.urls")),
]

