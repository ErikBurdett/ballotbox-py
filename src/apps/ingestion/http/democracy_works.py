from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class DemocracyWorksError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pagination:
    total_record_count: int
    current_page: int
    page_size: int


class DemocracyWorksClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.democracy.works/v2", timeout_s: int = 30):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise DemocracyWorksError("DEMOCRACY_WORKS_API_KEY is not set.")
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v not in (None, '')}, doseq=True)}"

        req = Request(
            url,
            headers={
                # Docs specify lowercase header key.
                "x-api-key": self.api_key,
                "accept": "application/json",
                "user-agent": "the-ballot-box/0.1 (+https://example.invalid)",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8", "ignore")
        except Exception as exc:
            raise DemocracyWorksError(f"DW request failed: {path}") from exc

        try:
            data = json.loads(body)
        except Exception as exc:
            raise DemocracyWorksError("DW returned invalid JSON.") from exc
        return data

    def list_elections(self, *, params: dict[str, Any]) -> tuple[list[dict[str, Any]], Pagination | None]:
        payload = self._request("/elections", params=params)
        elections = (payload.get("data") or {}).get("elections") or []
        pag = (payload.get("pagination") or (payload.get("data") or {}).get("pagination")) or {}
        pagination = None
        if pag and isinstance(pag, dict):
            try:
                pagination = Pagination(
                    total_record_count=int(pag.get("totalRecordCount") or pag.get("total_record_count") or 0),
                    current_page=int(pag.get("currentPage") or pag.get("current_page") or 1),
                    page_size=int(pag.get("pageSize") or pag.get("page_size") or 10),
                )
            except Exception:
                pagination = None
        if not isinstance(elections, list):
            elections = []
        return elections, pagination

    def iter_elections(self, *, params: dict[str, Any]) -> tuple[int, Any]:
        """
        Stream elections page-by-page to avoid loading everything into memory.

        Returns (total_seen, generator).
        """

        def _gen():
            page = int(params.get("page") or 1)
            while True:
                batch, pagination = self.list_elections(params={**params, "page": page})
                for e in batch:
                    yield e
                if not pagination:
                    break
                if pagination.current_page * pagination.page_size >= pagination.total_record_count:
                    break
                page += 1

        # We don't know total upfront without an initial call. The caller can count.
        return 0, _gen()

    def list_elections_for_state(
        self,
        *,
        state_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        include_ballot_data: bool = True,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        elections: list[dict[str, Any]] = []
        _unused, gen = self.iter_elections(
            params={
                "stateCode": state_code,
                "startDate": start_date.isoformat() if start_date else "",
                "endDate": end_date.isoformat() if end_date else "",
                "includeBallotData": "true" if include_ballot_data else "false",
                "pageSize": page_size,
                "page": 1,
            }
        )
        elections.extend(list(gen))
        return elections

    def iter_elections_for_state(
        self,
        *,
        state_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        include_ballot_data: bool = True,
        page_size: int = 50,
    ):
        _unused, gen = self.iter_elections(
            params={
                "stateCode": state_code,
                "startDate": start_date.isoformat() if start_date else "",
                "endDate": end_date.isoformat() if end_date else "",
                "includeBallotData": "true" if include_ballot_data else "false",
                "pageSize": page_size,
                "page": 1,
            }
        )
        return gen

    def list_upcoming_elections_for_state(self, *, state_code: str, start_date: date) -> list[dict[str, Any]]:
        return self.list_elections_for_state(state_code=state_code, start_date=start_date, include_ballot_data=True)

    def list_upcoming_elections_for_address(self, *, address: dict[str, str], start_date: date) -> list[dict[str, Any]]:
        elections: list[dict[str, Any]] = []
        page = 1
        while True:
            batch, pagination = self.list_elections(
                params={
                    "addressStreet": address.get("street") or "",
                    "addressCity": address.get("city") or "",
                    "addressStateCode": address.get("state_code") or "",
                    "addressZip": address.get("zip") or "",
                    "addressZip4": address.get("zip4") or "",
                    "startDate": start_date.isoformat(),
                    "includeBallotData": "true",
                    "pageSize": 50,
                    "page": page,
                }
            )
            elections.extend(batch)
            if not pagination:
                break
            if pagination.current_page * pagination.page_size >= pagination.total_record_count:
                break
            page += 1
        return elections

