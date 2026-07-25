"""Shared pytest fixtures.

The app is built with TESTING=True and RUN_WORKER=0 so no background worker spawns. These
tests deliberately avoid DB queries and network calls, so no Postgres/embedding/LLM services
are required — only the base dependencies.
"""

import os

os.environ.setdefault("RUN_WORKER", "0")

import pytest

from app import create_app
from app.config import Config


@pytest.fixture
def app():
    application = create_app(Config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()
