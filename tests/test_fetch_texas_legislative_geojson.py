import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.geo.models import Jurisdiction, JurisdictionType
from apps.offices.models import Office


@pytest.mark.django_db
def test_fetch_texas_legislative_geojson_writes_files(tmp_path, monkeypatch, settings):
    fake_base = tmp_path / "src"
    fake_base.mkdir()
    monkeypatch.setattr(settings, "BASE_DIR", fake_base)
    geo_dir = fake_base / "static" / "geo"
    geo_dir.mkdir(parents=True)

    tiny = {"type": "FeatureCollection", "features": []}
    one = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": None}]}
    two = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": None}] * 2}

    def fake_all():
        return [
            ("tx-cd119.geojson", "U.S. House (119th)", one),
            ("tx-sldu.geojson", "Texas Senate", tiny),
            ("tx-sldl.geojson", "Texas House", two),
            ("tx-school-districts.geojson", "Texas school districts", one),
            ("tx-water-districts.geojson", "Texas water districts", tiny),
        ]

    with patch(
        "apps.geo.management.commands.fetch_texas_legislative_geojson.fetch_all_ballot_map_geo_bundles",
        fake_all,
    ):
        call_command("fetch_texas_legislative_geojson")

    for name in (
        "tx-cd119.geojson",
        "tx-sldu.geojson",
        "tx-sldl.geojson",
        "tx-school-districts.geojson",
        "tx-water-districts.geojson",
    ):
        p = geo_dir / name
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["type"] == "FeatureCollection"


@pytest.mark.django_db
def test_sync_tceq_gcd_jurisdictions_creates_special_district_and_office(tmp_path):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "DISTNAME": "HAYS TRINITY GROUNDWATER CONSERVATION DISTRICT",
                    "SHORTNAM": "Hays Trinity GCD",
                    "DIST_NUM": "4421002",
                    "ELECTION": "Required",
                    "WDDLINK": "https://example.test/gcd",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-98.2, 30.0],
                            [-98.0, 30.0],
                            [-98.0, 30.2],
                            [-98.2, 30.2],
                            [-98.2, 30.0],
                        ]
                    ],
                },
            }
        ],
    }
    p = tmp_path / "gcd.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")

    call_command("sync_tceq_gcd_jurisdictions", geojson_path=p)

    jurisdiction = Jurisdiction.objects.get(
        state="TX",
        jurisdiction_type=JurisdictionType.SPECIAL_DISTRICT,
        name="Hays Trinity Groundwater Conservation District",
    )
    assert jurisdiction.fips_code == "4421002"
    assert jurisdiction.geom is not None
    assert Office.objects.filter(
        jurisdiction=jurisdiction,
        name="Groundwater Conservation District Board Director",
        is_partisan=False,
    ).exists()


@pytest.mark.django_db
def test_sync_tceq_water_district_jurisdictions_creates_special_district_and_office(tmp_path):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "NAME": "Example Municipal Utility District",
                    "TYPE": "MUD",
                    "DISTRICT_ID": "12345",
                    "COUNTY": "Travis",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-97.8, 30.2],
                            [-97.7, 30.2],
                            [-97.7, 30.3],
                            [-97.8, 30.3],
                            [-97.8, 30.2],
                        ]
                    ],
                },
            }
        ],
    }
    p = tmp_path / "water.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")

    call_command("sync_tceq_water_district_jurisdictions", geojson_path=p)

    jurisdiction = Jurisdiction.objects.get(
        state="TX",
        jurisdiction_type=JurisdictionType.SPECIAL_DISTRICT,
        name="Example Municipal Utility District",
    )
    assert jurisdiction.fips_code == "12345"
    assert jurisdiction.county == "Travis"
    assert jurisdiction.geom is not None
    assert Office.objects.filter(
        jurisdiction=jurisdiction,
        name="Municipal Utility District Board Director",
        is_partisan=False,
    ).exists()
