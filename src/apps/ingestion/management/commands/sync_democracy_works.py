from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.ingestion.http.democracy_works import DemocracyWorksClient, DemocracyWorksError
from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Sync Democracy Works elections + contests + candidates into normalized tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--state",
            type=str,
            default="",
            help="Two-letter state code to sync (defaults to DEMOCRACY_WORKS_STATE_CODE, else TX).",
        )
        parser.add_argument(
            "--election-year",
            type=str,
            default="",
            help="Election year scope (YYYY). Ignored if --start-date/--end-date/--all provided.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Start date scope (YYYY-MM-DD). If set, overrides --election-year.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="End date scope (YYYY-MM-DD). If set, overrides --election-year.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Full backfill scope for the state (defaults to 2020-01-01 through ~2 years ahead).",
        )
        parser.add_argument(
            "--amarillo-metro",
            action="store_true",
            help=(
                "Fetch ballots for Amarillo, TX using several ZIPs (Potter + Randall coverage). "
                "Honors --election-year / --start-date / --end-date / --all like state sync."
            ),
        )
        parser.add_argument(
            "--with-photos",
            action="store_true",
            help="After DW sync, enrich headshots via Ballotpedia links.",
        )
        parser.add_argument(
            "--photo-limit",
            type=int,
            default=2500,
            help="Max people to process for Ballotpedia photos when using --with-photos (default: 2500).",
        )
        parser.add_argument(
            "--photo-sleep-ms",
            type=int,
            default=300,
            help="Delay between Ballotpedia requests in milliseconds (default: 300).",
        )
        parser.add_argument(
            "--photo-fresh-days",
            type=int,
            default=30,
            help="Skip Ballotpedia refetch if fetched within N days (default: 30).",
        )
        parser.add_argument(
            "--photo-force",
            action="store_true",
            help="Force Ballotpedia refetch and overwrite Person.photo_url (never overwrites manual_photo_url).",
        )

    @staticmethod
    def _parse_iso_date(value: str) -> date | None:
        v = (value or "").strip()
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except Exception:
            return None

    def handle(self, *args, **options):
        if not (getattr(settings, "DEMOCRACY_WORKS_API_KEY", "") or "").strip():
            self.stdout.write(
                self.style.WARNING(
                    "DEMOCRACY_WORKS_API_KEY is not set (or expired). Skipping — existing Democracy Works "
                    "data in the database is unchanged. For new fetches use: "
                    "python manage.py sync_ballotpedia_geographic"
                )
            )
            return

        # Allow running without container restart by mutating settings for this process.
        sync_cfg = getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}
        if not isinstance(sync_cfg, dict):
            sync_cfg = {}

        state = (options.get("state") or "").strip().upper()
        if not state:
            state = str(sync_cfg.get("state_code") or "").strip().upper() or "TX"
        if len(state) != 2:
            self.stdout.write(self.style.ERROR("Invalid --state (expected 2-letter code)."))
            return

        election_year = (options.get("election_year") or "").strip()
        start_date = self._parse_iso_date(options.get("start_date") or "")
        end_date = self._parse_iso_date(options.get("end_date") or "")
        do_all = bool(options.get("all"))

        if do_all:
            start_date = date(2020, 1, 1)
            end_date = date.today() + timedelta(days=365 * 2)
            election_year = ""

        if start_date or end_date:
            # Date range overrides year.
            election_year = ""

        sync_cfg["state_code"] = state
        sync_cfg["election_year"] = election_year
        sync_cfg["start_date"] = start_date.isoformat() if start_date else ""
        sync_cfg["end_date"] = end_date.isoformat() if end_date else ""
        addr = (sync_cfg.get("address") or {})
        if not isinstance(addr, dict):
            addr = {}
        addr["street"] = ""
        addr["city"] = ""
        addr["state_code"] = ""
        addr["zip"] = ""
        addr["zip4"] = ""
        sync_cfg["address"] = addr
        # CLI runs do not inherit DEMOCRACY_WORKS_AMARILLO_METRO unless --amarillo-metro is passed.
        sync_cfg["amarillo_metro"] = bool(options.get("amarillo_metro"))
        settings.DEMOCRACY_WORKS_SYNC = sync_cfg

        # Fail fast with a clear error if the key is invalid or quota is exhausted,
        # rather than creating stuck SyncRuns.
        try:
            client = DemocracyWorksClient(
                api_key=getattr(settings, "DEMOCRACY_WORKS_API_KEY", ""),
                base_url=getattr(settings, "DEMOCRACY_WORKS_API_BASE_URL", "https://api.democracy.works/v2"),
                timeout_s=10,
                max_attempts=1,
                max_backoff_s=0.0,
            )
            if sync_cfg.get("amarillo_metro"):
                client.list_elections(
                    params={
                        "addressStreet": "601 S Buchanan St",
                        "addressCity": "Amarillo",
                        "addressStateCode": "TX",
                        "addressZip": "79101",
                        "startDate": sync_cfg.get("start_date") or "",
                        "endDate": sync_cfg.get("end_date") or "",
                        "includeBallotData": "false",
                        "pageSize": 1,
                        "page": 1,
                    }
                )
            else:
                client.list_elections(
                    params={
                        "stateCode": state,
                        "startDate": sync_cfg.get("start_date") or "",
                        "endDate": sync_cfg.get("end_date") or "",
                        "includeBallotData": "false",
                        "pageSize": 1,
                        "page": 1,
                    }
                )
        except DemocracyWorksError as exc:
            msg = str(exc)
            if "http 429" in msg.lower() or "limit exceeded" in msg.lower():
                self.stdout.write(
                    self.style.ERROR(
                        "Democracy Works API quota/rate-limit is currently exhausted (HTTP 429 Limit Exceeded). "
                        "Rotate to a fresh key/quota or wait for the quota window to reset, then re-run this command."
                    )
                )
                return
            if "http 403" in msg.lower() or "forbidden" in msg.lower():
                self.stdout.write(
                    self.style.ERROR(
                        "Democracy Works API returned HTTP 403 Forbidden. This usually means the API key is invalid/revoked "
                        "(or missing). Update `DEMOCRACY_WORKS_API_KEY` and re-run."
                    )
                )
                return
            raise

        scope_label = ""
        if sync_cfg.get("amarillo_metro"):
            if do_all:
                scope_label = f"Amarillo metro {start_date.isoformat()}..{end_date.isoformat()} (all)"
            elif start_date or end_date:
                scope_label = f"Amarillo metro {sync_cfg['start_date'] or '...'}..{sync_cfg['end_date'] or '...'}"
            elif election_year:
                scope_label = f"Amarillo metro year={election_year}"
            else:
                scope_label = "Amarillo metro (default dates: current election year)"
        elif do_all:
            scope_label = f"{state} {start_date.isoformat()}..{end_date.isoformat()} (all)"
        elif start_date or end_date:
            scope_label = f"{state} {sync_cfg['start_date'] or '...'}..{sync_cfg['end_date'] or '...'}"
        elif election_year:
            scope_label = f"{state} year={election_year}"
        else:
            scope_label = f"{state} (default)"

        self.stdout.write(self.style.WARNING(f"Democracy Works sync scope: {scope_label}"))
        run_id = sync_provider(Provider.DEMOCRACY_WORKS)
        self.stdout.write(self.style.SUCCESS(f"democracy_works: sync_run={run_id}"))

        if bool(options.get("with_photos")):
            photo_limit = int(options.get("photo_limit") or 2500)
            photo_sleep_ms = int(options.get("photo_sleep_ms") or 300)
            photo_fresh_days = int(options.get("photo_fresh_days") or 30)
            photo_force = bool(options.get("photo_force"))
            call_command(
                "sync_ballotpedia_photos",
                limit=photo_limit,
                sleep_ms=photo_sleep_ms,
                fresh_days=photo_fresh_days,
                force=photo_force,
                state=state,
            )

