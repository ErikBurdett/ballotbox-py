from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

from apps.geo.public_views import _jurisdiction_hub_context
from apps.geo.texas_county_boundaries import resolve_jurisdiction_for_texas_county_feature, texas_county_feature_for_point

# Approximate Texas bounds (WGS84) for soft validation
_TX_LON = (-106.65, -93.51)
_TX_LAT = (25.84, 36.50)


def _parse_lon_lat(request) -> tuple[float, float] | None:
    try:
        lon = float(request.GET.get("lng") or request.GET.get("lon") or "")
        lat = float(request.GET.get("lat") or "")
    except (TypeError, ValueError):
        return None
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return lon, lat


def _in_texas_bbox(lon: float, lat: float) -> bool:
    return _TX_LON[0] <= lon <= _TX_LON[1] and _TX_LAT[0] <= lat <= _TX_LAT[1]


def _legislative_geojson_urls() -> dict[str, str | bool]:
    """
    URLs for bundled map overlays (same pattern as tx-counties.geojson).

    Files are produced by ``manage.py fetch_texas_legislative_geojson`` (legislative, SBOE PLANE2106,
    places / CDPs / urban areas from Census, merged school districts, TCEQ water, etc.)
    so the map does not call remote APIs on each page view.
    """
    geo_dir = Path(settings.BASE_DIR) / "static" / "geo"

    def _u(filename: str) -> str:
        if (geo_dir / filename).is_file():
            return static(f"geo/{filename}")
        return ""

    cd = _u("tx-cd119.geojson")
    sdu = _u("tx-sldu.geojson")
    sdl = _u("tx-sldl.geojson")
    school = _u("tx-school-districts.geojson")
    water = _u("tx-water-districts.geojson")
    sboe = _u("tx-sboe-plane2106.geojson")
    coa = _u("tx-coa-districts.geojson")
    cca = _u("tx-cca-statewide.geojson")
    gcd = _u("tx-groundwater-conservation-districts.geojson")
    pgma = _u("tx-priority-groundwater-management-areas.geojson")
    gma = _u("tx-groundwater-management-areas.geojson")
    rwpa = _u("tx-regional-water-planning-areas.geojson")
    rasl = _u("tx-river-authorities-special-law-districts.geojson")
    places = _u("tx-places-incorporated.geojson")
    cdp = _u("tx-places-cdp.geojson")
    urban = _u("tx-urban-areas.geojson")
    return {
        "tx_cd119_geojson_url": cd,
        "tx_sldu_geojson_url": sdu,
        "tx_sldl_geojson_url": sdl,
        "tx_sboe_geojson_url": sboe,
        "tx_school_geojson_url": school,
        "tx_water_geojson_url": water,
        "tx_coa_geojson_url": coa,
        "tx_cca_geojson_url": cca,
        "tx_gcd_geojson_url": gcd,
        "tx_pgma_geojson_url": pgma,
        "tx_gma_geojson_url": gma,
        "tx_rwpa_geojson_url": rwpa,
        "tx_rasl_geojson_url": rasl,
        "tx_places_incorporated_geojson_url": places,
        "tx_places_cdp_geojson_url": cdp,
        "tx_urban_areas_geojson_url": urban,
        "legislative_geo_bundled": bool(
            cd and sdu and sdl and sboe and school and water and gcd and pgma and gma and rwpa and rasl and places and cdp and urban
        ),
    }


@require_GET
def texas_ballot_map(request):
    ctx = {
        "tx_counties_geojson_url": static("geo/tx-counties.geojson"),
        **_legislative_geojson_urls(),
    }
    return render(request, "geo/texas_ballot_map.html", ctx)


@require_GET
def texas_ballot_map_context(request):
    parsed = _parse_lon_lat(request)
    if parsed is None:
        return render(
            request,
            "geo/texas_ballot_map_context.html",
            {
                "error": "Select a location on the map (or search for a Texas address).",
                "county_label": "",
                "jurisdiction": None,
                "offices": [],
                "current_terms": [],
                "elections": [],
                "races": [],
                "sources": [],
                "canonical_url": "",
            },
        )
    lon, lat = parsed
    feature = texas_county_feature_for_point(lon, lat)
    if feature is None:
        msg = (
            "No Texas county boundary contains this point."
            if _in_texas_bbox(lon, lat)
            else "This point appears to be outside Texas. Try a location inside the state."
        )
        return render(
            request,
            "geo/texas_ballot_map_context.html",
            {
                "error": msg,
                "county_label": "",
                "jurisdiction": None,
                "offices": [],
                "current_terms": [],
                "elections": [],
                "races": [],
                "sources": [],
                "canonical_url": "",
            },
        )

    props = feature.get("properties") or {}
    county_label = str(props.get("NAME") or "").strip()
    if (props.get("LSAD") or "").strip().lower() == "county" and county_label and "county" not in county_label.lower():
        county_display = f"{county_label} County"
    else:
        county_display = county_label or "Unknown county"

    jurisdiction = resolve_jurisdiction_for_texas_county_feature(feature)
    if jurisdiction is None:
        return render(
            request,
            "geo/texas_ballot_map_context.html",
            {
                "error": (
                    f"We matched {county_display} on the map, but there is no matching "
                    "county jurisdiction in the database yet. Run ingestion when data is available."
                ),
                "county_label": county_display,
                "jurisdiction": None,
                "offices": [],
                "current_terms": [],
                "elections": [],
                "races": [],
                "sources": [],
                "canonical_url": "",
            },
        )

    ctx = _jurisdiction_hub_context(request, jurisdiction)
    ctx["county_label"] = county_display
    ctx["geo_match_note"] = f"Showing data for {county_display} (point: {lat:.4f}, {lon:.4f})."
    ctx["error"] = ""
    return render(request, "geo/texas_ballot_map_context.html", ctx)


@require_GET
def texas_ballot_map_geocode(request):
    """
    Proxy to the U.S. Census geocoder (no API key). Returns JSON ``lat``, ``lng``, ``display``.
    """
    q = (request.GET.get("q") or request.GET.get("address") or "").strip()
    if not q or len(q) > 240:
        return HttpResponseBadRequest("Missing or invalid address")

    params = urllib.parse.urlencode(
        {
            "address": q,
            "benchmark": "Public_AR_Current",
            "format": "json",
        }
    )
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{params}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "Geocoder request failed. Try again or click the map."}, status=502)

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        return JsonResponse({"ok": False, "error": "No match found. Include street, city, and ZIP if possible."})

    m0 = matches[0]
    coords = m0.get("coordinates") or {}
    try:
        lng = float(coords["x"])
        lat = float(coords["y"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Unexpected geocoder response."}, status=502)

    matched = m0.get("matchedAddress") or q
    return JsonResponse({"ok": True, "lat": lat, "lng": lng, "display": matched})
