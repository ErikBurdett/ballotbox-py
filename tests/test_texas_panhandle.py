import pytest
from django.utils import timezone

from apps.ingestion.models import Provider, SourceRecord
from apps.ingestion.texas_panhandle import (
    PANHANDLE_COUNTY_FIPS,
    district_matches_panhandle_north,
    district_matches_texas_panhandle,
    load_panhandle_north_of_lubbock_county_points,
    load_panhandle_sync_points,
    order_points_by_geo_election_record_count,
    pick_date_discovery_points,
)


def test_panhandle_fips_is_26_counties():
    assert len(PANHANDLE_COUNTY_FIPS) == 26


def test_load_panhandle_sync_points_from_geojson():
    pts = load_panhandle_sync_points()
    assert len(pts) == 26
    for p in pts:
        assert "lat" in p and "long" in p and "slug" in p and "fips" in p
        assert p["fips"] in PANHANDLE_COUNTY_FIPS


def test_district_matches_texas_panhandle_positive():
    d = {"name": "Potter County", "type": "County", "races": []}
    assert district_matches_texas_panhandle(d) is True


def test_district_matches_texas_panhandle_negative():
    d = {"name": "Travis County", "type": "County", "races": []}
    assert district_matches_texas_panhandle(d) is False


def test_load_panhandle_north_superset_of_classic_panhandle():
    north = load_panhandle_north_of_lubbock_county_points()
    classic = load_panhandle_sync_points()
    assert len(north) >= len(classic) >= 26
    classic_fips = {str(p["fips"]) for p in classic}
    north_fips = {str(p["fips"]) for p in north}
    assert classic_fips <= north_fips
    assert "48189" in north_fips  # Hale County (north of Lubbock, not in 26-county list)


def test_district_matches_panhandle_north_hale():
    d = {"name": "Hale County", "type": "County", "races": []}
    assert district_matches_panhandle_north(d) is True


def test_pick_date_discovery_points_respects_limit():
    pts = load_panhandle_sync_points()
    picked = pick_date_discovery_points(pts, 3)
    assert len(picked) == 3


@pytest.mark.django_db
def test_order_points_by_geo_election_record_count_prefers_sparse():
    pts = load_panhandle_sync_points()[:4]
    slug_a, slug_b = str(pts[0]["slug"]), str(pts[1]["slug"])
    pl = {}
    sha = SourceRecord.compute_sha256(pl)
    SourceRecord.objects.create(
        provider=Provider.BALLOTPEDIA,
        external_id=f"ballotpedia:geo_elections:{slug_a}:2026-05-03",
        payload=pl,
        payload_sha256=sha,
        fetched_at=timezone.now(),
    )
    sha2 = SourceRecord.compute_sha256({"x": 1})
    SourceRecord.objects.create(
        provider=Provider.BALLOTPEDIA,
        external_id=f"ballotpedia:geo_elections:{slug_a}:2026-11-04",
        payload={"x": 1},
        payload_sha256=sha2,
        fetched_at=timezone.now(),
    )
    ordered = order_points_by_geo_election_record_count(list(pts))
    assert str(ordered[-1]["slug"]) == slug_a
    assert str(ordered[0]["slug"]) != slug_a
