from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.geo.merge_jurisdictions import iter_duplicate_jurisdiction_groups, merge_duplicate_groups
from apps.geo.models import JurisdictionType


class Command(BaseCommand):
    help = (
        "Merge duplicate Jurisdiction rows (same state, type, and slugified name). "
        "Run after ingestion fixes or to clean historical duplicates (e.g. multiple Potter County rows)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--state", default="TX", help="Two-letter state code (default: TX).")
        parser.add_argument(
            "--types",
            default="county,city,town,village,borough,township",
            help="Comma-separated jurisdiction_type values to scan.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log merge groups only; do not write to the database.",
        )

    def handle(self, *args, **options):
        state = (options["state"] or "").strip().upper()
        if len(state) != 2:
            self.stderr.write(self.style.ERROR("Invalid --state (expected 2 letters)."))
            return
        raw_types = [t.strip() for t in (options["types"] or "").split(",") if t.strip()]
        allowed = {c[0] for c in JurisdictionType.choices}
        types = [t for t in raw_types if t in allowed]
        if not types:
            self.stderr.write(self.style.ERROR("No valid jurisdiction types in --types."))
            return

        if options["dry_run"]:
            groups = iter_duplicate_jurisdiction_groups(state=state, jurisdiction_types=types)
            for g in groups:
                keeper, *dups = sorted(g, key=lambda x: x.id)
                self.stdout.write(
                    f"  Would keep id={keeper.id} {keeper.name!r} ({keeper.jurisdiction_type}); "
                    f"merge away ids={[d.id for d in dups]}"
                )
            self.stdout.write(self.style.WARNING(f"Dry run: {len(groups)} duplicate group(s); no DB writes."))
            return
        merged_groups, agg = merge_duplicate_groups(state=state, jurisdiction_types=types, dry_run=False)
        self.stdout.write(self.style.SUCCESS(f"Merged {merged_groups} duplicate group(s). Stats: {agg!r}"))
