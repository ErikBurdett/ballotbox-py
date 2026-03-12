from __future__ import annotations

from .ballotready_civicengine import BallotReadyCivicEngineAdapter
from .ballotpedia import BallotpediaAdapter
from .openfec import OpenFecAdapter
from .openstates import OpenStatesAdapter
from .youtube import YouTubeAdapter


def get_adapters():
    return [
        BallotReadyCivicEngineAdapter(),
        BallotpediaAdapter(),
        OpenStatesAdapter(),
        OpenFecAdapter(),
        YouTubeAdapter(),
    ]

