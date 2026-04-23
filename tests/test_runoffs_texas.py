from datetime import date

import pytest
from django.urls import reverse

from apps.elections.models import ElectionType
from tests.factories import ElectionFactory, JurisdictionFactory, RaceFactory


@pytest.mark.django_db
def test_runoffs_texas_page(client):
    resp = client.get(reverse("elections:runoffs_texas"))
    assert resp.status_code == 200
    assert b"Texas runoffs" in resp.content
    assert b"Runoff elections" in resp.content
    assert b"Jurisdictions" in resp.content


@pytest.mark.django_db
def test_runoffs_texas_lists_tx_runoff_election(client):
    jx = JurisdictionFactory(name="Runoffville", state="TX")
    election = ElectionFactory(
        jurisdiction=jx,
        name="Mayoral Runoff",
        election_type=ElectionType.RUNOFF,
        date=date(2025, 5, 10),
    )
    RaceFactory(election=election, office__jurisdiction=jx)

    resp = client.get(reverse("elections:runoffs_texas"))
    assert resp.status_code == 200
    assert b"Mayoral Runoff" in resp.content
    assert b"Runoffville" in resp.content
