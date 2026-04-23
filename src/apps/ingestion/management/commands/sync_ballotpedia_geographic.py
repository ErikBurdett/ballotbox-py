from __future__ import annotations

import json
import time
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ingestion.http.ballotpedia_geographic import BallotpediaGeographicClient, BallotpediaGeographicError
from apps.ingestion.models import Provider, SourceRecord, SyncRun, SyncStatus
from apps.ingestion.normalizers.ballotpedia_geographic import (
    normalize_ballotpedia_elections_by_point,
    normalize_ballotpedia_elections_by_state_filtered,
    normalize_ballotpedia_officeholders,
    record_ballotpedia_raw_payload,
)
from apps.ingestion.texas_panhandle import (
    district_matches_panhandle_north,
    district_matches_texas_panhandle,
    load_panhandle_north_of_lubbock_county_points,
    load_panhandle_sync_points,
    order_points_by_geo_election_record_count,
    pick_date_discovery_points,
)

# Multiple coordinates improve ``elections_by_point`` coverage (city vs county vs school-district ballots).
# See https://developer.ballotpedia.org/geographic-apis/practical-guide
def _payload_data_as_dict(body: dict) -> dict:
    """Coerce ``body['data']`` to dict (Ballotpedia occasionally returns a string or null)."""
    if not isinstance(body, dict):
        return {}
    raw = body.get("data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


DEFAULT_POINTS: list[dict[str, float | str]] = [
    {"slug": "potter_amarillo", "lat": 35.2080, "long": -101.8307, "label": "Potter County (Amarillo)"},
    {"slug": "randall_canyon", "lat": 34.9797, "long": -101.9188, "label": "Randall County (Canyon)"},
    {"slug": "amarillo_north", "lat": 35.2700, "long": -101.8310, "label": "Amarillo (north)"},
    {"slug": "amarillo_south", "lat": 35.1500, "long": -101.8750, "label": "Amarillo (south)"},
    {"slug": "amarillo_east", "lat": 35.2100, "long": -101.7200, "label": "Amarillo (east)"},
    {"slug": "amarillo_west", "lat": 35.1900, "long": -101.9500, "label": "Amarillo (west)"},
]


def _parse_years_arg(raw: str, today: date) -> list[int]:
    s = (raw or "").strip()
    if not s:
        return [today.year - 1, today.year, today.year + 1]
    out: list[int] = []
    for part in s.split(","):
        p = part.strip()
        if p.isdigit() and len(p) == 4:
            y = int(p)
            if 1990 <= y <= 2100:
                out.append(y)
    return sorted(set(out)) if out else [today.year - 1, today.year, today.year + 1]


def _officeholders_not_in_package(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "officeholders" in s and ("not available" in s or "your package" in s)


def _prioritize_sparse_counties_first(preset: str, options: dict) -> bool:
    if bool(options.get("no_prioritize_missing")):
        return False
    if bool(options.get("prioritize_missing")):
        return True
    return preset == "panhandle_north"


class Command(BaseCommand):
    help = (
        "Sync Ballotpedia geographic data: ``election_dates/point``, optional Texas ``election_dates/list``, "
        "``elections_by_point`` at one coordinate per area, optional filtered ``elections_by_state`` (Local), "
        "and optional ``officeholders``. "
        "Use ``--preset panhandle`` for 26 Panhandle county centroids + expanded local filter on elections_by_state. "
        "Use ``--preset panhandle_north`` for High Plains counties north of Lubbock (centroid rules), sparse-first "
        "``elections_by_point``/officeholders ordering, and a small cap on /election_dates/point calls to save quota. "
        "Trial geographic-only keys: use ``--geographic-only`` (election_dates + elections_by_point only) and avoid 429s. "
        "See also https://developer.ballotpedia.org/geographic-apis/getting-started-with-geographic-apis"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--preset",
            choices=("default", "panhandle", "panhandle_north"),
            default="default",
            help=(
                "default: Amarillo/Potter/Randall multi-point set. "
                "panhandle: 26 county centroids from static GeoJSON + broader Panhandle substring filter on elections_by_state. "
                "panhandle_north: ~35 High Plains counties (north of Lubbock, west of 99°W) + sparse-first sync by default."
            ),
        )
        parser.add_argument(
            "--election-dates-max-points",
            type=int,
            default=None,
            help=(
                "Max county centroids for /election_dates/point (saves quota). "
                "Default: all points except panhandle_north (default 6 with anchor counties first)."
            ),
        )
        parser.add_argument(
            "--prioritize-missing-counties",
            action="store_true",
            dest="prioritize_missing",
            default=False,
            help="Order elections_by_point/officeholders by fewest stored geo-election payloads first (coverage gaps).",
        )
        parser.add_argument(
            "--no-prioritize-missing-counties",
            action="store_true",
            dest="no_prioritize_missing",
            default=False,
            help="Disable sparse-first ordering (panhandle_north enables it unless this flag is set).",
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=450,
            help="Stop after this many API requests (trial keys are often 500/day). Default 450; panhandle runs often use 480.",
        )
        parser.add_argument(
            "--max-election-dates",
            type=int,
            default=18,
            help="Cap distinct election dates after merging point + Texas calendar (default 18).",
        )
        parser.add_argument(
            "--election-dates",
            type=str,
            default="",
            help="Comma-separated YYYY-MM-DD list. If set, skips /election_dates/point and Texas calendar.",
        )
        parser.add_argument(
            "--no-tx-election-calendar",
            action="store_true",
            help="Do not call /election_dates/list for Texas (loses dates outside the point API window).",
        )
        parser.add_argument(
            "--tx-calendar-years",
            type=str,
            default="",
            help="Comma years for Texas calendar (default: prior, current, next calendar year).",
        )
        parser.add_argument(
            "--max-tx-calendar-pages",
            type=int,
            default=12,
            help="Max total /election_dates/list pages across all years (default 12).",
        )
        parser.add_argument(
            "--no-tx-local-by-state",
            action="store_true",
            help="Disable supplemental /elections_by_state (TX, office_level=Local) pass; default is enabled.",
        )
        parser.add_argument(
            "--tx-local-state-pages",
            type=int,
            default=2,
            help="Max pages per election date for /elections_by_state Local (default 2).",
        )
        parser.add_argument(
            "--skip-if-fetched-days",
            type=int,
            default=0,
            help="Skip elections_by_point if a raw payload was stored for that point+date within N days (0=disabled).",
        )
        parser.add_argument(
            "--collections",
            type=str,
            default="social,contact",
            help="Optional collections query param (empty to omit). Default social,contact.",
        )
        parser.add_argument(
            "--with-officeholders",
            action="store_true",
            help="Call /officeholders (requires your Ballotpedia package to include that endpoint).",
        )
        parser.add_argument(
            "--geographic-only",
            action="store_true",
            help=(
                "Skip /officeholders and /elections_by_state; only election date discovery + /elections_by_point. "
                "Use with geographic trial API keys (saves quota and avoids 400/429)."
            ),
        )
        parser.add_argument(
            "--sleep-between-requests",
            type=float,
            default=0.0,
            help="Seconds to sleep after each successful API call (e.g. 0.25) to reduce 429 rate limits.",
        )
        parser.add_argument(
            "--no-elections",
            action="store_true",
            help="Do not call /elections_by_point.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print planned requests only (no HTTP, no DB writes).",
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, "BALLOTPEDIA_API_KEY", "") or ""
        base_url = getattr(settings, "BALLOTPEDIA_API4_BASE_URL", "https://api4.ballotpedia.org/data")
        preset = (options.get("preset") or "default").strip().lower()

        max_req = max(1, int(options.get("max_requests") or 450))
        max_dates = max(1, int(options.get("max_election_dates") or 18))
        skip_days = max(0, int(options.get("skip_if_fetched_days") or 0))
        collections = (options.get("collections") or "").strip()
        dry = bool(options.get("dry_run"))
        no_tx_cal = bool(options.get("no_tx_election_calendar"))
        max_tx_cal_pages = max(0, int(options.get("max_tx_calendar_pages") or 0))
        include_tx_state = not bool(options.get("no_tx_local_by_state"))
        tx_state_pages = max(1, int(options.get("tx_local_state_pages") or 2))
        geo_only = bool(options.get("geographic_only"))
        if geo_only:
            include_tx_state = False
        with_officeholders = bool(options.get("with_officeholders")) and not geo_only
        sleep_s = max(0.0, float(options.get("sleep_between_requests") or 0.0))

        state_elections_filter = None
        points_all: list[dict[str, float | str]]
        if preset == "panhandle_north":
            state_elections_filter = district_matches_panhandle_north
            pn = load_panhandle_north_of_lubbock_county_points()
            if pn:
                points_all = pn
                self.stdout.write(
                    f"Preset panhandle_north: {len(points_all)} county centroid(s) "
                    "(High Plains: north of Lubbock, west of 99°W)."
                )
            else:
                ph_fb = load_panhandle_sync_points()
                points_all = ph_fb if ph_fb else list(DEFAULT_POINTS)
                self.stdout.write(
                    self.style.WARNING(
                        "panhandle_north: could not load north-of-Lubbock centroids; "
                        "falling back to 26-county panhandle or DEFAULT_POINTS."
                    )
                )
        elif preset == "panhandle":
            state_elections_filter = district_matches_texas_panhandle
            ph = load_panhandle_sync_points()
            if ph:
                points_all = ph
                self.stdout.write(f"Panhandle preset: {len(points_all)} county centroid(s) from GeoJSON.")
            else:
                points_all = list(DEFAULT_POINTS)
                self.stdout.write(
                    self.style.WARNING(
                        "Panhandle preset: could not load centroids (missing static/geo/tx-counties.geojson?); "
                        "using DEFAULT_POINTS."
                    )
                )
        else:
            points_all = list(DEFAULT_POINTS)

        sparse_first = _prioritize_sparse_counties_first(preset, options)
        ed_cap_opt = options.get("election_dates_max_points")
        if ed_cap_opt is None:
            ed_cap = 6 if preset == "panhandle_north" else len(points_all)
        else:
            ed_cap = max(1, int(ed_cap_opt))
        ed_cap = min(ed_cap, len(points_all))
        points_date = pick_date_discovery_points(points_all, ed_cap)
        points_sync = order_points_by_geo_election_record_count(points_all) if sparse_first else list(points_all)

        if dry:
            self.stdout.write(self.style.WARNING("Dry run: no API calls and no database writes."))
            self.stdout.write(
                f"preset={preset} geographic_only={geo_only} "
                f"election_dates_points={len(points_date)} sync_points={len(points_sync)} sparse_first={sparse_first}"
            )

        if not dry and not api_key:
            self.stdout.write(self.style.ERROR("BALLOTPEDIA_API_KEY is not set."))
            return

        run = None
        if not dry:
            run = SyncRun.objects.create(provider=Provider.BALLOTPEDIA, status=SyncStatus.RUNNING)

        used = 0
        errors = 0

        def budget() -> bool:
            return used < max_req

        def touch() -> None:
            nonlocal used
            used += 1
            if sleep_s > 0 and not dry:
                time.sleep(sleep_s)

        dates: list[str] = []
        raw_dates = (options.get("election_dates") or "").strip()
        today = timezone.now().date()

        if raw_dates:
            dates = sorted({d.strip() for d in raw_dates.split(",") if d.strip()})
            dates = dates[:max_dates]
        elif not options.get("no_elections"):
            if dry:
                for _p in points_date:
                    self.stdout.write("Would GET /election_dates/point …")
                    touch()
                self.stdout.write("Would GET /election_dates/list (TX) …")
                touch()
                dates = ["2026-11-04", "2026-03-04", "2025-05-03"][:max_dates]
            else:
                client = BallotpediaGeographicClient(api_key=api_key, base_url=base_url)
                merged: set[str] = set()
                for p in points_date:
                    if not budget():
                        break
                    try:
                        body = client.election_dates_point(lat=float(p["lat"]), long=float(p["long"]))
                    except BallotpediaGeographicError as exc:
                        errors += 1
                        self.stdout.write(self.style.ERROR(f"election_dates/point {p['label']}: {exc}"))
                        continue
                    touch()
                    data = _payload_data_as_dict(body)
                    for row in data.get("elections") or []:
                        if isinstance(row, dict):
                            d = str(row.get("date") or "").strip()
                            if d:
                                merged.add(d)

                if not no_tx_cal and max_tx_cal_pages > 0 and budget():
                    years = _parse_years_arg(str(options.get("tx_calendar_years") or ""), today)
                    pages_left = max_tx_cal_pages
                    for y in years:
                        page = 1
                        while pages_left > 0 and budget():
                            try:
                                body = client.election_dates_list(state="TX", year=y, page=page)
                            except BallotpediaGeographicError as exc:
                                errors += 1
                                self.stdout.write(self.style.ERROR(f"election_dates/list TX {y} p{page}: {exc}"))
                                break
                            touch()
                            pages_left -= 1
                            rows = _payload_data_as_dict(body).get("elections") or []
                            if not isinstance(rows, list) or not rows:
                                break
                            for row in rows:
                                if isinstance(row, dict):
                                    d = str(row.get("date") or "").strip()
                                    if d:
                                        merged.add(d)
                            if len(rows) < 25:
                                break
                            page += 1

                dates = sorted(merged)[:max_dates]

        if with_officeholders:
            if dry:
                for p in points_sync:
                    if not budget():
                        break
                    self.stdout.write(
                        f"Would GET /officeholders lat={p['lat']} long={p['long']} collections={collections or '(none)'}"
                    )
                    touch()
            elif run is not None:
                client = BallotpediaGeographicClient(api_key=api_key, base_url=base_url)
                officeholders_package_denied = False
                for p in points_sync:
                    if not budget() or officeholders_package_denied:
                        break
                    slug = str(p["slug"])
                    try:
                        body = client.officeholders(
                            lat=float(p["lat"]),
                            long=float(p["long"]),
                            collections=collections,
                        )
                    except BallotpediaGeographicError as exc:
                        errors += 1
                        if _officeholders_not_in_package(exc):
                            officeholders_package_denied = True
                            self.stdout.write(
                                self.style.WARNING(
                                    "Stopping /officeholders: endpoint not included in your Ballotpedia package "
                                    "(common on geographic trial keys). Remaining county skips not counted as separate errors."
                                )
                            )
                        else:
                            self.stdout.write(self.style.ERROR(f"officeholders {p['label']}: {exc}"))
                        continue
                    touch()
                    ext = f"ballotpedia:geo_officeholders:{slug}"
                    record_ballotpedia_raw_payload(sync_run=run, external_id=ext, api_payload=body)
                    try:
                        normalize_ballotpedia_officeholders(sync_run=run, anchor_slug=slug, api_payload=body)
                    except Exception as exc:
                        errors += 1
                        self.stdout.write(self.style.ERROR(f"normalize officeholders {slug}: {exc}"))

        if not options.get("no_elections") and dates:
            if dry:
                for p in points_sync:
                    for d in dates[:max_dates]:
                        if not budget():
                            break
                        self.stdout.write(f"Would GET /elections_by_point … {d}")
                        touch()
                if include_tx_state:
                    for d in dates[:max_dates]:
                        for pg in range(1, tx_state_pages + 1):
                            if not budget():
                                break
                            self.stdout.write(f"Would GET /elections_by_state TX {d} page={pg}")
                            touch()
            elif run is not None:
                client = BallotpediaGeographicClient(api_key=api_key, base_url=base_url)
                cutoff = timezone.now() - timedelta(days=skip_days) if skip_days else None
                for p in points_sync:
                    slug = str(p["slug"])
                    if sparse_first and skip_days == 0 and dates:
                        have_all_dates = True
                        for d0 in dates:
                            ext_chk = f"ballotpedia:geo_elections:{slug}:{d0}"
                            if not SourceRecord.objects.filter(
                                provider=Provider.BALLOTPEDIA, external_id=ext_chk
                            ).exists():
                                have_all_dates = False
                                break
                        if have_all_dates:
                            self.stdout.write(f"Skip county (all current election dates on file): {p['label']}")
                            continue
                    for d in dates:
                        if not budget():
                            self.stdout.write(self.style.WARNING("Stopped: max-requests reached before elections done."))
                            break
                        ext_raw = f"ballotpedia:geo_elections:{slug}:{d}"
                        if cutoff is not None:
                            recent = SourceRecord.objects.filter(
                                provider=Provider.BALLOTPEDIA,
                                external_id=ext_raw,
                                fetched_at__gte=cutoff,
                            ).exists()
                            if recent:
                                self.stdout.write(f"Skip (recent): {ext_raw}")
                                continue
                        try:
                            body = client.elections_by_point(
                                lat=float(p["lat"]),
                                long=float(p["long"]),
                                election_date=d,
                                collections=collections,
                            )
                        except BallotpediaGeographicError as exc:
                            errors += 1
                            self.stdout.write(self.style.ERROR(f"elections_by_point {slug} {d}: {exc}"))
                            continue
                        touch()
                        record_ballotpedia_raw_payload(sync_run=run, external_id=ext_raw, api_payload=body)
                        try:
                            normalize_ballotpedia_elections_by_point(sync_run=run, api_payload=body)
                        except Exception as exc:
                            errors += 1
                            self.stdout.write(self.style.ERROR(f"normalize elections {slug} {d}: {exc}"))

                if include_tx_state and budget():
                    state_sync_stopped = False
                    for d in dates:
                        if state_sync_stopped:
                            break
                        for page in range(1, tx_state_pages + 1):
                            if not budget() or state_sync_stopped:
                                break
                            ext_st = f"ballotpedia:geo_tx_local:{d}:p{page}"
                            try:
                                body = client.elections_by_state(
                                    state="TX",
                                    election_date=d,
                                    page=page,
                                    office_level="Local",
                                    collections=collections,
                                )
                            except BallotpediaGeographicError as exc:
                                err_s = str(exc)
                                if "429" in err_s or "Limit Exceeded" in err_s:
                                    self.stdout.write(
                                        self.style.WARNING(
                                            "Stopping /elections_by_state: daily rate limit (429). "
                                            "Use --geographic-only or --no-tx-local-by-state for trial keys; retry tomorrow."
                                        )
                                    )
                                    state_sync_stopped = True
                                else:
                                    errors += 1
                                    self.stdout.write(self.style.ERROR(f"elections_by_state TX {d} p{page}: {exc}"))
                                    break
                                break
                            touch()
                            data_st = _payload_data_as_dict(body)
                            raw_d = body.get("data") if isinstance(body, dict) else None
                            if isinstance(raw_d, str) and raw_d.strip() and not data_st:
                                errors += 1
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"elections_by_state TX {d} p{page}: non-JSON data field ({raw_d[:200]!r}), skipping."
                                    )
                                )
                                break
                            districts = data_st.get("districts") or []
                            if not isinstance(districts, list) or not districts:
                                break
                            record_ballotpedia_raw_payload(sync_run=run, external_id=ext_st, api_payload=body)
                            try:
                                normalize_ballotpedia_elections_by_state_filtered(
                                    sync_run=run,
                                    api_payload=body,
                                    district_filter=state_elections_filter,
                                )
                            except Exception as exc:
                                errors += 1
                                self.stdout.write(
                                    self.style.ERROR(f"normalize elections_by_state TX {d} p{page}: {exc}")
                                )

        if run is not None:
            run.status = SyncStatus.PARTIAL if errors else SyncStatus.SUCCESS
            run.stats = {
                "api_requests": used,
                "errors": errors,
                "election_dates_count": len(dates),
                "election_dates_sample": dates[:12],
                "preset": preset,
                "sync_points": len(points_all),
                "election_dates_centroids": len(points_date),
                "sparse_first": sparse_first,
                "geographic_only": geo_only,
                "sleep_between_requests_s": sleep_s,
            }
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "stats", "finished_at", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Ballotpedia geographic: api_requests={used} max={max_req} errors={errors} "
                f"election_dates={len(dates) if dates else 0} sync_run={run.public_id.hex if run else 'n/a'}"
            )
        )
