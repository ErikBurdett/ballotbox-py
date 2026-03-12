from apps.ingestion.models import Provider

from .fixture_adapter import FixtureAdapter


class YouTubeAdapter(FixtureAdapter):
    def __init__(self):
        super().__init__(Provider.YOUTUBE, "youtube_demo.json")

