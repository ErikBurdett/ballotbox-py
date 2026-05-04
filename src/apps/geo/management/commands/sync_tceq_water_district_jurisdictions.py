from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import ReviewStatus
from apps.geo.models import Jurisdiction, JurisdictionType
from apps.geo.texas_ballot_map_geo_fetch import fetch_tceq_water_districts
from apps.offices.models import Office, OfficeBranch, OfficeLevel


TYPE_LABELS = {
    "DD": "Drainage District",
    "FWSD": "Fresh Water Supply District",
    "GCD": "Groundwater Conservation District",
    "ID": "Irrigation District",
    "LID": "Levee Improvement District",
    "MD": "Management District",
    "MMD": "Municipal Management District",
    "MUD": "Municipal Utility District",
    "ND": "Navigation District",
    "OTH": "Other Water District",
    "RA": "River Authority",
    "RD": "Regional District",
    "SCD": "Storm Water Control District",
    "SUD": "Special Utility District",
    "SWCD": "Soil & Water Conservation District",
    "WCID": "Water Control & Improvement District",
    "WID": "Water Improvement District",
}


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").strip().split())


def _multipolygon_from_geojson_geometry(geom: dict[str, Any]) -> MultiPolygon | None:
    if not isinstance(geom, dict):
        return None
    g = GEOSGeometry(json.dumps(geom))
    if g.srid is None:
        g.srid = 4326
    if isinstance(g, Polygon):
        return MultiPolygon(g, srid=4326)
    if isinstance(g, MultiPolygon):
        g.srid = 4326
        return g
    return None


def _load_water_geojson(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    default_path = Path(settings.BASE_DIR) / "static" / "geo" / "tx-water-districts.geojson"
    if default_path.is_file():
        return json.loads(default_path.read_text(encoding="utf-8"))
    return fetch_tceq_water_districts()


class Command(BaseCommand):
    help = (
        "Create/update Texas water district jurisdictions from TCEQ WaterDistricts GeoJSON, "
        "and create a default nonpartisan board office for each district."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--geojson-path",
            type=Path,
            default=None,
            help="Optional path to tx-water-districts.geojson. Defaults to static/geo file or TCEQ fetch.",
        )
        parser.add_argument(
            "--types",
            default="",
            help="Optional comma-separated TYPE codes to sync, e.g. MUD,WCID,SUD,RA.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read features and print what would change without writing database rows.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        path = options["geojson_path"]
        type_filter = {v.strip().upper() for v in (options["types"] or "").split(",") if v.strip()}
        fc = _load_water_geojson(path)
        feats = fc.get("features") if isinstance(fc, dict) else None
        if not isinstance(feats, list):
            raise ValueError("Expected a GeoJSON FeatureCollection with a features array")

        created_jurisdictions = 0
        updated_jurisdictions = 0
        created_offices = 0
        updated_offices = 0
        skipped = 0
        now = timezone.now()

        for feat in feats:
            if not isinstance(feat, dict):
                skipped += 1
                continue
            props = feat.get("properties") or {}
            if not isinstance(props, dict):
                skipped += 1
                continue
            type_code = str(props.get("TYPE") or "").strip().upper()
            if type_filter and type_code not in type_filter:
                continue
            name = _clean_name(str(props.get("NAME") or ""))
            geom = _multipolygon_from_geojson_geometry(feat.get("geometry") or {})
            if not name or geom is None:
                skipped += 1
                continue

            label = TYPE_LABELS.get(type_code, "Water District")
            if dry:
                self.stdout.write(f"Would sync {type_code or 'UNK'} jurisdiction: {name}")
                continue

            jurisdiction, j_created = Jurisdiction.objects.update_or_create(
                state="TX",
                jurisdiction_type=JurisdictionType.SPECIAL_DISTRICT,
                name=name,
                county=str(props.get("COUNTY") or "").strip(),
                city="",
                defaults={
                    "geom": geom,
                    "fips_code": str(props.get("DISTRICT_ID") or "").strip(),
                    "review_status": ReviewStatus.APPROVED,
                    "last_verified_at": now,
                    "review_notes": (
                        f"TCEQ water district TYPE={type_code or 'unknown'} ({label}); "
                        f"status={props.get('STATUS') or 'unknown'}. "
                        "Board members/candidates must be added from district or election sources."
                    ),
                },
            )
            if j_created:
                created_jurisdictions += 1
            else:
                updated_jurisdictions += 1

            _, o_created = Office.objects.update_or_create(
                jurisdiction=jurisdiction,
                name=f"{label} Board Director",
                defaults={
                    "level": OfficeLevel.LOCAL,
                    "branch": OfficeBranch.OTHER,
                    "description": f"Governing board for a Texas {label}.",
                    "is_partisan": False,
                    "review_status": ReviewStatus.NEEDS_REVIEW,
                    "last_verified_at": now,
                    "review_notes": (
                        f"Created from TCEQ WaterDistricts metadata. TYPE={type_code or 'unknown'}, "
                        f"district_id={props.get('DISTRICT_ID') or ''}."
                    ),
                },
            )
            if o_created:
                created_offices += 1
            else:
                updated_offices += 1

        if dry:
            self.stdout.write(self.style.WARNING("Dry run: no database rows written."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Synced TCEQ water district jurisdictions: "
                f"{created_jurisdictions} created, {updated_jurisdictions} updated; "
                f"offices: {created_offices} created, {updated_offices} updated; skipped: {skipped}."
            )
        )
