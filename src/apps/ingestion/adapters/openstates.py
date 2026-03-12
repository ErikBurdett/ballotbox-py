from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class OpenStatesAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.OPENSTATES, "openstates_demo.json")

