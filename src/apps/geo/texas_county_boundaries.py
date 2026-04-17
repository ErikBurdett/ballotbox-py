"""
Texas county polygons (static GeoJSON) for map display and point-in-polygon lookup.

Data file: ``static/geo/tx-counties.geojson`` (254 counties, filtered from public domain
county boundaries). No external API calls at runtime.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, Point

from apps.geo.models import Jurisdiction, JurisdictionType


@lru_cache(maxsize=1)
def _tx_counties_geojson() -> dict:
    path = Path(settings.BASE_DIR) / "static" / "geo" / "tx-counties.geojson"
    return json.loads(path.read_text(encoding="utf-8"))


def texas_county_feature_for_point(lon: float, lat: float) -> dict | None:
    """Return the GeoJSON feature whose polygon contains ``(lon, lat)``, or ``None``."""
    pt = Point(float(lon), float(lat), srid=4326)
    for feat in _tx_counties_geojson().get("features") or []:
        geom = feat.get("geometry")
        if not geom:
            continue
        g = GEOSGeometry(json.dumps(geom))
        if g.srid is None:
            g.srid = 4326
        elif g.srid != 4326:
            g.transform(4326)
        if g.contains(pt) or g.covers(pt):
            return feat
    return None


def resolve_jurisdiction_for_texas_county_feature(feature: dict) -> Jurisdiction | None:
    """Match a county feature to a ``Jurisdiction`` row using FIPS, name, or county stem."""
    props = feature.get("properties") or {}
    name = str(props.get("NAME") or "").strip()
    raw_id = str(feature.get("id") or "")
    geo = str(props.get("GEO_ID") or "")
    fips5 = raw_id if len(raw_id) == 5 and raw_id.isdigit() else geo.replace("0500000US", "")[-5:]
    if len(fips5) != 5 or not fips5.isdigit():
        fips5 = ""

    qs = Jurisdiction.objects.filter(state="TX", jurisdiction_type=JurisdictionType.COUNTY)
    if fips5:
        j = qs.filter(fips_code=fips5).first()
        if j:
            return j
    if name:
        j = qs.filter(name__iexact=f"{name} County").first()
        if j:
            return j
        j = qs.filter(county__iexact=name).first()
        if j:
            return j
    return None
