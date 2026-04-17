from django.conf import settings

from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class BallotpediaAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.BALLOTPEDIA, "ballotpedia_demo.json")

    def fetch(self) -> list[dict]:
        # When a real Ballotpedia API key is configured, election/candidate data comes from
        # `sync_ballotpedia_geographic` (Celery / management command), not demo fixtures.
        if (getattr(settings, "BALLOTPEDIA_API_KEY", "") or "").strip():
            return []
        return super().fetch()

