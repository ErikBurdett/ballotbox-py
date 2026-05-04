from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.geo.texas_ballot_map_geo_fetch import fetch_all_ballot_map_geo_bundles


class Command(BaseCommand):
    help = (
        "Download Texas ballot map GeoJSON bundles into static/geo/: Census TIGERweb legislative (House/Senate), "
        "Texas Legislative Council SBOE Plan E2106 (tx-sboe-plane2106.geojson from Capitol Data zip), "
        "Census School (unified + secondary + elementary merged as tx-school-districts.geojson), "
        "TCEQ water districts (tx-water-districts.geojson), "
        "TCEQ GCD Viewer groundwater conservation districts and PGMAs "
        "(tx-groundwater-conservation-districts.geojson, tx-priority-groundwater-management-areas.geojson), "
        "TWDB GMA/RWPA/RASL planning boundaries, "
        "Census TIGERweb incorporated places + CDPs + 2020 urban areas (tx-places-*.geojson, tx-urban-areas.geojson), "
        "plus — when static/geo/tx-counties.geojson is present — "
        "Texas Courts of Appeals polygons (tx-coa-districts.geojson, Gov't Code §22.201 county dissolve) and "
        "Court of Criminal Appeals statewide (tx-cca-statewide.geojson). "
        "The map loads these like tx-counties.geojson — instant toggles. Large outputs are gitignored by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch from Census but print sizes only; do not write files.",
        )

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        geo_dir = Path(settings.BASE_DIR) / "static" / "geo"

        self.stdout.write(
            "Fetching legislative (Census), school / places / urban (Census), "
            "water / GCD / PGMA (TCEQ), and appellate (county dissolve)…"
        )
        bundles = fetch_all_ballot_map_geo_bundles()

        for fname, label, data in bundles:
            feats = data.get("features") if isinstance(data, dict) else None
            n = len(feats) if isinstance(feats, list) else 0
            raw = json.dumps(data, separators=(",", ":"))
            size_kb = len(raw.encode("utf-8")) / 1024.0
            self.stdout.write(f"  {label}: {n} features, {size_kb:.1f} KiB → {fname}")
            if dry:
                continue
            geo_dir.mkdir(parents=True, exist_ok=True)
            out = geo_dir / fname
            out.write_text(raw, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"  Wrote {out}"))

        if dry:
            self.stdout.write(self.style.WARNING("Dry run: no files written."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Done. Reload /texas/ballot-map/ — district layers load from static files and toggle instantly."
                )
            )
