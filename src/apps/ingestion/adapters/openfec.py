from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class OpenFecAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.OPENFEC, "openfec_demo.json")

