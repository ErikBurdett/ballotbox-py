from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import time


class DemocracyWorksError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pagination:
    total_record_count: int
    current_page: int
    page_size: int


class DemocracyWorksClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.democracy.works/v2",
        timeout_s: int = 30,
        max_attempts: int = 5,
        max_backoff_s: float = 60.0,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_attempts = max(1, int(max_attempts or 1))
        self.max_backoff_s = float(max(0.0, float(max_backoff_s or 0.0)))

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
        last_exc: Exception | None = None
        for attempt in range(self.max_attempts):
            status: int | None = None
            body = ""
            retry_after_s: float = 0.0
            try:
                with urlopen(req, timeout=self.timeout_s) as resp:
                    try:
                        status = int(getattr(resp, "status", None) or resp.getcode() or 0) or None
                    except Exception:
                        status = None
                    retry_after = str(resp.headers.get("retry-after") or "").strip()
                    if retry_after.isdigit():
                        retry_after_s = float(int(retry_after))
                    body = resp.read().decode("utf-8", "ignore")
            except HTTPError as exc:
                last_exc = exc
                status = int(getattr(exc, "code", None) or 0) or None
                try:
                    body = (exc.read() or b"").decode("utf-8", "ignore")
                except Exception:
                    body = ""
                retry_after = str(getattr(exc, "headers", {}).get("retry-after") if getattr(exc, "headers", None) else "").strip()
                if retry_after.isdigit():
                    retry_after_s = float(int(retry_after))
            except (TimeoutError, URLError) as exc:
                last_exc = exc
                status = None
            except Exception as exc:
                last_exc = exc
                status = None

            # Retry policy (gentle backoff for rate limiting / transient upstream errors).
            if status in {429, 500, 502, 503, 504}:
                if attempt < (self.max_attempts - 1):
                    # DW does not always return Retry-After headers. When 429 happens, back off harder.
                    base = 0.5 * (attempt + 1)
                    if status == 429:
                        base = 30.0 * (attempt + 1)
                    sleep_s = max(retry_after_s, min(self.max_backoff_s or base, base))
                    time.sleep(sleep_s)
                    continue
            if status is None and last_exc is not None:
                if attempt < (self.max_attempts - 1):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise DemocracyWorksError(f"DW request failed: {path}") from last_exc
            if status and status >= 400:
                # Provide context for debugging / telemetry.
                snippet = (body or "").strip().replace("\n", " ")[:240]
                raise DemocracyWorksError(f"DW HTTP {status} for {path}. body={snippet}")
            # Success path: body should be JSON.
            break

        try:
            data = json.loads(body)
        except Exception as exc:
            snippet = (body or "").strip().replace("\n", " ")[:240]
            raise DemocracyWorksError(f"DW returned invalid JSON. body={snippet}") from exc
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

    def get_candidate(self, *, candidate_id: str) -> dict[str, Any]:
        """
        Fetch a single candidate by id.

        The DW API has historically returned either:
        - {"data": {"candidates": {...}}}
        - {...candidate...} (top-level object)
        """
        cid = (candidate_id or "").strip()
        if not cid:
            raise DemocracyWorksError("candidate_id is required.")
        payload = self._request(f"/candidates/{cid}")
        # Wrapped shape
        try:
            wrapped = (payload.get("data") or {}).get("candidates")  # type: ignore[union-attr]
        except Exception:
            wrapped = None
        if isinstance(wrapped, dict) and str(wrapped.get("id") or "").strip():
            return wrapped
        # Top-level shape
        if isinstance(payload, dict) and str(payload.get("id") or "").strip():
            return payload
        return {}

    def list_endorsements_bulk_by_matching_entity(
        self,
        *,
        candidate_id: str = "",
        ballot_measure_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], Pagination | None]:
        """
        Fetch endorsements by candidateId OR ballotMeasureId.
        """
        cid = (candidate_id or "").strip()
        bid = (ballot_measure_id or "").strip()
        if bool(cid) == bool(bid):
            raise DemocracyWorksError("Provide exactly one of candidate_id or ballot_measure_id.")
        params: dict[str, Any] = {"page": max(1, int(page or 1)), "pageSize": min(max(1, int(page_size or 50)), 100)}
        if cid:
            params["candidateId"] = cid
        if bid:
            params["ballotMeasureId"] = bid

        payload = self._request("/endorsements/bulk/byMatchingEntity", params=params)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            data = []
        pag = payload.get("pagination") if isinstance(payload, dict) else None
        pagination = None
        if isinstance(pag, dict):
            try:
                pagination = Pagination(
                    total_record_count=int(pag.get("totalRecordCount") or pag.get("total_record_count") or 0),
                    current_page=int(pag.get("currentPage") or pag.get("current_page") or 1),
                    page_size=int(pag.get("pageSize") or pag.get("page_size") or params["pageSize"]),
                )
            except Exception:
                pagination = None
        return data, pagination

    def iter_endorsements_by_candidate(self, *, candidate_id: str, page_size: int = 50, max_pages: int = 10):
        """
        Stream endorsements for a candidate across pages.
        """
        cid = (candidate_id or "").strip()
        if not cid:
            return iter([])

        def _gen():
            page = 1
            while True:
                batch, pagination = self.list_endorsements_bulk_by_matching_entity(
                    candidate_id=cid, page=page, page_size=page_size
                )
                for row in batch:
                    yield row
                if not pagination:
                    break
                if pagination.current_page * pagination.page_size >= pagination.total_record_count:
                    break
                page += 1
                if max_pages and page > max_pages:
                    break

        return _gen()

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

    def _address_election_params(
        self,
        *,
        address: dict[str, str],
        start_date: date,
        end_date: date | None,
        include_ballot_data: bool,
        page_size: int,
        page: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "addressStreet": address.get("street") or "",
            "addressCity": address.get("city") or "",
            "addressStateCode": address.get("state_code") or "",
            "addressZip": address.get("zip") or "",
            "addressZip4": address.get("zip4") or "",
            "startDate": start_date.isoformat(),
            "includeBallotData": "true" if include_ballot_data else "false",
            "pageSize": page_size,
            "page": page,
        }
        if end_date is not None:
            params["endDate"] = end_date.isoformat()
        return params

    def list_elections_for_address(
        self,
        *,
        address: dict[str, str],
        start_date: date,
        end_date: date | None = None,
        include_ballot_data: bool = True,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        elections: list[dict[str, Any]] = []
        page = 1
        while True:
            batch, pagination = self.list_elections(
                params=self._address_election_params(
                    address=address,
                    start_date=start_date,
                    end_date=end_date,
                    include_ballot_data=include_ballot_data,
                    page_size=page_size,
                    page=page,
                )
            )
            elections.extend(batch)
            if not pagination:
                break
            if pagination.current_page * pagination.page_size >= pagination.total_record_count:
                break
            page += 1
        return elections

    def iter_elections_for_address(
        self,
        *,
        address: dict[str, str],
        start_date: date,
        end_date: date | None = None,
        include_ballot_data: bool = True,
        page_size: int = 50,
    ):
        _unused, gen = self.iter_elections(
            params=self._address_election_params(
                address=address,
                start_date=start_date,
                end_date=end_date,
                include_ballot_data=include_ballot_data,
                page_size=page_size,
                page=1,
            )
        )
        return gen

    def list_upcoming_elections_for_address(self, *, address: dict[str, str], start_date: date) -> list[dict[str, Any]]:
        return self.list_elections_for_address(address=address, start_date=start_date, end_date=None, include_ballot_data=True)

