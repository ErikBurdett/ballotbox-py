"""
GeoJSON bundles for the Texas ballot map: Census TIGERweb (legislative, school, places, urban)
and TCEQ (water districts), plus Texas Legislative Council SBOE Plan E2106 from Capitol Data.

Used by ``manage.py fetch_texas_legislative_geojson`` (writes under ``static/geo/``).
"""

from __future__ import annotations

import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from apps.geo.tigerweb_legislative import TX_STATE_WHERE, fetch_texas_legislative_bundle
from apps.geo.texas_judicial_geo import (
    build_cca_geojson,
    build_coa_geojson,
    load_tx_counties_geojson_from_path,
    validate_coa_county_coverage,
)

TIGERWEB_SCHOOL_MAPSERVER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/School/MapServer"
)
TIGERWEB_PLACES_MAPSERVER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer"
)
TIGERWEB_URBAN_MAPSERVER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer"
TCEQ_WATER_MAPSERVER = "https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/WaterDistricts/MapServer"
TCEQ_GCD_MAPSERVER = "https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/GCDs/MapServer"
TCEQ_PGMA_MAPSERVER = "https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/PGMA/MapServer"

# Places / urban: current-year-ish TIGERweb layer ids (see each service's ?f=json catalog)
PLACES_INCORPORATED_LAYER_ID = 4
PLACES_CDP_LAYER_ID = 5
URBAN_AREA_2020_LAYER_ID = 0

# Texas Legislative Council — S.B. 7 Plan E2106 (SBOE), same archive linked from Capitol Data portal.
PLANE2106_ZIP_URL = (
    "https://data.capitol.texas.gov/dataset/ad1ae979-6df9-4322-98cf-6771cc67f02d/"
    "resource/640a507d-e26e-4b50-861c-7913c152bdc7/download/plane2106.zip"
)
TWDB_GMA_ZIP_URL = "https://www.twdb.texas.gov/mapping/gisdata/doc/gma.zip"
TWDB_RWPA_ZIP_URL = "https://www.twdb.texas.gov/mapping/gisdata/doc/RWPA_Shapefile.zip"
TWDB_RASL_ZIP_URL = "https://www.twdb.texas.gov/mapping/gisdata/doc/RA_SLD_Shapefile.zip"

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


def fetch_tceq_groundwater_conservation_districts() -> dict[str, Any]:
    """TCEQ Groundwater Conservation District boundaries from the public GCD viewer service."""
    return arcgis_geojson_paged(
        TCEQ_GCD_MAPSERVER,
        0,
        "1=1",
        page_size=500,
        max_offset=10_000,
        timeout_s=240.0,
    )


def fetch_tceq_priority_groundwater_management_areas() -> dict[str, Any]:
    """TCEQ Priority Groundwater Management Areas from the public GCD viewer service."""
    return arcgis_geojson_paged(
        TCEQ_PGMA_MAPSERVER,
        0,
        "1=1",
        page_size=500,
        max_offset=10_000,
        timeout_s=240.0,
    )


