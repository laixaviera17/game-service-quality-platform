import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path):
    os.environ["GAME_QA_DB"] = str(tmp_path / "test.db")
    from app.database import initialize_database

    initialize_database()
    yield
    os.environ.pop("GAME_QA_DB", None)
