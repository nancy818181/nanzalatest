"""Pytest fixtures for isolated, headless accounting safety-net tests."""

from pathlib import Path

import nanza_paths  # noqa: F401 - adds the application modules without starting Tk
import pytest
from database import Database


@pytest.fixture
def synthetic_db(tmp_path: Path):
    """Create a fresh synthetic company DB inside pytest's temporary directory."""
    db_path = (tmp_path / "synthetic-company.db").resolve()
    assert tmp_path.resolve() in db_path.parents

    db = Database(db_path)
    db.initialize("Synthetic-Only-Test-Password-2026")
    try:
        yield db
    finally:
        db.release()
