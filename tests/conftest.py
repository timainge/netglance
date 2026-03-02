"""Shared test fixtures for netglance."""

import tempfile
from pathlib import Path

import pytest

from netglance.store.db import Store


@pytest.fixture
def tmp_db(tmp_path: Path) -> Store:
    """Provide a Store backed by a temporary SQLite database."""
    store = Store(db_path=tmp_path / "test.db")
    store.init_db()
    yield store  # type: ignore[misc]
    store.close()


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Provide a temporary config file path."""
    config_path = tmp_path / "config.yaml"
    return config_path
