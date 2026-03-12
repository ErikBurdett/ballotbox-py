from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class BallotpediaAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.BALLOTPEDIA, "ballotpedia_demo.json")

