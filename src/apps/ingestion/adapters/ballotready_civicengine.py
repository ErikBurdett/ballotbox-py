from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class BallotReadyCivicEngineAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.BALLOTREADY_CIVICENGINE, "ballotready_civicengine_demo.json")

