import pytest
from django.urls import reverse

from apps.geo.models import JurisdictionType

from .factories import (
    CandidacyFactory,
    DistrictFactory,
    ElectionFactory,
    JurisdictionFactory,
    OfficeFactory,
    OfficeholderTermFactory,
    PersonFactory,
    RaceFactory,
)


@pytest.mark.django_db
def test_home_page(client):
    resp = client.get(reverse("core:home"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_person_office_geo_detail_pages(client):
    district = DistrictFactory()
    office = OfficeFactory(jurisdiction=district.jurisdiction, default_district=district)
    term = OfficeholderTermFactory(office=office, jurisdiction=district.jurisdiction, district=district)
    person = term.person

    resp = client.get(reverse("people:person_detail", args=[person.public_id]))
    assert resp.status_code == 200

    resp = client.get(reverse("offices:office_detail", args=[office.public_id]))
    assert resp.status_code == 200

    resp = client.get(reverse("geo:district_detail", args=[district.public_id]))
    assert resp.status_code == 200

    resp = client.get(reverse("geo:jurisdiction_detail", args=[district.jurisdiction.public_id]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_counties_root_redirects_to_texas_list(client):
    resp = client.get(reverse("geo:counties_root"), follow=False)
    assert resp.status_code == 302
    assert resp["Location"].endswith(reverse("geo:counties_list", kwargs={"state": "TX"}))


@pytest.mark.django_db
def test_county_slug_hub_and_list(client):
    county = JurisdictionFactory(
        name="Potter County",
        jurisdiction_type=JurisdictionType.COUNTY,
        state="TX",
        county="Potter",
        city="",
    )
    election = ElectionFactory(jurisdiction=county, name="2026 General")
    office = OfficeFactory(jurisdiction=county, name="County Commissioner")
    race = RaceFactory(election=election, office=office)
    CandidacyFactory(race=race)

    resp = client.get(reverse("geo:counties_list", kwargs={"state": "TX"}))
    assert resp.status_code == 200
    assert resp.content.count(b"Potter County") == 1

    resp = client.get(reverse("geo:county_detail", kwargs={"state": "TX", "county_slug": "potter-county"}))
    assert resp.status_code == 200
    assert b"County Commissioner" in resp.content
    assert b"Races &amp; candidates" in resp.content


@pytest.mark.django_db
def test_jurisdiction_uuid_canonical_points_to_county_slug(client):
    county = JurisdictionFactory(
        name="Randall County",
        jurisdiction_type=JurisdictionType.COUNTY,
        state="TX",
        county="Randall",
        city="",
    )
    url = reverse("geo:county_detail", kwargs={"state": "TX", "county_slug": "randall-county"})
    resp = client.get(reverse("geo:jurisdiction_detail", args=[county.public_id]))
    assert resp.status_code == 200
    assert f'href="http://testserver{url}"'.encode() in resp.content


@pytest.mark.django_db
def test_city_slug_hub_and_list(client):
    city = JurisdictionFactory(
        name="Amarillo",
        jurisdiction_type=JurisdictionType.CITY,
        state="TX",
        county="Potter",
        city="Amarillo",
    )
    resp = client.get(reverse("geo:cities_list", kwargs={"state": "TX"}))
    assert resp.status_code == 200
    assert b"Amarillo" in resp.content

    resp = client.get(reverse("geo:city_detail", kwargs={"state": "TX", "city_slug": "amarillo"}))
    assert resp.status_code == 200
    assert b"All TX cities" in resp.content or b"cities &amp; towns" in resp.content

