from __future__ import annotations

from datetime import date
from datetime import timedelta

from django.conf import settings

from apps.ingestion.http.democracy_works import DemocracyWorksClient
from apps.ingestion.models import Provider, SyncRun

from .base import AdapterStats
from ..normalizers.democracy_works import normalize_dw_election


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

    def fetch_iter(self):
        """
        Stream elections from DW (preferred for large state backfills).
        """
        api_key = getattr(settings, "DEMOCRACY_WORKS_API_KEY", "")
        base_url = getattr(settings, "DEMOCRACY_WORKS_API_BASE_URL", "https://api.democracy.works/v2")
        cfg = getattr(settings, "DEMOCRACY_WORKS_SYNC", {}) or {}

        client = DemocracyWorksClient(api_key=api_key, base_url=base_url, timeout_s=30)

        address = (cfg.get("address") or {}) if isinstance(cfg, dict) else {}
        has_address = bool(address.get("street") and address.get("city") and address.get("state_code") and address.get("zip"))
        if has_address:
            # Address mode is inherently "voter-specific"; keep it focused on upcoming elections.
            return iter(client.list_upcoming_elections_for_address(address=address, start_date=date.today()))

        state_code = str(cfg.get("state_code") or "").strip().upper() if isinstance(cfg, dict) else ""
        if not state_code:
            return iter([])

        election_year = self._parse_year(str(cfg.get("election_year") or "")) if isinstance(cfg, dict) else None
        start_date = self._parse_date(str(cfg.get("start_date") or "")) if isinstance(cfg, dict) else None
        end_date = self._parse_date(str(cfg.get("end_date") or "")) if isinstance(cfg, dict) else None

        # Default behavior for this project: focus on the current election year (e.g. 2026).
        # You can override by setting explicit start/end dates.
        if election_year is None and start_date is None and end_date is None:
            election_year = date.today().year

        if election_year is not None and start_date is None and end_date is None:
            start_date = date(election_year, 1, 1)
            end_date = date(election_year, 12, 31)

        if start_date is None:
            start_date = date.today()

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

