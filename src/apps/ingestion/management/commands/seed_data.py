from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Seed local/dev data: fixtures + (optional) Democracy Works."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dw-state",
            default="TX",
            help="Two-letter state code to sync from Democracy Works (default: TX).",
        )
        parser.add_argument(
            "--skip-dw",
            action="store_true",
            help="Skip Democracy Works sync even if API key is configured.",
        )

    def handle(self, *args, **options):
        # 1) Local demo fixtures (fictional)
        for provider in [p for p, _label in Provider.choices if p != Provider.DEMOCRACY_WORKS]:
            run_id = sync_provider(provider)
            self.stdout.write(self.style.SUCCESS(f"{provider}: sync_run={run_id}"))

        # 2) Democracy Works (real API, requires API key)
        if options["skip_dw"]:
            self.stdout.write(self.style.WARNING("Skipping Democracy Works sync (--skip-dw)."))
            return

        state = (options["dw_state"] or "").strip().upper()
        if not state or len(state) != 2:
            self.stdout.write(self.style.ERROR("Invalid --dw-state (expected 2-letter code)."))
            return

        if not getattr(settings, "DEMOCRACY_WORKS_API_KEY", ""):
            self.stdout.write(
                self.style.WARNING(
                    "DEMOCRACY_WORKS_API_KEY not set; skipping Democracy Works sync."
                )
            )
            return

        # Override sync scope for this run without requiring a restart.
        sync_cfg = getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}
        sync_cfg["state_code"] = state
        sync_cfg["amarillo_metro"] = False
        addr = (sync_cfg.get("address") or {}) if isinstance(sync_cfg, dict) else {}
        if isinstance(addr, dict):
            addr["street"] = ""
            addr["city"] = ""
            addr["state_code"] = ""
            addr["zip"] = ""
            addr["zip4"] = ""
        settings.DEMOCRACY_WORKS_SYNC = sync_cfg

        run_id = sync_provider(Provider.DEMOCRACY_WORKS)
        self.stdout.write(self.style.SUCCESS(f"democracy_works({state}): sync_run={run_id}"))