def _json_safe_property_value(val: Any) -> Any:
    """
    Convert shapefile / GDAL attribute values to JSON-serializable scalars.

    Django GDAL may return OFTInteger64 and similar wrappers that are not handled by :func:`json.dumps`.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float):
        return val
    if isinstance(val, (bytes, memoryview)):
        return bytes(val).decode("utf-8", "replace")
    if hasattr(val, "isoformat") and callable(getattr(val, "isoformat")):
        try:
            return val.isoformat()
        except Exception:
            pass
    try:
        return int(val)
    except (TypeError, ValueError):
        pass
    try:
        return float(val)
    except (TypeError, ValueError):
        pass
    return str(val)


def shapefile_to_geojson_feature_collection(shp_path: Path) -> dict[str, Any]:
    """
    Read an Esri shapefile (path to ``*.shp``) into a GeoJSON FeatureCollection (WGS84).

    Requires GDAL bindings (available in the production Docker image and typical PostGIS dev setups).
    """
    from django.contrib.gis.gdal import DataSource

    ds = DataSource(str(shp_path))
    layer = ds[0]
    out_features: list[dict[str, Any]] = []
    for feat in layer:
        ogr_geom = feat.geom
        if ogr_geom is None:
            continue
        ogr_geom.transform(4326)
        geos = ogr_geom.geos
        props: dict[str, Any] = {}
        for name in layer.fields:
            try:
                props[name] = _json_safe_property_value(feat[name])
            except (IndexError, KeyError, TypeError, ValueError):
                props[name] = None
        out_features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": json.loads(geos.geojson),
            }
        )
    return {"type": "FeatureCollection", "features": out_features}


def fetch_texas_sboe_plane2106_geojson(*, timeout_s: float = 120.0) -> dict[str, Any]:
    """
    State Board of Education districts, Plan E2106 (effective Jan 2023), from Capitol Data.

    Source: https://data.capitol.texas.gov/dataset/plane2106 — shapefile inside ``PLANE2106.zip``.
    """
    with tempfile.TemporaryDirectory(prefix="plane2106_") as td_raw:
        td = Path(td_raw)
        zpath = td / "plane2106.zip"
        req = urllib.request.Request(
            PLANE2106_ZIP_URL,
            headers={
                "User-Agent": (
                    "ballotbox-py/1.0 (+https://github.com/) texas-ballot-map-sboe-plane2106"
                ),
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            zpath.write_bytes(resp.read())
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(td)
        shp = td / "PLANE2106" / "PLANE2106.shp"
        if not shp.is_file():
            raise FileNotFoundError(f"Expected shapefile at {shp} after extracting Capitol PLANE2106.zip")
        return shapefile_to_geojson_feature_collection(shp)


def fetch_shapefile_zip_geojson(url: str, *, timeout_s: float = 120.0) -> dict[str, Any]:
    """Download a zipped shapefile and convert the first ``*.shp`` found to GeoJSON."""
    with tempfile.TemporaryDirectory(prefix="shpzip_") as td_raw:
        td = Path(td_raw)
        zpath = td / "source.zip"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ballotbox-py/1.0 (+https://github.com/) texas-ballot-map-shapefile-fetch",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            zpath.write_bytes(resp.read())
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(td)
        shp_files = sorted(td.rglob("*.shp"))
        if not shp_files:
            raise FileNotFoundError(f"No shapefile found after extracting {url}")
        return shapefile_to_geojson_feature_collection(shp_files[0])


def fetch_twdb_groundwater_management_areas() -> dict[str, Any]:
    """TWDB Groundwater Management Areas (GMA) boundaries."""
    return fetch_shapefile_zip_geojson(TWDB_GMA_ZIP_URL)


def fetch_twdb_regional_water_planning_areas() -> dict[str, Any]:
    """TWDB Regional Water Planning Areas (RWPA) boundaries."""
    return fetch_shapefile_zip_geojson(TWDB_RWPA_ZIP_URL)


def fetch_twdb_river_authorities_special_law_districts() -> dict[str, Any]:
    """TWDB River Authorities and Special Law Districts statutory boundaries."""
    return fetch_shapefile_zip_geojson(TWDB_RASL_ZIP_URL)


def fetch_texas_incorporated_places() -> dict[str, Any]:
    """Census TIGERweb: incorporated places clipped to Texas (STATE='48')."""
    return arcgis_geojson_paged(
        TIGERWEB_PLACES_MAPSERVER,
        PLACES_INCORPORATED_LAYER_ID,
        TX_STATE_WHERE,
        page_size=50,
        max_offset=80_000,
        timeout_s=240.0,
    )


def fetch_texas_census_designated_places() -> dict[str, Any]:
    """Census TIGERweb: Census Designated Places in Texas."""
    return arcgis_geojson_paged(
        TIGERWEB_PLACES_MAPSERVER,
        PLACES_CDP_LAYER_ID,
        TX_STATE_WHERE,
        page_size=50,
        max_offset=50_000,
        timeout_s=240.0,
    )


def fetch_texas_urban_areas_2020_name_tx() -> dict[str, Any]:
    """
    Census 2020 Urban Areas whose TIGERweb ``NAME`` ends with ``, TX`` (Texas portions).

    This avoids pulling the full national urban layer while still covering Texas metro footprints.
    """
    return arcgis_geojson_paged(
        TIGERWEB_URBAN_MAPSERVER,
        URBAN_AREA_2020_LAYER_ID,
        "NAME LIKE '%, TX%'",
        page_size=100,
        max_offset=10_000,
        timeout_s=300.0,
    )


def fetch_texas_judicial_ballot_map_bundles(counties_geojson_path: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Courts of Appeals (§22.201) + Court of Criminal Appeals (statewide), built from ``tx-counties.geojson``.
    """
    fc = load_tx_counties_geojson_from_path(counties_geojson_path)
    validate_coa_county_coverage(fc)
    coa = build_coa_geojson(fc)
    cca = build_cca_geojson(fc)
    return [
        ("tx-coa-districts.geojson", "Texas Courts of Appeals (Gov't Code §22.201)", coa),
        ("tx-cca-statewide.geojson", "Texas Court of Criminal Appeals (statewide)", cca),
    ]


