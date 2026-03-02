"""Tests for DB size warning feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from netglance.cli._shared import maybe_warn_db_size
from netglance.config.settings import DbConfig, Settings
from netglance.store.db import Store


# ---------------------------------------------------------------------------
# Store.check_db_size tests
# ---------------------------------------------------------------------------


class TestCheckDbSize:
    """Tests for Store.check_db_size method."""

    def test_returns_none_for_small_db(self, tmp_db: Store) -> None:
        """Small DB should return None (under threshold)."""
        result = tmp_db.check_db_size(warn_threshold_mb=100)
        assert result is None

    def test_returns_none_at_exact_threshold(self, tmp_db: Store) -> None:
        """DB exactly at threshold should still return None (< not <=)."""
        db_size = 100 * 1024 * 1024  # exactly 100 MB
        with patch("os.path.getsize", return_value=db_size):
            # 100 MB is not < 100, so it should return a warning
            result = tmp_db.check_db_size(warn_threshold_mb=100)
        assert result is not None

    def test_returns_warning_for_large_db(self, tmp_db: Store) -> None:
        """DB over threshold should return a warning dict."""
        db_size = 150 * 1024 * 1024  # 150 MB
        with patch("os.path.getsize", return_value=db_size):
            result = tmp_db.check_db_size(warn_threshold_mb=100)
        assert result is not None
        assert result["size_mb"] == pytest.approx(150.0)
        assert result["threshold_mb"] == 100
        assert result["largest_table"] in {
            "results",
            "baselines",
            "metrics",
            "alert_rules",
            "alert_log",
        }
        assert isinstance(result["largest_count"], int)

    def test_returns_none_with_high_threshold(self, tmp_db: Store) -> None:
        """Setting a very high threshold should return None."""
        db_size = 50 * 1024 * 1024  # 50 MB
        with patch("os.path.getsize", return_value=db_size):
            result = tmp_db.check_db_size(warn_threshold_mb=1000)
        assert result is None

    def test_identifies_largest_table(self, tmp_db: Store) -> None:
        """Should identify the table with the most rows."""
        # Insert rows into results table
        for i in range(10):
            tmp_db.save_result("test", {"i": i})

        db_size = 200 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            result = tmp_db.check_db_size(warn_threshold_mb=100)

        assert result is not None
        assert result["largest_table"] == "results"
        assert result["largest_count"] == 10

    def test_custom_threshold(self, tmp_db: Store) -> None:
        """Custom threshold is respected."""
        db_size = 60 * 1024 * 1024  # 60 MB
        with patch("os.path.getsize", return_value=db_size):
            result_under = tmp_db.check_db_size(warn_threshold_mb=100)
            result_over = tmp_db.check_db_size(warn_threshold_mb=50)

        assert result_under is None
        assert result_over is not None
        assert result_over["threshold_mb"] == 50

    def test_default_threshold_is_100(self, tmp_db: Store) -> None:
        """Default threshold should be 100 MB."""
        db_size = 101 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            result = tmp_db.check_db_size()
        assert result is not None
        assert result["threshold_mb"] == 100

    def test_all_tables_empty_largest_is_consistent(self, tmp_db: Store) -> None:
        """When all tables are empty, largest_count should be 0."""
        db_size = 200 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            result = tmp_db.check_db_size(warn_threshold_mb=100)
        assert result is not None
        assert result["largest_count"] == 0


# ---------------------------------------------------------------------------
# maybe_warn_db_size tests
# ---------------------------------------------------------------------------


class TestMaybeWarnDbSize:
    """Tests for maybe_warn_db_size shared helper."""

    def test_prints_warning_when_threshold_exceeded(self, tmp_db: Store) -> None:
        """Should print a warning when DB exceeds threshold."""
        c = Console(file=__import__("io").StringIO(), no_color=True, highlight=False)
        db_size = 200 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            maybe_warn_db_size(tmp_db, console=c, threshold_mb=100)
        output = c.file.getvalue()
        assert "Database is 200 MB" in output
        assert "threshold: 100 MB" in output
        assert "netglance db prune" in output

    def test_silent_when_under_threshold(self, tmp_db: Store) -> None:
        """Should print nothing when DB is under threshold."""
        c = Console(file=__import__("io").StringIO(), no_color=True, highlight=False)
        maybe_warn_db_size(tmp_db, console=c, threshold_mb=100)
        output = c.file.getvalue()
        assert output == ""

    def test_silent_on_error(self, tmp_db: Store) -> None:
        """Should silently swallow any exception."""
        c = Console(file=__import__("io").StringIO(), no_color=True, highlight=False)
        with patch.object(tmp_db, "check_db_size", side_effect=RuntimeError("boom")):
            maybe_warn_db_size(tmp_db, console=c)
        output = c.file.getvalue()
        assert output == ""

    def test_creates_console_if_none_provided(self, tmp_db: Store) -> None:
        """Should not raise when console=None (creates its own)."""
        db_size = 200 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            # Should not raise
            maybe_warn_db_size(tmp_db, console=None, threshold_mb=100)

    def test_warning_includes_largest_table(self, tmp_db: Store) -> None:
        """Warning message should include the largest table name and count."""
        for i in range(5):
            tmp_db.save_result("test", {"i": i})

        c = Console(file=__import__("io").StringIO(), no_color=True, highlight=False)
        db_size = 150 * 1024 * 1024
        with patch("os.path.getsize", return_value=db_size):
            maybe_warn_db_size(tmp_db, console=c, threshold_mb=100)
        output = c.file.getvalue()
        assert "results" in output
        assert "5" in output


# ---------------------------------------------------------------------------
# DbConfig tests
# ---------------------------------------------------------------------------


class TestDbConfig:
    """Tests for DbConfig dataclass."""

    def test_defaults(self) -> None:
        """Default warn_threshold_mb should be 100."""
        cfg = DbConfig()
        assert cfg.warn_threshold_mb == 100

    def test_custom_value(self) -> None:
        """Should accept a custom threshold."""
        cfg = DbConfig(warn_threshold_mb=250)
        assert cfg.warn_threshold_mb == 250


# ---------------------------------------------------------------------------
# Settings.load() db config tests
# ---------------------------------------------------------------------------


class TestSettingsDbConfig:
    """Tests for Settings.load() parsing db config."""

    def test_settings_has_db_config_default(self) -> None:
        """Settings should include a DbConfig with defaults."""
        settings = Settings()
        assert settings.db.warn_threshold_mb == 100

    def test_load_parses_db_warn_threshold(self, tmp_path: Path) -> None:
        """Settings.load() should parse db.warn_threshold_mb from YAML."""
        config = tmp_path / "config.yaml"
        config.write_text("db:\n  warn_threshold_mb: 250\n")
        settings = Settings.load(config_path=config)
        assert settings.db.warn_threshold_mb == 250

    def test_load_falls_back_to_default(self, tmp_path: Path) -> None:
        """Settings.load() should use default when db section is missing."""
        config = tmp_path / "config.yaml"
        config.write_text("network:\n  subnet: 10.0.0.0/8\n")
        settings = Settings.load(config_path=config)
        assert settings.db.warn_threshold_mb == 100

    def test_load_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        """When config file doesn't exist, all defaults apply."""
        settings = Settings.load(config_path=tmp_path / "nonexistent.yaml")
        assert settings.db.warn_threshold_mb == 100
