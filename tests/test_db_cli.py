"""Tests for database management CLI and Store methods."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netglance.cli.db import app as db_app
from netglance.cli.baseline import app as baseline_app
from netglance.store.db import VALID_TABLES, Store

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_result(store: Store, module: str = "ping", days_ago: int = 0) -> int:
    """Insert a result row with a timestamp offset by days_ago."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    cur = store.conn.execute(
        "INSERT INTO results (module, timestamp, data) VALUES (?, ?, ?)",
        (module, ts, json.dumps({"test": True})),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_metric(store: Store, metric: str = "latency", days_ago: int = 0) -> int:
    """Insert a metric row with a timestamp offset by days_ago."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    cur = store.conn.execute(
        "INSERT INTO metrics (ts, metric, value, tags) VALUES (?, ?, ?, ?)",
        (ts, metric, 42.0, None),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_baseline(store: Store, label: str | None = None) -> int:
    """Insert a baseline row."""
    cur = store.conn.execute(
        "INSERT INTO baselines (label, timestamp, data) VALUES (?, ?, ?)",
        (label, datetime.now(timezone.utc).isoformat(), json.dumps({"devices": []})),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_alert_rule(store: Store) -> int:
    """Insert an alert rule row."""
    cur = store.conn.execute(
        "INSERT INTO alert_rules (metric, condition, threshold, window_s, enabled, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("latency", "above", 100.0, 300, 1, "test"),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_alert_log(store: Store, rule_id: int = 1) -> int:
    """Insert an alert log entry."""
    cur = store.conn.execute(
        "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message, acknowledged) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), rule_id, "latency", 150.0, 100.0, "test alert", 0),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ===========================================================================
# Store method tests
# ===========================================================================


class TestCountRows:
    def test_empty_tables(self, tmp_db: Store) -> None:
        for table in VALID_TABLES:
            assert tmp_db.count_rows(table) == 0

    def test_after_insert(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        _insert_result(tmp_db)
        assert tmp_db.count_rows("results") == 2

    def test_invalid_table_raises(self, tmp_db: Store) -> None:
        with pytest.raises(ValueError, match="Unknown table"):
            tmp_db.count_rows("nonexistent")

    def test_injection_attempt_raises(self, tmp_db: Store) -> None:
        with pytest.raises(ValueError, match="Unknown table"):
            tmp_db.count_rows("results; DROP TABLE results")


class TestPruneResults:
    def test_deletes_old_rows(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, days_ago=400)
        _insert_result(tmp_db, days_ago=400)
        _insert_result(tmp_db, days_ago=10)
        deleted = tmp_db.prune_results(older_than_days=365)
        assert deleted == 2
        assert tmp_db.count_rows("results") == 1

    def test_keeps_recent_rows(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, days_ago=0)
        _insert_result(tmp_db, days_ago=30)
        deleted = tmp_db.prune_results(older_than_days=365)
        assert deleted == 0
        assert tmp_db.count_rows("results") == 2

    def test_empty_table(self, tmp_db: Store) -> None:
        deleted = tmp_db.prune_results(older_than_days=365)
        assert deleted == 0


class TestDeleteBaseline:
    def test_delete_existing(self, tmp_db: Store) -> None:
        bid = _insert_baseline(tmp_db, label="test")
        assert tmp_db.delete_baseline(bid) is True
        assert tmp_db.count_rows("baselines") == 0

    def test_delete_nonexistent(self, tmp_db: Store) -> None:
        assert tmp_db.delete_baseline(9999) is False

    def test_delete_specific_id(self, tmp_db: Store) -> None:
        _insert_baseline(tmp_db, label="keep")
        bid = _insert_baseline(tmp_db, label="delete-me")
        tmp_db.delete_baseline(bid)
        assert tmp_db.count_rows("baselines") == 1


class TestResetAll:
    def test_clears_all_tables(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        _insert_baseline(tmp_db)
        _insert_metric(tmp_db)
        _insert_alert_rule(tmp_db)
        _insert_alert_log(tmp_db)

        counts = tmp_db.reset_all()
        assert counts["results"] == 1
        assert counts["baselines"] == 1
        assert counts["metrics"] == 1
        assert counts["alert_rules"] == 1
        assert counts["alert_log"] == 1

        for table in VALID_TABLES:
            assert tmp_db.count_rows(table) == 0

    def test_empty_db(self, tmp_db: Store) -> None:
        counts = tmp_db.reset_all()
        for table in VALID_TABLES:
            assert counts[table] == 0


class TestExportAll:
    def test_empty_db(self, tmp_db: Store) -> None:
        data = tmp_db.export_all()
        for table in VALID_TABLES:
            assert table in data
            assert data[table] == []

    def test_with_data(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, module="dns")
        _insert_baseline(tmp_db, label="export-test")
        data = tmp_db.export_all()
        assert len(data["results"]) == 1
        assert data["results"][0]["module"] == "dns"
        assert len(data["baselines"]) == 1
        assert data["baselines"][0]["label"] == "export-test"


class TestImportAll:
    def test_merge_mode(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        export = tmp_db.export_all()
        counts = tmp_db.import_all(export, mode="merge")
        assert counts["results"] == 1
        assert tmp_db.count_rows("results") == 2

    def test_replace_mode(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        _insert_result(tmp_db)
        export = tmp_db.export_all()
        # Import with replace: wipes 2 rows, then imports 2
        counts = tmp_db.import_all(export, mode="replace")
        assert counts["results"] == 2
        assert tmp_db.count_rows("results") == 2

    def test_empty_import(self, tmp_db: Store) -> None:
        counts = tmp_db.import_all({}, mode="merge")
        for table in VALID_TABLES:
            assert counts[table] == 0


class TestExportImportRoundTrip:
    def test_preserves_data(self, tmp_db: Store, tmp_path: Path) -> None:
        _insert_result(tmp_db, module="ping")
        _insert_baseline(tmp_db, label="roundtrip")
        _insert_metric(tmp_db, metric="latency")

        exported = tmp_db.export_all()
        # Write to file and read back
        f = tmp_path / "export.json"
        f.write_text(json.dumps(exported))
        reimported = json.loads(f.read_text())

        # Replace into a fresh store
        fresh = Store(db_path=tmp_path / "fresh.db")
        fresh.init_db()
        fresh.import_all(reimported, mode="replace")

        re_exported = fresh.export_all()
        fresh.close()

        assert len(re_exported["results"]) == 1
        assert re_exported["results"][0]["module"] == "ping"
        assert len(re_exported["baselines"]) == 1
        assert re_exported["baselines"][0]["label"] == "roundtrip"
        assert len(re_exported["metrics"]) == 1


# ===========================================================================
# CLI tests — db subcommand
# ===========================================================================


class TestDbStatusCLI:
    def test_shows_table_names(self, tmp_db: Store) -> None:
        result = runner.invoke(db_app, ["status", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        for table in VALID_TABLES:
            assert table in result.output

    def test_shows_counts(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        _insert_result(tmp_db)
        result = runner.invoke(db_app, ["status", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_json_output(self, tmp_db: Store) -> None:
        result = runner.invoke(db_app, ["status", "--json", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "path" in data
        assert "size_bytes" in data
        assert "tables" in data
        for table in VALID_TABLES:
            assert table in data["tables"]


class TestDbPruneCLI:
    def test_dry_run(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, days_ago=400)
        _insert_metric(tmp_db, days_ago=400)
        result = runner.invoke(db_app, ["prune", "--dry-run", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "Dry run" in result.output
        # Data should still be there
        assert tmp_db.count_rows("results") == 1
        assert tmp_db.count_rows("metrics") == 1

    def test_actual_prune(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, days_ago=400)
        _insert_metric(tmp_db, days_ago=400)
        _insert_result(tmp_db, days_ago=0)
        result = runner.invoke(db_app, ["prune", "--days", "365", "--results-days", "365", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "Pruned" in result.output
        assert tmp_db.count_rows("results") == 1
        assert tmp_db.count_rows("metrics") == 0

    def test_prune_nothing(self, tmp_db: Store) -> None:
        _insert_result(tmp_db, days_ago=0)
        result = runner.invoke(db_app, ["prune", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "Pruned 0 metrics rows, 0 results rows." in result.output


class TestDbResetCLI:
    def test_without_confirm_exits_error(self, tmp_db: Store) -> None:
        result = runner.invoke(db_app, ["reset", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 1
        assert "confirm" in result.output.lower()

    def test_with_confirm_wipes_data(self, tmp_db: Store) -> None:
        _insert_result(tmp_db)
        _insert_baseline(tmp_db)
        result = runner.invoke(db_app, ["reset", "--confirm", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "reset complete" in result.output.lower()
        for table in VALID_TABLES:
            assert tmp_db.count_rows(table) == 0


class TestDbExportCLI:
    def test_creates_file(self, tmp_db: Store, tmp_path: Path) -> None:
        _insert_result(tmp_db)
        out = tmp_path / "export.json"
        result = runner.invoke(db_app, ["export", "--output", str(out), "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "results" in data
        assert len(data["results"]) == 1

    def test_export_empty_db(self, tmp_db: Store, tmp_path: Path) -> None:
        out = tmp_path / "empty.json"
        result = runner.invoke(db_app, ["export", "--output", str(out), "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "Exported 0 total rows" in result.output


class TestDbImportCLI:
    def test_import_file(self, tmp_db: Store, tmp_path: Path) -> None:
        _insert_result(tmp_db, module="dns")
        export = tmp_db.export_all()
        tmp_db.reset_all()

        f = tmp_path / "import.json"
        f.write_text(json.dumps(export))

        result = runner.invoke(db_app, ["import", str(f), "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert tmp_db.count_rows("results") == 1

    def test_import_replace_mode(self, tmp_db: Store, tmp_path: Path) -> None:
        _insert_result(tmp_db)
        _insert_result(tmp_db)
        # Export only 1 result
        export = {"results": [{"module": "scan", "timestamp": datetime.now(timezone.utc).isoformat(), "data": "{}"}]}
        f = tmp_path / "replace.json"
        f.write_text(json.dumps(export))

        result = runner.invoke(db_app, ["import", str(f), "--mode", "replace", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert tmp_db.count_rows("results") == 1

    def test_import_nonexistent_file(self, tmp_db: Store) -> None:
        result = runner.invoke(db_app, ["import", "/tmp/does-not-exist.json", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 1


# ===========================================================================
# CLI tests — baseline delete
# ===========================================================================


class TestBaselineDeleteCLI:
    def test_delete_existing(self, tmp_db: Store) -> None:
        bid = _insert_baseline(tmp_db, label="to-delete")
        result = runner.invoke(baseline_app, ["delete", str(bid), "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert tmp_db.count_rows("baselines") == 0

    def test_delete_nonexistent(self, tmp_db: Store) -> None:
        result = runner.invoke(baseline_app, ["delete", "9999", "--db", str(tmp_db.db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_delete_preserves_others(self, tmp_db: Store) -> None:
        _insert_baseline(tmp_db, label="keep")
        bid = _insert_baseline(tmp_db, label="remove")
        result = runner.invoke(baseline_app, ["delete", str(bid), "--db", str(tmp_db.db_path)])
        assert result.exit_code == 0
        assert tmp_db.count_rows("baselines") == 1
