from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BallotpediaGeographicError(RuntimeError):
    pass


class BallotpediaGeographicClient:
    """
    Ballotpedia Data Client geographic API (api4).

    Docs: https://developer.ballotpedia.org/geographic-apis/getting-started-with-geographic-apis

    All requests are GET with headers:
      x-api-key, Content-Type: application/json

    Use ``collections="social,contact"`` on endpoints that support it to maximize
    payload per HTTP request (important for low daily quotas).
    """

    def __init__(self, *, api_key: str, base_url: str = "https://api4.ballotpedia.org/data", timeout_s: int = 60):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise BallotpediaGeographicError("BALLOTPEDIA_API_KEY is not set.")
        rel = path if path.startswith("/") else f"/{path}"
        q = {k: v for k, v in params.items() if v not in (None, "")}
        url = f"{self.base_url}{rel}"
        if q:
            url = f"{url}?{urlencode(q, doseq=True)}"
        req = Request(
            url,
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
                "user-agent": "the-ballot-box/0.1 (+https://example.invalid)",
            },
            method="GET",
        )
        last_exc: Exception | None = None
        for attempt in range(5):
            status: int | None = None
            body = ""
            retry_after_s = 0.0
            try:
                with urlopen(req, timeout=self.timeout_s) as resp:
                    try:
                        status = int(getattr(resp, "status", None) or resp.getcode() or 0) or None
                    except Exception:
                        status = None
                    ra = str(resp.headers.get("retry-after") or "").strip()
                    if ra.isdigit():
                        retry_after_s = float(int(ra))
                    body = resp.read().decode("utf-8", "ignore")
            except HTTPError as exc:
                last_exc = exc
                status = int(getattr(exc, "code", None) or 0) or None
                try:
                    body = (exc.read() or b"").decode("utf-8", "ignore")
                except Exception:
                    body = ""
                hdrs = getattr(exc, "headers", None) or {}
                ra = str(hdrs.get("retry-after") or "").strip()
                if ra.isdigit():
                    retry_after_s = float(int(ra))
            except (TimeoutError, URLError) as exc:
                last_exc = exc
                status = None
            except Exception as exc:
                last_exc = exc
                status = None

            if status in {429, 500, 502, 503, 504}:
                if attempt < 4:
                    time.sleep(max(retry_after_s, 0.5 * (attempt + 1)))
                    continue
            if status is None and last_exc is not None and attempt < 4:
                time.sleep(0.5 * (attempt + 1))
                continue
            if status and status >= 400:
                snippet = (body or "").strip().replace("\n", " ")[:400]
                raise BallotpediaGeographicError(f"Ballotpedia geographic HTTP {status} for {rel}. body={snippet}")
            break

        try:
            data = json.loads(body)
        except Exception as exc:
            snippet = (body or "").strip().replace("\n", " ")[:240]
            raise BallotpediaGeographicError(f"Ballotpedia geographic invalid JSON for {rel}: {snippet}") from exc
        if not isinstance(data, dict):
            raise BallotpediaGeographicError(f"Ballotpedia geographic unexpected root type for {rel}")
        if not data.get("success"):
            msg = str(data.get("message") or data.get("error") or "success=false")
            raise BallotpediaGeographicError(f"Ballotpedia geographic API error for {rel}: {msg}")
        return data

    def election_dates_point(self, *, lat: float, long: float) -> dict[str, Any]:
        """https://developer.ballotpedia.org/geographic-apis/election_dates (by point)"""
        return self._get("/election_dates/point", {"lat": lat, "long": long})

    def election_dates_list(
        self,
        *,
        state: str,
        year: int,
        page: int = 1,
        type: str = "",
    ) -> dict[str, Any]:
        """https://developer.ballotpedia.org/geographic-apis/election_dates (list; paginated, 25/page)."""
        params: dict[str, Any] = {"state": (state or "").strip().upper(), "year": int(year), "page": max(1, int(page))}
        if type:
            params["type"] = type
        return self._get("/election_dates/list", params)

    def elections_by_state(
        self,
        *,
        state: str,
        election_date: str,
        page: int = 1,
        office_level: str = "",
        district_type: str = "",
        collections: str = "social,contact",
    ) -> dict[str, Any]:
        """
        https://developer.ballotpedia.org/geographic-apis/elections_by_state

        Optional ``office_level`` (Federal,State,Local) and ``district_type`` reduce payload size.
        """
        params: dict[str, Any] = {
            "state": (state or "").strip().upper(),
            "election_date": election_date,
            "page": max(1, int(page)),
        }
        if office_level:
            params["office_level"] = office_level
        if district_type:
            params["district_type"] = district_type
        if collections:
            params["collections"] = collections
        return self._get("/elections_by_state", params)

    def elections_by_point(
        self,
        *,
        lat: float,
        long: float,
        election_date: str,
        collections: str = "social,contact",
    ) -> dict[str, Any]:
        """
        https://developer.ballotpedia.org/geographic-apis/elections_by_point

        ``collections`` should include ``social`` and ``contact`` when your package
        allows it — one request returns the widest candidate/person enrichment.
        """
        params: dict[str, Any] = {"lat": lat, "long": long, "election_date": election_date}
        if collections:
            params["collections"] = collections
        return self._get("/elections_by_point", params)

    def officeholders(self, *, lat: float, long: float, collections: str = "social,contact") -> dict[str, Any]:
        """https://developer.ballotpedia.org/geographic-apis/officeholders"""
        params: dict[str, Any] = {"lat": lat, "long": long}
        if collections:
            params["collections"] = collections
        return self._get("/officeholders", params)
