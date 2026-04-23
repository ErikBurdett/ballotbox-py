import pytest
from django.urls import reverse

from apps.geo.models import JurisdictionType

from .factories import JurisdictionFactory


@pytest.mark.django_db
def test_texas_ballot_map_page(client):
    resp = client.get(reverse("geo:texas_ballot_map"))
    assert resp.status_code == 200
    assert b"Texas ballot map" in resp.content
    assert b"Map layers" in resp.content
    assert b"maplibre-gl" in resp.content.lower() or b"maplibre" in resp.content.lower()


@pytest.mark.django_db
def test_texas_ballot_map_context_potter_point(client):
    JurisdictionFactory(
        name="Potter County",
        jurisdiction_type=JurisdictionType.COUNTY,
        state="TX",
        county="Potter",
        city="",
        fips_code="48375",
    )
    # Amarillo area — inside Potter County per bundled GeoJSON
    url = reverse("geo:texas_ballot_map_context") + "?lat=35.2220&lng=-101.8313"
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Potter County" in resp.content


@pytest.mark.django_db
def test_texas_ballot_map_context_outside_texas(client):
    url = reverse("geo:texas_ballot_map_context") + "?lat=40.0&lng=-74.0"
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"outside Texas" in resp.content
