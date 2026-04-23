"""
GeoJSON bundles for the Texas ballot map: Census TIGERweb (legislative, school) and TCEQ (water districts).

Used by ``manage.py fetch_texas_legislative_geojson`` (writes under ``static/geo/``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from apps.geo.tigerweb_legislative import TX_STATE_WHERE, fetch_texas_legislative_bundle

TIGERWEB_SCHOOL_MAPSERVER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/School/MapServer"
)
TCEQ_WATER_MAPSERVER = "https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/WaterDistricts/MapServer"

# Census School service: unified / secondary / elementary (ACS 2025 block uses layers 0–2)
SCHOOL_LAYER_IDS: tuple[tuple[str, int], ...] = (
    ("unified", 0),
    ("secondary", 1),
    ("elementary", 2),
)


def _arcgis_query_url(mapserver_base: str, layer_id: int, params: dict[str, str]) -> str:
    base = mapserver_base.rstrip("/")
    qs = urllib.parse.urlencode(params)
    return f"{base}/{layer_id}/query?{qs}"


def _urlopen_geojson_chunk(url: str, *, timeout_s: float) -> dict[str, Any]:
    """GET ArcGIS ``f=geojson`` response; raises if body is empty, HTML (WAF), or invalid JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ballotbox-py/1.0 (+https://github.com/) texas-ballot-map-geo-fetch",
            "Accept": "application/geo+json, application/json, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", "ignore").strip()
    if not raw:
        raise ValueError("empty response body")
    if raw.lstrip().startswith("<"):
        raise ValueError(f"non-JSON (likely WAF or error page): {raw[:240]!r}")
    return json.loads(raw)


def arcgis_geojson_paged(
    mapserver_base: str,
    layer_id: int,
    where: str,
    *,
    out_fields: str = "*",
    page_size: int = 500,
    max_offset: int = 50_000,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Paged ArcGIS MapServer GeoJSON query; merges all features."""
    all_features: list[dict[str, Any]] = []
    offset = 0
    while offset <= max_offset:
        params: dict[str, str] = {
            "where": where,
            "f": "geojson",
            "outSR": "4326",
            "outFields": out_fields,
            "resultRecordCount": str(page_size),
        }
        if offset > 0:
            params["resultOffset"] = str(offset)
        url = _arcgis_query_url(mapserver_base, layer_id, params)
        try:
            chunk = _urlopen_geojson_chunk(url, timeout_s=timeout_s)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ArcGIS GeoJSON request failed ({url[:80]}… offset={offset}): {exc}") from exc
        feats = chunk.get("features") or []
        if not isinstance(feats, list):
            break
        all_features.extend(feats)
        if len(feats) < page_size:
            break
        offset += page_size
    return {"type": "FeatureCollection", "features": all_features}


def fetch_texas_school_districts_merged() -> dict[str, Any]:
    """
    Merge Texas unified, secondary, and elementary school districts from TIGERweb School.

    Each feature gets ``BALLOTBOX_SCHOOL_LEVEL`` = unified | secondary | elementary.
    """
    merged: list[dict[str, Any]] = []
    for level, lid in SCHOOL_LAYER_IDS:
        # TIGERweb often returns an HTML "Request Rejected" (WAF) for large GeoJSON pages
        # (e.g. resultRecordCount=500 + full geometry). Use a smaller page size for School.
        fc = arcgis_geojson_paged(
            TIGERWEB_SCHOOL_MAPSERVER,
            lid,
            TX_STATE_WHERE,
            page_size=50,
            max_offset=25_000,
        )
        for feat in fc.get("features") or []:
            if not isinstance(feat, dict):
                continue
            props = feat.setdefault("properties", {})
            if isinstance(props, dict):
                props["BALLOTBOX_SCHOOL_LEVEL"] = level
            merged.append(feat)
    return {"type": "FeatureCollection", "features": merged}


def fetch_tceq_water_districts() -> dict[str, Any]:
    """All water district polygons from TCEQ Public WaterDistricts (Texas)."""
    return arcgis_geojson_paged(
        TCEQ_WATER_MAPSERVER,
        0,
        "1=1",
        page_size=500,
        max_offset=25_000,
        timeout_s=240.0,
    )


def fetch_all_ballot_map_geo_bundles() -> list[tuple[str, str, dict[str, Any]]]:
    """
    Return ordered (filename, human label, GeoJSON dict) for every ballot-map overlay file.
    """
    cd, sdu, sdl = fetch_texas_legislative_bundle()
    school = fetch_texas_school_districts_merged()
    water = fetch_tceq_water_districts()
    return [
        ("tx-cd119.geojson", "U.S. House (119th)", cd),
        ("tx-sldu.geojson", "Texas Senate", sdu),
        ("tx-sldl.geojson", "Texas House", sdl),
        (
            "tx-school-districts.geojson",
            "Texas school districts (Census: unified / secondary / elementary)",
            school,
        ),
        ("tx-water-districts.geojson", "Texas water districts (TCEQ)", water),
    ]
