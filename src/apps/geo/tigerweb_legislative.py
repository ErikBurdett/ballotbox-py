"""
Fetch Texas-only legislative boundaries from U.S. Census TIGERweb (GeoJSON).

Used by ``fetch_texas_legislative_geojson`` and documented alongside the Texas ballot map.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TIGERWEB_LEGISLATIVE_BASE = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Legislative/MapServer"
)
TX_STATE_WHERE = "STATE='48'"

# MapServer layer ids (119th Congress / 2024 SLD per TIGERweb service catalog)
LAYER_US_HOUSE_119 = 0
LAYER_TX_SENATE = 1
LAYER_TX_HOUSE = 2


def _query_url(*, layer_id: int, out_fields: str, result_offset: int | None, result_record_count: int | None) -> str:
    params: dict[str, str] = {
        "where": TX_STATE_WHERE,
        "f": "geojson",
        "outSR": "4326",
        "outFields": out_fields,
    }
    if result_record_count is not None:
        params["resultOffset"] = str(result_offset or 0)
        params["resultRecordCount"] = str(result_record_count)
    qs = urllib.parse.urlencode(params)
    return f"{TIGERWEB_LEGISLATIVE_BASE}/{layer_id}/query?{qs}"


def fetch_geojson_layer(*, layer_id: int, out_fields: str, timeout_s: float = 120.0) -> dict[str, Any]:
    """Single request (suitable for U.S. House and Texas Senate)."""
    url = _query_url(layer_id=layer_id, out_fields=out_fields, result_offset=None, result_record_count=None)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def fetch_geojson_paged(
    *, layer_id: int, out_fields: str, page_size: int = 50, max_offset: int = 600, timeout_s: float = 120.0
) -> dict[str, Any]:
    """Merge paged GeoJSON features (Texas House is large)."""
    all_features: list[dict[str, Any]] = []
    offset = 0
    while offset <= max_offset:
        url = _query_url(
            layer_id=layer_id,
            out_fields=out_fields,
            result_offset=offset,
            result_record_count=page_size,
        )
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:
                chunk = json.loads(resp.read().decode("utf-8", "ignore"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"TIGERweb request failed (offset={offset}): {exc}") from exc
        feats = chunk.get("features") or []
        if not isinstance(feats, list):
            break
        all_features.extend(feats)
        if len(feats) < page_size:
            break
        offset += page_size
    return {"type": "FeatureCollection", "features": all_features}


def fetch_texas_legislative_bundle() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Return (us_house_119_geojson, tx_senate_geojson, tx_house_geojson).

    ``outFields=*`` returns every attribute Census exposes on each layer (POP100, HU100,
    AREALAND, centroids, etc.) for richer map tooltips after bundling.
    """
    out = "*"
    cd = fetch_geojson_layer(layer_id=LAYER_US_HOUSE_119, out_fields=out)
    sdu = fetch_geojson_layer(layer_id=LAYER_TX_SENATE, out_fields=out)
    sdl = fetch_geojson_paged(layer_id=LAYER_TX_HOUSE, out_fields=out)
    return cd, sdu, sdl