def fetch_all_ballot_map_geo_bundles(
    *,
    counties_geojson_path: Path | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Return ordered (filename, human label, GeoJSON dict) for every ballot-map overlay file.
    """
    cd, sdu, sdl = fetch_texas_legislative_bundle()
    sboe = fetch_texas_sboe_plane2106_geojson()
    school = fetch_texas_school_districts_merged()
    water = fetch_tceq_water_districts()
    gcd = fetch_tceq_groundwater_conservation_districts()
    pgma = fetch_tceq_priority_groundwater_management_areas()
    gma = fetch_twdb_groundwater_management_areas()
    rwpa = fetch_twdb_regional_water_planning_areas()
    rasl = fetch_twdb_river_authorities_special_law_districts()
    places = fetch_texas_incorporated_places()
    cdps = fetch_texas_census_designated_places()
    urban = fetch_texas_urban_areas_2020_name_tx()
    rows = [
        ("tx-cd119.geojson", "U.S. House (119th)", cd),
        ("tx-sldu.geojson", "Texas Senate", sdu),
        ("tx-sldl.geojson", "Texas House", sdl),
        (
            "tx-sboe-plane2106.geojson",
            "Texas State Board of Education — Plan E2106 (Capitol Data shapefile)",
            sboe,
        ),
        (
            "tx-school-districts.geojson",
            "Texas school districts (Census: unified / secondary / elementary)",
            school,
        ),
        ("tx-water-districts.geojson", "Texas water districts (TCEQ)", water),
        (
            "tx-groundwater-conservation-districts.geojson",
            "Texas groundwater conservation districts (TCEQ GCD viewer)",
            gcd,
        ),
        (
            "tx-priority-groundwater-management-areas.geojson",
            "Texas priority groundwater management areas (TCEQ GCD viewer)",
            pgma,
        ),
        (
            "tx-groundwater-management-areas.geojson",
            "Texas groundwater management areas (TWDB)",
            gma,
        ),
        (
            "tx-regional-water-planning-areas.geojson",
            "Texas regional water planning areas (TWDB)",
            rwpa,
        ),
        (
            "tx-river-authorities-special-law-districts.geojson",
            "Texas river authorities and special law districts (TWDB)",
            rasl,
        ),
        (
            "tx-places-incorporated.geojson",
            "Texas incorporated places (Census TIGERweb)",
            places,
        ),
        (
            "tx-places-cdp.geojson",
            "Texas Census Designated Places (Census TIGERweb)",
            cdps,
        ),
        (
            "tx-urban-areas.geojson",
            "Texas urban areas, 2020 (Census TIGERweb; NAME LIKE '%, TX%')",
            urban,
        ),
    ]
    cpath = counties_geojson_path
    if cpath is None:
        from django.conf import settings

        cpath = Path(settings.BASE_DIR) / "static" / "geo" / "tx-counties.geojson"
    if cpath.is_file():
        rows.extend(fetch_texas_judicial_ballot_map_bundles(Path(cpath)))
    return rows
