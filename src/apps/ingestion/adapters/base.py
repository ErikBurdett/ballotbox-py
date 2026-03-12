from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.ingestion.models import Provider, SyncRun


@dataclass(frozen=True)
class AdapterStats:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    errors: int = 0


class ProviderAdapter(Protocol):
    provider: Provider

    def fetch(self) -> list[dict]:
        """Return a list of raw provider payloads (dicts)."""

    def normalize(self, payload: dict, sync_run: SyncRun) -> AdapterStats:
        """Write normalized models and SourceRecords for a payload."""

