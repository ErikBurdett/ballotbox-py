import pytest
from django.urls import reverse

from .factories import DistrictFactory, OfficeFactory, OfficeholderTermFactory, PersonFactory


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

