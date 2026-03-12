import os

import pytest


@pytest.fixture(autouse=True)
def _django_test_env(monkeypatch):
    # Tests are intended to run under docker-compose where DATABASE_URL is set.
    # This keeps settings import stable if a developer runs pytest manually.
    monkeypatch.setenv("DJANGO_DEBUG", os.getenv("DJANGO_DEBUG", "1"))
