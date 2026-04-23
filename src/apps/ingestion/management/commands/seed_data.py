from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Seed local/dev data: demo fixtures + optional Ballotpedia geographic sync; Democracy Works is opt-in only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-ballotpedia-geo",
            action="store_true",
            help="Skip Ballotpedia geographic API sync even if BALLOTPEDIA_API_KEY is set.",
        )
        parser.add_argument(
            "--with-dw",
            action="store_true",
            help="Legacy: run Democracy Works when DEMOCRACY_WORKS_API_KEY is configured.",
        )
        parser.add_argument(
            "--dw-state",
            default="TX",
            help="Two-letter state code for optional Democracy Works sync (with --with-dw).",
        )

    def handle(self, *args, **options):
        # 1) Local demo fixtures (fictional) — excludes Democracy Works; Ballotpedia fixture skipped when API key set.
        for provider in [p for p, _label in Provider.choices if p != Provider.DEMOCRACY_WORKS]:
            run_id = sync_provider(provider)
            self.stdout.write(self.style.SUCCESS(f"{provider}: sync_run={run_id}"))

        # 2) Ballotpedia geographic (real API — primary source for new election data when key is set)
        if options["skip_ballotpedia_geo"]:
            self.stdout.write(self.style.WARNING("Skipping Ballotpedia geographic sync (--skip-ballotpedia-geo)."))
        elif not getattr(settings, "BALLOTPEDIA_API_KEY", ""):
            self.stdout.write(
                self.style.WARNING(
                    "BALLOTPEDIA_API_KEY not set; skipping Ballotpedia geographic sync."
                )
            )
        else:
            geo_kwargs: dict = {
                "max_requests": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_REQUESTS", 160)),
                "max_election_dates": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_ELECTION_DATES", 14)),
                "max_tx_calendar_pages": int(getattr(settings, "BALLOTPEDIA_GEO_MAX_TX_CALENDAR_PAGES", 10)),
                "tx_local_state_pages": int(getattr(settings, "BALLOTPEDIA_GEO_TX_LOCAL_STATE_PAGES", 1)),
                "skip_if_fetched_days": int(getattr(settings, "BALLOTPEDIA_GEO_SKIP_IF_FETCHED_DAYS", 1)),
            }
            geo_preset = (getattr(settings, "BALLOTPEDIA_GEO_PRESET", "") or "").strip().lower()
            if geo_preset == "panhandle":
                geo_kwargs["preset"] = "panhandle"
            elif geo_preset == "panhandle_north":
                geo_kwargs["preset"] = "panhandle_north"
            if bool(getattr(settings, "BALLOTPEDIA_GEO_WITH_OFFICEHOLDERS", False)):
                geo_kwargs["with_officeholders"] = True
            if bool(getattr(settings, "BALLOTPEDIA_GEO_GEOGRAPHIC_ONLY", False)):
                geo_kwargs["geographic_only"] = True
            call_command("sync_ballotpedia_geographic", **geo_kwargs)
            self.stdout.write(self.style.SUCCESS("Ballotpedia geographic sync finished."))

        # 3) Optional legacy Democracy Works
        if not options["with_dw"]:
            return

        state = (options["dw_state"] or "").strip().upper()
        if not state or len(state) != 2:
            self.stdout.write(self.style.ERROR("Invalid --dw-state (expected 2-letter code)."))
            return

        if not getattr(settings, "DEMOCRACY_WORKS_API_KEY", ""):
            self.stdout.write(
                self.style.WARNING(
                    "DEMOCRACY_WORKS_API_KEY not set; skipping optional Democracy Works sync (--with-dw)."
                )
            )
            return

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
