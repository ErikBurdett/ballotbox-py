"""
Texas intermediate appellate districts and statewide Court of Criminal Appeals overlays.

Court of Appeals district membership is taken from Texas Government Code §22.201 (2025 snapshot).
County boundaries come from the same bundled Census ``tx-counties.geojson`` used elsewhere on the ballot map.

* 1st and 14th districts cover the same counties in §22.201 — merged as one feature ``1-14``.
* 5th and 6th both include Hunt County — both polygons include that county (overlap on the map).
* 6th and 12th share several counties — overlaps preserved.
* 15th district is statewide per §22.201(p) — one polygon covering all counties.
* Court of Criminal Appeals is statewide criminal jurisdiction — one polygon (same geometry as 15th, but separate layer).

See: https://statutes.capitol.texas.gov/Docs/GV/htm/GV.22.htm#22.201
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from django.contrib.gis.geos import GEOSGeometry

# Statute uses "LaSalle"; Census county NAME is "La Salle".
STATUTE_COUNTY_NAME_FIXES: dict[str, str] = {
    "LaSalle": "La Salle",
}

# §22.201(b)-(o): comma-separated lists in statute order (Public.Law transcription).
_COA_STATUTE_SNIPPETS: dict[str, str] = {
    "1": "Austin, Brazoria, Chambers, Colorado, Fort Bend, Galveston, Grimes, Harris, Waller, and Washington",
    "2": "Archer, Clay, Cooke, Denton, Hood, Jack, Montague, Parker, Tarrant, Wichita, Wise, and Young",
    "3": "Bastrop, Bell, Blanco, Burnet, Caldwell, Coke, Comal, Concho, Fayette, Hays, Irion, Lampasas, Lee, Llano, McCulloch, Milam, Mills, Runnels, San Saba, Schleicher, Sterling, Tom Green, Travis, and Williamson",
    "4": "Atascosa, Bandera, Bexar, Brooks, Dimmit, Duval, Edwards, Frio, Gillespie, Guadalupe, Jim Hogg, Jim Wells, Karnes, Kendall, Kerr, Kimble, Kinney, LaSalle, McMullen, Mason, Maverick, Medina, Menard, Real, Starr, Sutton, Uvalde, Val Verde, Webb, Wilson, Zapata, and Zavala",
    "5": "Collin, Dallas, Grayson, Hunt, Kaufman, and Rockwall",
    "6": "Bowie, Camp, Cass, Delta, Fannin, Franklin, Gregg, Harrison, Hopkins, Hunt, Lamar, Marion, Morris, Panola, Red River, Rusk, Titus, Upshur, and Wood",
    "7": "Armstrong, Bailey, Briscoe, Carson, Castro, Childress, Cochran, Collingsworth, Cottle, Crosby, Dallam, Deaf Smith, Dickens, Donley, Floyd, Foard, Garza, Gray, Hale, Hall, Hansford, Hardeman, Hartley, Hemphill, Hockley, Hutchinson, Kent, King, Lamb, Lipscomb, Lubbock, Lynn, Moore, Motley, Ochiltree, Oldham, Parmer, Potter, Randall, Roberts, Sherman, Swisher, Terry, Wilbarger, Wheeler, and Yoakum",
    "8": "Andrews, Brewster, Crane, Crockett, Culberson, El Paso, Hudspeth, Jeff Davis, Loving, Pecos, Presidio, Reagan, Reeves, Terrell, Upton, Ward, and Winkler",
    "9": "Hardin, Jasper, Jefferson, Liberty, Montgomery, Newton, Orange, Polk, San Jacinto, and Tyler",
    "10": "Bosque, Burleson, Brazos, Coryell, Ellis, Falls, Freestone, Hamilton, Hill, Johnson, Leon, Limestone, Madison, McLennan, Navarro, Robertson, Somervell, and Walker",
    "11": "Baylor, Borden, Brown, Callahan, Coleman, Comanche, Dawson, Eastland, Ector, Erath, Fisher, Gaines, Glasscock, Haskell, Howard, Jones, Knox, Martin, Midland, Mitchell, Nolan, Palo Pinto, Scurry, Shackelford, Stephens, Stonewall, Taylor, and Throckmorton",
    "12": "Anderson, Angelina, Cherokee, Gregg, Henderson, Houston, Nacogdoches, Rains, Rusk, Sabine, San Augustine, Shelby, Smith, Trinity, Upshur, Van Zandt, and Wood",
    "13": "Aransas, Bee, Calhoun, Cameron, DeWitt, Goliad, Gonzales, Hidalgo, Jackson, Kenedy, Kleberg, Lavaca, Live Oak, Matagorda, Nueces, Refugio, San Patricio, Victoria, Wharton, and Willacy",
    "14": "Austin, Brazoria, Chambers, Colorado, Fort Bend, Galveston, Grimes, Harris, Waller, and Washington",
}


def _parse_county_names(snippet: str) -> list[str]:
    s = snippet.replace(" and ", ", ")
    parts = re.split(r",\s*", s)
    out: list[str] = []
    for p in parts:
        name = STATUTE_COUNTY_NAME_FIXES.get(p.strip(), p.strip())
        if name:
            out.append(name)
    return out


def coa_district_to_county_names() -> dict[str, frozenset[str]]:
    """Return raw §22.201 district → counties (1 and 14 still separate)."""
    return {k: frozenset(_parse_county_names(v)) for k, v in _COA_STATUTE_SNIPPETS.items()}


def coa_geo_district_spec() -> list[tuple[str, str, frozenset[str]]]:
    """
    Districts as drawn on the map: ``(COA_DIST id, label, counties)``.

    Merges 1 + 14 into ``1-14``. Drops standalone ``15`` here — added as statewide union in :func:`build_coa_geojson_features`.
    """
    raw = coa_district_to_county_names()
    one = raw["1"]
    fourteen = raw["14"]
    if one != fourteen:
        raise ValueError("Expected §22.201 First and Fourteenth COA districts to list the same counties for merge.")

    out: list[tuple[str, str, frozenset[str]]] = [
        ("1-14", "1st & 14th Courts of Appeals (Houston)", one),
    ]
    for key in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"):
        labels = {
            "2": "2nd Court of Appeals (Fort Worth)",
            "3": "3rd Court of Appeals (Austin)",
            "4": "4th Court of Appeals (San Antonio)",
            "5": "5th Court of Appeals (Dallas)",
            "6": "6th Court of Appeals (Texarkana)",
            "7": "7th Court of Appeals (Amarillo)",
            "8": "8th Court of Appeals (El Paso)",
            "9": "9th Court of Appeals (Beaumont)",
            "10": "10th Court of Appeals (Waco)",
            "11": "11th Court of Appeals (Eastland)",
            "12": "12th Court of Appeals (Tyler)",
            "13": "13th Court of Appeals (Corpus Christi–Edinburg)",
        }
        out.append((key, labels[key], raw[key]))
    return out


def _county_index_from_geojson(counties_fc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    feats = counties_fc.get("features")
    if not isinstance(feats, list):
        return {}
    by_name: dict[str, dict[str, Any]] = {}
    for feat in feats:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            continue
        name = str(props.get("NAME") or "").strip()
        if not name:
            continue
        by_name[name] = feat
    return by_name


def _union_geojson_geometries(geoms: list[dict[str, Any]]) -> GEOSGeometry:
    if not geoms:
        raise ValueError("no geometries to union")
    merged: GEOSGeometry | None = None
    for g in geoms:
        gg = GEOSGeometry(json.dumps(g))
        if gg.srid is None:
            gg.srid = 4326
        merged = gg if merged is None else merged.union(gg)
    assert merged is not None
    return merged


def build_statewide_texas_feature(counties_fc: dict[str, Any]) -> dict[str, Any]:
    """Single dissolved polygon for all Texas counties in the file."""
    feats = counties_fc.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("counties feature collection is empty")
    geoms = [f["geometry"] for f in feats if isinstance(f, dict) and isinstance(f.get("geometry"), dict)]
    u = _union_geojson_geometries(geoms)
    return {
        "type": "Feature",
        "properties": {
            "NAME": "State of Texas",
            "LAYER": "statewide",
        },
        "geometry": json.loads(u.geojson),
    }


def build_coa_geojson(counties_fc: dict[str, Any]) -> dict[str, Any]:
    """FeatureCollection: one polygon per COA region (+ 15th statewide). Overlaps preserved."""
    by_name = _county_index_from_geojson(counties_fc)
    out_features: list[dict[str, Any]] = []

    for dist_id, label, counties in coa_geo_district_spec():
        geoms: list[dict[str, Any]] = []
        missing: list[str] = []
        for c in sorted(counties):
            src = by_name.get(c)
            if not src or not isinstance(src.get("geometry"), dict):
                missing.append(c)
            else:
                geoms.append(src["geometry"])
        if missing:
            raise KeyError(f"COA district {dist_id}: counties missing from tx-counties.geojson: {missing!r}")
        u = _union_geojson_geometries(geoms)
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "COA_DIST": dist_id,
                    "COA_LABEL": label,
                    "SOURCE": "Texas Gov't Code §22.201 + Census county boundaries",
                },
                "geometry": json.loads(u.geojson),
            }
        )

    statewide = build_statewide_texas_feature(counties_fc)
    statewide["properties"] = {
        "COA_DIST": "15",
        "COA_LABEL": "15th Court of Appeals (statewide civil jurisdiction)",
        "SOURCE": "Texas Gov't Code §22.201(p); geometry from Census counties",
    }
    out_features.append(statewide)

    return {"type": "FeatureCollection", "features": out_features}


def build_cca_geojson(counties_fc: dict[str, Any]) -> dict[str, Any]:
    """Single statewide polygon for Court of Criminal Appeals jurisdiction (all Texas counties)."""
    f = build_statewide_texas_feature(counties_fc)
    f["properties"] = {
        "CCA": "Court of Criminal Appeals",
        "DESCRIPTION": "Statewide final court of appeal in criminal matters (Texas).",
        "SOURCE": "Geometry: union of Census Texas county boundaries",
    }
    return {"type": "FeatureCollection", "features": [f]}


def load_tx_counties_geojson_from_path(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_coa_county_coverage(counties_fc: dict[str, Any]) -> None:
    """
    Every Texas county in ``tx-counties.geojson`` must appear in at least one §22.201 district 1–14 list
    (15th is statewide and does not need explicit enumeration).
    """
    names = set(_county_index_from_geojson(counties_fc).keys())
    covered: set[str] = set()
    for _dist_id, _label, counties in coa_geo_district_spec():
        covered |= set(counties)
    missing = sorted(names - covered)
    extra = sorted(covered - names)
    if missing:
        raise ValueError(f"Counties in GeoJSON not listed in §22.201 (districts 1–14): {missing}")
    if extra:
        raise ValueError(f"§22.201 names not found as Census county NAME keys: {extra}")
