import pytest
from django.urls import reverse

from apps.geo.models import Jurisdiction

from .factories import CandidacyFactory, JurisdictionFactory, OfficeholderTermFactory


@pytest.mark.django_db
def test_officials_directory_filters_by_state(client):
    ca = JurisdictionFactory(state="CA", name="CA Demo City")
    ny = JurisdictionFactory(state="NY", name="NY Demo City")
    OfficeholderTermFactory(jurisdiction=ca, office__jurisdiction=ca, person__first_name="Alex", person__last_name="Rivera")
    OfficeholderTermFactory(jurisdiction=ny, office__jurisdiction=ny, person__first_name="Jamie", person__last_name="Patel")

    url = reverse("offices:officials_directory")
    resp = client.get(url, {"state": "CA"})
    assert resp.status_code == 200
    assert "Alex" in resp.content.decode()
    assert "Jamie" not in resp.content.decode()


@pytest.mark.django_db
def test_officials_directory_htmx_returns_partial(client):
    j = JurisdictionFactory(state="CA")
    OfficeholderTermFactory(jurisdiction=j, office__jurisdiction=j, person__first_name="Alex", person__last_name="Rivera")

    url = reverse("offices:officials_directory")
    resp = client.get(url, {"state": "CA"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    # partial template should not include full HTML scaffold
    assert "<html" not in resp.content.decode().lower()


@pytest.mark.django_db
def test_candidates_directory_filters_by_party(client):
    c1 = CandidacyFactory(party="democratic", person__first_name="Jordan", person__last_name="Kim")
    c2 = CandidacyFactory(party="republican", person__first_name="Taylor", person__last_name="Nguyen")

    url = reverse("elections:candidates_directory")
    resp = client.get(url, {"party": "democratic"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Jordan" in body
    assert "Taylor" not in body

