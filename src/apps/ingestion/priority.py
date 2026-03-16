from __future__ import annotations

from apps.ingestion.models import Provider


# Lower number = higher priority for conflicting fields
PROVIDER_PRIORITY: dict[str, int] = {
    Provider.BALLOTPEDIA: 10,
    Provider.DEMOCRACY_WORKS: 15,
    Provider.BALLOTREADY_CIVICENGINE: 20,
    Provider.OPENSTATES: 30,
    Provider.OPENFEC: 40,
    Provider.YOUTUBE: 90,
}


def priority(provider: str) -> int:
    return PROVIDER_PRIORITY.get(provider, 1000)

