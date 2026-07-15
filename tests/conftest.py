import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path):
    os.environ.pop("DATABASE_URL", None)
    os.environ["RELIABILITY_LAB_DB"] = str(tmp_path / "reliability_lab.db")
    yield
    os.environ.pop("RELIABILITY_LAB_DB", None)
