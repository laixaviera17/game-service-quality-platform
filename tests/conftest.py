import os
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: MySQL + Redis + Celery integration tests")


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, request):
    if "integration" in request.keywords:
        yield
        return
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("EXECUTION_MODE", None)
    os.environ["RELIABILITY_LAB_DB"] = str(tmp_path / "reliability_lab.db")
    yield
    os.environ.pop("RELIABILITY_LAB_DB", None)
