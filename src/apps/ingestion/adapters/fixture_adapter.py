from __future__ import annotations

import json
from pathlib import Path

from apps.ingestion.models import Provider, SyncRun

from .base import AdapterStats
from ..normalizers.demo import normalize_demo_record


class FixtureAdapter:
    provider: Provider
    fixture_filename: str

    def __init__(self, provider: Provider, fixture_filename: str):
        self.provider = provider
        self.fixture_filename = fixture_filename

    def fetch(self) -> list[dict]:
        fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
        path = fixtures_dir / self.fixture_filename
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Fixture must be a list: {path}")
        return data

    def normalize(self, payload: dict, sync_run: SyncRun) -> AdapterStats:
        normalize_demo_record(provider=self.provider, payload=payload, sync_run=sync_run)
        return AdapterStats(fetched=1, created=0, updated=0, errors=0)

