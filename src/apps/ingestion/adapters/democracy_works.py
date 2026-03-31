from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings

from apps.ingestion.http.democracy_works import DemocracyWorksClient
from apps.ingestion.models import Provider, SyncRun

from .base import AdapterStats
from ..normalizers.democracy_works import normalize_dw_election

# Representative Amarillo-area addresses (Potter + Randall county ballots).
# DW returns voter-specific ballots; multiple ZIPs reduce gaps at county lines.
DEFAULT_AMARILLO_METRO_ADDRESSES: list[dict[str, str]] = [
    {"street": "601 S Buchanan St", "city": "Amarillo", "state_code": "TX", "zip": "79101", "zip4": ""},
    {"street": "3301 SE 10th Ave", "city": "Amarillo", "state_code": "TX", "zip": "79104", "zip4": ""},
    {"street": "3700 S Soncy Rd", "city": "Amarillo", "state_code": "TX", "zip": "79119", "zip4": ""},
    {"street": "7122 Hillside Rd", "city": "Amarillo", "state_code": "TX", "zip": "79118", "zip4": ""},
    {"street": "4515 S Georgia St", "city": "Amarillo", "state_code": "TX", "zip": "79110", "zip4": ""},
]


def _dw_election_dedupe_key(election_payload: dict[str, Any]) -> str:
    eid = str(election_payload.get("id") or "").strip()
    if eid:
        return f"id:{eid}"
    ocd = str(election_payload.get("ocdId") or "")
    d = str(election_payload.get("date") or "")
    return f"ocd:{ocd}:{d}"


class DemocracyWorksAdapter:
    provider = Provider.DEMOCRACY_WORKS

    def _parse_year(self, value: str) -> int | None:
        v = (value or "").strip()
        if not v:
            return None
        if v.isdigit() and len(v) == 4:
            y = int(v)
            if 1900 <= y <= 2100:
                return y
        return None

    def _parse_date(self, value: str) -> date | None:
        v = (value or "").strip()
        if not v:
            return None
        try:
            y, m, d = [int(x) for x in v.split("-")]
            return date(y, m, d)
        except Exception:
            return None

    def _resolve_sync_dates(self, cfg: dict) -> tuple[date, date | None]:
        election_year = self._parse_year(str(cfg.get("election_year") or ""))
        start_date = self._parse_date(str(cfg.get("start_date") or ""))
        end_date = self._parse_date(str(cfg.get("end_date") or ""))

        if election_year is None and start_date is None and end_date is None:
            election_year = date.today().year

        if election_year is not None and start_date is None and end_date is None:
            start_date = date(election_year, 1, 1)
            end_date = date(election_year, 12, 31)

        if start_date is None:
            start_date = date.today()

        return start_date, end_date

    def _iter_amarillo_metro(self, client: DemocracyWorksClient, cfg: dict):
        start_date, end_date = self._resolve_sync_dates(cfg)
        raw = cfg.get("amarillo_addresses")
        addresses: list[dict[str, str]] = []
        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, dict):
                    continue
                if not (
                    str(row.get("street") or "").strip()
                    and str(row.get("city") or "").strip()
                    and str(row.get("state_code") or "").strip()
                    and str(row.get("zip") or "").strip()
                ):
                    continue
                addresses.append(
                    {
                        "street": str(row.get("street") or "").strip(),
                        "city": str(row.get("city") or "").strip(),
                        "state_code": str(row.get("state_code") or "").strip().upper(),
                        "zip": str(row.get("zip") or "").strip(),
                        "zip4": str(row.get("zip4") or "").strip(),
                    }
                )
        if not addresses:
            addresses = list(DEFAULT_AMARILLO_METRO_ADDRESSES)

        seen: set[str] = set()
        for addr in addresses:
            for election in client.iter_elections_for_address(
                address=addr,
                start_date=start_date,
                end_date=end_date,
                include_ballot_data=True,
                page_size=50,
            ):
                key = _dw_election_dedupe_key(election)
                if key in seen:
                    continue
                seen.add(key)
                yield election

    def fetch_iter(self):
        """
        Stream elections from DW (preferred for large state backfills).
        """
        api_key = getattr(settings, "DEMOCRACY_WORKS_API_KEY", "")
        base_url = getattr(settings, "DEMOCRACY_WORKS_API_BASE_URL", "https://api.democracy.works/v2")
        cfg = getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}

        # DW is quota-limited; targeted syncs (like Amarillo metro) should be willing
        # to wait out rate limits rather than failing immediately.
        max_attempts = 5
        max_backoff_s = 60.0
        if cfg.get("amarillo_metro"):
            max_attempts = 12
            max_backoff_s = 300.0
        client = DemocracyWorksClient(
            api_key=api_key,
            base_url=base_url,
            timeout_s=30,
            max_attempts=max_attempts,
            max_backoff_s=max_backoff_s,
        )

        if cfg.get("amarillo_metro"):
            return self._iter_amarillo_metro(client, cfg)

        address = cfg.get("address") or {}
        if not isinstance(address, dict):
            address = {}
        has_address = bool(address.get("street") and address.get("city") and address.get("state_code") and address.get("zip"))
        if has_address:
            start_date, end_date = self._resolve_sync_dates(cfg)
            return client.iter_elections_for_address(
                address=address,
                start_date=start_date,
                end_date=end_date,
                include_ballot_data=True,
                page_size=50,
            )

        state_code = str(cfg.get("state_code") or "").strip().upper()
        if not state_code:
            return iter([])

        start_date, end_date = self._resolve_sync_dates(cfg)

        return client.iter_elections_for_state(
            state_code=state_code,
            start_date=start_date,
            end_date=end_date,
            include_ballot_data=True,
            page_size=50,
        )

    def fetch(self) -> list[dict]:
        return list(self.fetch_iter())

    def normalize(self, payload: dict, sync_run: SyncRun) -> AdapterStats:
        normalize_dw_election(sync_run=sync_run, election_payload=payload)
        return AdapterStats(fetched=1, created=0, updated=0, errors=0)

