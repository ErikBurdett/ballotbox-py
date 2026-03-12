from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.offices.urls")),
    path("candidates/", include("apps.elections.public_urls")),
    path("people/", include("apps.people.public_urls")),
    path("", include("apps.geo.public_urls")),
    path("search/", include("apps.search.urls")),
    path("api/", include("apps.api.urls")),
]

