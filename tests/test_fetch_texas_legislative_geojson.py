import json
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command


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
