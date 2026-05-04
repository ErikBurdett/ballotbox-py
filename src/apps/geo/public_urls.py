from django.urls import path

from . import ballot_map_views, public_views

app_name = "geo"

urlpatterns = [
    path("texas/ballot-map/geocode/", ballot_map_views.texas_ballot_map_geocode, name="texas_ballot_map_geocode"),
    path("texas/ballot-map/context/", ballot_map_views.texas_ballot_map_context, name="texas_ballot_map_context"),
    path("texas/ballot-map/", ballot_map_views.texas_ballot_map, name="texas_ballot_map"),
    path("texas/groundwater-districts/", public_views.texas_groundwater_districts, name="texas_groundwater_districts"),
    path("texas/water-districts/", public_views.texas_water_districts, name="texas_water_districts"),
    path("counties/", public_views.counties_root, name="counties_root"),
    path("counties/<str:state>/", public_views.counties_list, name="counties_list"),
    path("counties/<str:state>/<slug:county_slug>/", public_views.county_detail, name="county_detail"),
    path("cities/", public_views.cities_root, name="cities_root"),
    path("cities/<str:state>/", public_views.cities_list, name="cities_list"),
    path("cities/<str:state>/<slug:city_slug>/", public_views.city_detail, name="city_detail"),
    path("jurisdictions/<uuid:public_id>/", public_views.jurisdiction_detail, name="jurisdiction_detail"),
    path("districts/<uuid:public_id>/", public_views.district_detail, name="district_detail"),
]

