from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.geo.texas_ballot_map_geo_fetch import (
    fetch_tceq_groundwater_conservation_districts,
    fetch_tceq_priority_groundwater_management_areas,
    fetch_twdb_groundwater_management_areas,
    fetch_twdb_regional_water_planning_areas,
    fetch_twdb_river_authorities_special_law_districts,
)


class Command(BaseCommand):
    help = (
        "Download water planning GeoJSON bundles into static/geo/: TCEQ GCD/PGMA, "
        "TWDB GMA/RWPA, and TWDB River Authorities/Special Law Districts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch from TCEQ but print sizes only; do not write files.",
        )

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        geo_dir = Path(settings.BASE_DIR) / "static" / "geo"

        self.stdout.write("Fetching water governance / planning layers (TCEQ + TWDB)...")
        bundles = [
            (
                "tx-groundwater-conservation-districts.geojson",
                "Texas groundwater conservation districts (TCEQ GCD viewer)",
                fetch_tceq_groundwater_conservation_districts(),
            ),
            (
                "tx-priority-groundwater-management-areas.geojson",
                "Texas priority groundwater management areas (TCEQ GCD viewer)",
                fetch_tceq_priority_groundwater_management_areas(),
            ),
            (
                "tx-groundwater-management-areas.geojson",
                "Texas groundwater management areas (TWDB)",
                fetch_twdb_groundwater_management_areas(),
            ),
            (
                "tx-regional-water-planning-areas.geojson",
                "Texas regional water planning areas (TWDB)",
                fetch_twdb_regional_water_planning_areas(),
            ),
            (
                "tx-river-authorities-special-law-districts.geojson",
                "Texas river authorities and special law districts (TWDB)",
                fetch_twdb_river_authorities_special_law_districts(),
            ),
        ]

        for fname, label, data in bundles:
            feats = data.get("features") if isinstance(data, dict) else None
            n = len(feats) if isinstance(feats, list) else 0
            raw = json.dumps(data, separators=(",", ":"))
            size_kb = len(raw.encode("utf-8")) / 1024.0
            self.stdout.write(f"  {label}: {n} features, {size_kb:.1f} KiB -> {fname}")
            if dry:
                continue
            geo_dir.mkdir(parents=True, exist_ok=True)
            out = geo_dir / fname
            out.write_text(raw, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"  Wrote {out}"))

        if dry:
            self.stdout.write(self.style.WARNING("Dry run: no files written."))
        else:
            self.stdout.write(self.style.SUCCESS("Done. Reload /texas/ballot-map/ to enable GCD / PGMA toggles."))
