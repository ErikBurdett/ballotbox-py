"""
Texas Panhandle — county FIPS, sync coordinates, and district substring filters for Ballotpedia.

The 26 counties are the commonly cited “square” Panhandle set (see e.g. Texas Almanac / regional usage).
Coordinates are computed at sync time from ``static/geo/tx-counties.geojson`` (centroids).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry

# Five-digit FIPS (state 48 + county) for the 26 Panhandle counties.
PANHANDLE_COUNTY_FIPS: frozenset[str] = frozenset(
    {
        "48011",  # Armstrong
        "48045",  # Briscoe
        "48065",  # Carson
        "48069",  # Castro
        "48075",  # Childress
        "48087",  # Collingsworth
        "48111",  # Dallam
        "48117",  # Deaf Smith
        "48129",  # Donley
        "48179",  # Gray
        "48191",  # Hall
        "48195",  # Hansford
        "48205",  # Hartley
        "48211",  # Hemphill
        "48233",  # Hutchinson
        "48295",  # Lipscomb
        "48341",  # Moore
        "48357",  # Ochiltree
        "48359",  # Oldham
        "48369",  # Parmer
        "48375",  # Potter
        "48381",  # Randall
        "48393",  # Roberts
        "48421",  # Sherman
        "48437",  # Swisher
        "48483",  # Wheeler
    }
)

# Substrings for ``elections_by_state`` row filtering (office/district/race text, lowercased).
# Includes Panhandle county names, seats, and common place names.
TEXAS_PANHANDLE_DISTRICT_SUBSTRINGS: tuple[str, ...] = (
    # Amarillo metro (existing coverage)
    "amarillo",
    "potter",
    "randall",
    "canyon",
    "river road",
    "bushland",
    "hereford",
    "claude",
    "lake tanglewood",
    "timbercreek",
    # Panhandle counties & seats (26)
    "armstrong",
    "briscoe",
    "carson county",
    "castro county",
    "childress",
    "collingsworth",
    "dallam",
    "deaf smith",
    "donley",
    "gray county",
    "hall county",
    "hansford",
    "hartley",
    "hemphill",
    "hutchinson",
    "lipscomb",
    "moore county",
    "ochiltree",
    "oldham",
    "parmer",
    "roberts county",
    "sherman county",
    "swisher",
    "wheeler county",
    "dumas",
    "dalhart",
    "stratford",
    "spearman",
    "perryton",
    "borger",
    "pampa",
    "friona",
    "memphis",
    "clarendon",
    "shamrock",
    "wells",
    "panhandle",
    "stinnett",
    "miami",
    "canadian",
    "vega",
    "farwell",
    "sudan",
    "tulia",
    "happy",
    "quitaque",
    "silverton",
    "lockney",
    "flomot",
    "edmonson",
)

# Counties in ``load_panhandle_north_of_lubbock_county_points`` but not in the 26-county Panhandle set (substring filter).
TEXAS_PANHANDLE_NORTH_EXTRA_SUBSTRINGS: tuple[str, ...] = (
    "bailey",
    "cottle",
    "floyd",
    "foard",
    "hale",
    "hardeman",
    "lamb",
    "motley",
    "wilbarger",
    "muleshoe",
    "plainview",
    "vernon",
    "paducah",
    "childress county",
)

# Centroid must be north of Lubbock metro and west of Wichita Falls–adjacent plains (excludes Grayson / Red River).
PANHANDLE_NORTH_MIN_LAT: float = 33.62
PANHANDLE_NORTH_MAX_LON: float = -99.0

# When capping /election_dates/point calls, hit major High Plains anchors first (FIPS without ``48`` prefix).
_DATE_DISCOVERY_FIPS_PRIORITY: tuple[str, ...] = (
    "48375",
    "48381",
    "48117",
    "48111",
    "48421",
    "48195",
    "48205",
)


@lru_cache(maxsize=1)
def _tx_geojson_path() -> Path:
    return Path(settings.BASE_DIR) / "static" / "geo" / "tx-counties.geojson"


def load_panhandle_sync_points() -> list[dict[str, float | str]]:
    """
    One centroid per Panhandle county (for ``election_dates/point`` + ``elections_by_point`` + ``officeholders``).

    Returns dicts: ``slug``, ``lat``, ``long``, ``label``, ``fips``.
    """
    path = _tx_geojson_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, float | str]] = []
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = str(feat.get("id") or "").strip()
        if fid not in PANHANDLE_COUNTY_FIPS:
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        g = GEOSGeometry(json.dumps(geom))
        if g.srid is None:
            g.srid = 4326
        elif g.srid != 4326:
            g.transform(4326)
        c = g.centroid
        props = feat.get("properties") or {}
        name = str(props.get("NAME") or "").strip() or "County"
        slug = f"tx_pan_{fid}"
        out.append(
            {
                "slug": slug,
                "lat": float(c.y),
                "long": float(c.x),
                "label": f"{name} County",
                "fips": fid,
            }
        )
    return sorted(out, key=lambda x: str(x["slug"]))


def load_panhandle_north_of_lubbock_county_points(
    *,
    min_lat: float = PANHANDLE_NORTH_MIN_LAT,
    max_lon: float = PANHANDLE_NORTH_MAX_LON,
) -> list[dict[str, float | str]]:
    """
    County centroids for the High Plains / Panhandle band: north of Lubbock and west of ~99°W.

    Includes the 26 ``PANHANDLE_COUNTY_FIPS`` counties plus adjacent plains counties (e.g. Hale, Lamb, Floyd).
    """
    path = _tx_geojson_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, float | str]] = []
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = str(feat.get("id") or "").strip()
        if len(fid) != 5 or not fid.isdigit():
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        g = GEOSGeometry(json.dumps(geom))
        if g.srid is None:
            g.srid = 4326
        elif g.srid != 4326:
            g.transform(4326)
        c = g.centroid
        lat, lon = float(c.y), float(c.x)
        if lat < min_lat or lon > max_lon:
            continue
        props = feat.get("properties") or {}
        name = str(props.get("NAME") or "").strip() or "County"
        slug = f"tx_pan_{fid}"
        out.append(
            {
                "slug": slug,
                "lat": lat,
                "long": lon,
                "label": f"{name} County",
                "fips": fid,
            }
        )
    return sorted(out, key=lambda x: str(x["slug"]))


def pick_date_discovery_points(points: list[dict[str, float | str]], limit: int) -> list[dict[str, float | str]]:
    """Prefer metro / northern anchors so /election_dates/point still sees statewide dates with fewer HTTP calls."""
    if limit <= 0 or limit >= len(points):
        return list(points)
    seen_slugs: set[str] = set()
    ordered: list[dict[str, float | str]] = []
    for fid in _DATE_DISCOVERY_FIPS_PRIORITY:
        hit = next((p for p in points if str(p.get("fips")) == fid), None)
        if hit is not None and str(hit["slug"]) not in seen_slugs:
            ordered.append(hit)
            seen_slugs.add(str(hit["slug"]))
        if len(ordered) >= limit:
            return ordered[:limit]
    for p in sorted(points, key=lambda x: (-float(x["lat"]), str(x["slug"]))):
        if str(p["slug"]) in seen_slugs:
            continue
        ordered.append(p)
        seen_slugs.add(str(p["slug"]))
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def order_points_by_geo_election_record_count(points: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    """
    Ascending count of stored ``ballotpedia:geo_elections:{slug}:…`` SourceRecords (sparse counties first).
    """
    from collections import defaultdict

    from apps.ingestion.models import Provider, SourceRecord

    counts: defaultdict[str, int] = defaultdict(int)
    prefix = "ballotpedia:geo_elections:"
    qs = SourceRecord.objects.filter(provider=Provider.BALLOTPEDIA, external_id__startswith=prefix).values_list(
        "external_id", flat=True
    )
    for ext in qs:
        if not isinstance(ext, str) or not ext.startswith(prefix):
            continue
        rest = ext[len(prefix) :]
        slug = rest.split(":", 1)[0] if ":" in rest else ""
        if slug:
            counts[slug] += 1
    return sorted(points, key=lambda p: (counts[str(p["slug"])], str(p["slug"])))


def district_matches_texas_panhandle(district: dict) -> bool:
    """Keep ``/elections_by_state`` rows that mention Panhandle counties / places."""
    parts: list[str] = [str(district.get("name") or ""), str(district.get("type") or "")]
    for race in district.get("races") or []:
        if not isinstance(race, dict):
            continue
        ob = race.get("office") or {}
        if isinstance(ob, dict):
            parts.append(str(ob.get("name") or ""))
            parts.append(str(ob.get("seat") or ""))
    blob = " ".join(parts).lower()
    return any(s in blob for s in TEXAS_PANHANDLE_DISTRICT_SUBSTRINGS)


def district_matches_panhandle_north(district: dict) -> bool:
    """``elections_by_state`` filter: classic Panhandle substrings plus north-of-Lubbock plains counties."""
    if district_matches_texas_panhandle(district):
        return True
    parts: list[str] = [str(district.get("name") or ""), str(district.get("type") or "")]
    for race in district.get("races") or []:
        if not isinstance(race, dict):
            continue
        ob = race.get("office") or {}
        if isinstance(ob, dict):
            parts.append(str(ob.get("name") or ""))
            parts.append(str(ob.get("seat") or ""))
    blob = " ".join(parts).lower()
    return any(s in blob for s in TEXAS_PANHANDLE_NORTH_EXTRA_SUBSTRINGS)
