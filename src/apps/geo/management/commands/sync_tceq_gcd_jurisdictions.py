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
from apps.geo.texas_ballot_map_geo_fetch import fetch_tceq_groundwater_conservation_districts
from apps.offices.models import Office, OfficeBranch, OfficeLevel


def _titlecase_gcd_name(raw: str) -> str:
    s = " ".join((raw or "").strip().split())
    if not s:
        return ""
    if s.upper() == s:
        s = s.title()
    for old, new in {" Gcd": " GCD", "Gcd ": "GCD ", " Uwd": " UWD"}.items():
        s = s.replace(old, new)
    return s


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


def _load_gcd_geojson(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    default_path = Path(settings.BASE_DIR) / "static" / "geo" / "tx-groundwater-conservation-districts.geojson"
    if default_path.is_file():
        return json.loads(default_path.read_text(encoding="utf-8"))
    return fetch_tceq_groundwater_conservation_districts()


class Command(BaseCommand):
    help = (
        "Create/update Texas Groundwater Conservation District jurisdictions from TCEQ GCD GeoJSON, "
        "and create a default nonpartisan board office for each GCD."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--geojson-path",
            type=Path,
            default=None,
            help="Optional path to tx-groundwater-conservation-districts.geojson. Defaults to static/geo file or TCEQ fetch.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read the GCD features and print what would change without writing database rows.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        path = options["geojson_path"]
        fc = _load_gcd_geojson(path)
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
            raw_name = str(props.get("DISTNAME") or props.get("SHORTNAM") or "").strip()
            name = _titlecase_gcd_name(raw_name)
            geom = _multipolygon_from_geojson_geometry(feat.get("geometry") or {})
            if not name or geom is None:
                skipped += 1
                continue

            if dry:
                self.stdout.write(f"Would sync GCD jurisdiction: {name}")
                continue

            jurisdiction, j_created = Jurisdiction.objects.update_or_create(
                state="TX",
                jurisdiction_type=JurisdictionType.SPECIAL_DISTRICT,
                name=name,
                county="",
                city="",
                defaults={
                    "geom": geom,
                    "fips_code": str(props.get("DIST_NUM") or props.get("GWPACODE") or "").strip(),
                    "review_status": ReviewStatus.APPROVED,
                    "last_verified_at": now,
                    "review_notes": (
                        "Boundary and district metadata synced from TCEQ Public/GCDs MapServer. "
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
                name="Groundwater Conservation District Board Director",
                defaults={
                    "level": OfficeLevel.LOCAL,
                    "branch": OfficeBranch.OTHER,
                    "description": (
                        "Governing board for a Texas Groundwater Conservation District. "
                        "TCEQ metadata identifies whether the district reports elected or appointed board selection."
                    ),
                    "is_partisan": False,
                    "review_status": ReviewStatus.NEEDS_REVIEW,
                    "last_verified_at": now,
                    "review_notes": (
                        f"TCEQ election metadata: {props.get('ELECTION') or 'unknown'}. "
                        f"TCEQ district link: {props.get('WDDLINK') or props.get('TCEQ_REGISTRY') or ''}"
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
                "Synced TCEQ GCD jurisdictions: "
                f"{created_jurisdictions} created, {updated_jurisdictions} updated; "
                f"offices: {created_offices} created, {updated_offices} updated; skipped: {skipped}."
            )
        )
