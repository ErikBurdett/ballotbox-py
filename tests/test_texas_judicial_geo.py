"""Texas Courts of Appeals dissolve (§22.201) vs Census county GeoJSON."""

from pathlib import Path

import pytest
from django.conf import settings

from apps.geo.texas_judicial_geo import (
    build_coa_geojson,
    validate_coa_county_coverage,
    load_tx_counties_geojson_from_path,
)


@pytest.mark.django_db
def test_coa_validate_and_build_from_bundled_counties():
    path = Path(settings.BASE_DIR) / "static" / "geo" / "tx-counties.geojson"
    if not path.is_file():
        pytest.skip("tx-counties.geojson not in workspace")
    fc = load_tx_counties_geojson_from_path(path)
    validate_coa_county_coverage(fc)
    coa = build_coa_geojson(fc)
    feats = coa.get("features") or []
    assert len(feats) == 14
    dists = {str(f["properties"].get("COA_DIST")) for f in feats if isinstance(f, dict)}
    assert dists == {"1-14", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "15"}
