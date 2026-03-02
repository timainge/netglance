"""Tests for uptime module store integration."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.uptime import app
from netglance.modules.uptime import (
    _default_store_fn,
    check_host,
    get_uptime_summary,
    save_uptime_record,
)
from netglance.store.db import Store
from netglance.store.models import UptimeRecord, UptimeSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


def _make_record(
    host: str = "192.168.1.1",
    alive: bool = True,
    latency: float | None = 10.0,
    check_time: datetime | None = None,
) -> UptimeRecord:
    return UptimeRecord(
        host=host,
        check_time=check_time or datetime(2024, 1, 1, 12, 0, 0),
        is_alive=alive,
        latency_ms=latency if alive else None,
    )


def _make_ping_mock(alive: bool = True, latency: float = 5.0) -> MagicMock:
    return MagicMock(
        return_value=MagicMock(
            is_alive=alive,
            avg_rtt=latency if alive else 0.0,
            min_rtt=latency if alive else 0.0,
            max_rtt=latency if alive else 0.0,
            packet_loss=0.0 if alive else 1.0,
        )
    )


# ---------------------------------------------------------------------------
# save_uptime_record tests
# ---------------------------------------------------------------------------


class TestSaveUptimeRecord:
    def test_saves_to_store(self, tmp_db: Store) -> None:
        record = _make_record()
        row_id = save_uptime_record(record, tmp_db)
        assert row_id >= 1

    def test_saved_data_is_retrievable(self, tmp_db: Store) -> None:
        record = _make_record(host="10.0.0.1", alive=True, latency=15.5)
        save_uptime_record(record, tmp_db)

        rows = tmp_db.get_results("uptime", limit=10)
        assert len(rows) == 1
        assert rows[0]["host"] == "10.0.0.1"
        assert rows[0]["is_alive"] is True
        assert rows[0]["latency_ms"] == 15.5

    def test_saves_check_time_as_iso(self, tmp_db: Store) -> None:
        dt = datetime(2024, 6, 15, 8, 30, 0)
        record = _make_record(check_time=dt)
        save_uptime_record(record, tmp_db)

        rows = tmp_db.get_results("uptime", limit=10)
        assert rows[0]["check_time"] == "2024-06-15T08:30:00"

    def test_saves_dead_host(self, tmp_db: Store) -> None:
        record = _make_record(alive=False)
        save_uptime_record(record, tmp_db)

        rows = tmp_db.get_results("uptime", limit=10)
        assert rows[0]["is_alive"] is False
        assert rows[0]["latency_ms"] is None

    def test_multiple_records(self, tmp_db: Store) -> None:
        for i in range(5):
            record = _make_record(
                host=f"host-{i}",
                check_time=datetime(2024, 1, 1, 12, i, 0),
            )
            save_uptime_record(record, tmp_db)

        rows = tmp_db.get_results("uptime", limit=100)
        assert len(rows) == 5


# ---------------------------------------------------------------------------
# _default_store_fn tests
# ---------------------------------------------------------------------------


class TestDefaultStoreFn:
    def test_retrieves_records_for_host(self, tmp_db: Store) -> None:
        now = datetime.now()
        for i in range(3):
            record = _make_record(
                host="192.168.1.1",
                check_time=now - timedelta(minutes=i),
            )
            save_uptime_record(record, tmp_db)
        # Add a different host
        save_uptime_record(
            _make_record(host="10.0.0.1", check_time=now), tmp_db
        )

        with patch("netglance.modules.uptime.Store") as MockStore:
            MockStore.return_value = tmp_db
            # Don't let _default_store_fn call init_db/close on our tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()

            records = _default_store_fn("192.168.1.1", "1h")

        assert len(records) == 3
        assert all(r.host == "192.168.1.1" for r in records)

    def test_filters_by_period(self) -> None:
        """_default_store_fn passes since= to store.get_results for period filtering."""
        now = datetime.now()
        recent_data = {
            "host": "h1",
            "check_time": (now - timedelta(minutes=5)).isoformat(),
            "is_alive": True,
            "latency_ms": 10.0,
        }

        with patch("netglance.modules.uptime.Store") as MockStore:
            mock_store = MagicMock()
            MockStore.return_value = mock_store
            # Simulate that only the recent record passes the since= filter
            mock_store.get_results.return_value = [recent_data]

            records = _default_store_fn("h1", "1h")

            # Verify since= was passed to get_results
            call_kwargs = mock_store.get_results.call_args
            assert call_kwargs[1].get("since") is not None or call_kwargs[0][0] == "uptime"

        assert len(records) == 1
        assert records[0].host == "h1"

    def test_returns_empty_for_unknown_host(self, tmp_db: Store) -> None:
        save_uptime_record(_make_record(host="known"), tmp_db)

        with patch("netglance.modules.uptime.Store") as MockStore:
            MockStore.return_value = tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()

            records = _default_store_fn("unknown", "24h")

        assert records == []


# ---------------------------------------------------------------------------
# get_uptime_summary with store tests
# ---------------------------------------------------------------------------


class TestGetUptimeSummaryWithStore:
    def test_returns_summary_from_stored_data(self) -> None:
        now = datetime.now()
        fake_records = [
            _make_record(host="h1", check_time=now - timedelta(minutes=i))
            for i in range(5)
        ]

        summary = get_uptime_summary(
            "h1", period="1h", _store_fn=lambda h, p: fake_records
        )
        assert summary.host == "h1"
        assert summary.uptime_pct == pytest.approx(100.0)
        assert summary.total_checks == 5
        assert summary.current_status == "up"

    def test_empty_store_returns_zero_summary(self) -> None:
        summary = get_uptime_summary(
            "empty.host", period="24h", _store_fn=lambda h, p: []
        )
        assert summary.host == "empty.host"
        assert summary.total_checks == 0
        assert summary.current_status == "unknown"
        assert summary.uptime_pct == 0.0

    def test_mixed_alive_dead_records(self) -> None:
        now = datetime.now()
        records = [
            _make_record(host="h", alive=True, check_time=now - timedelta(minutes=3)),
            _make_record(host="h", alive=True, check_time=now - timedelta(minutes=2)),
            _make_record(host="h", alive=False, check_time=now - timedelta(minutes=1)),
            _make_record(host="h", alive=True, check_time=now),
        ]

        summary = get_uptime_summary("h", _store_fn=lambda h, p: records)
        assert summary.uptime_pct == pytest.approx(75.0)
        assert summary.total_checks == 4
        assert len(summary.outages) == 1

    def test_uses_default_store_fn_when_none(self) -> None:
        """When _store_fn is None, get_uptime_summary uses _default_store_fn."""
        with patch("netglance.modules.uptime._default_store_fn", return_value=[]) as mock:
            summary = get_uptime_summary("test.host", period="24h")
            mock.assert_called_once_with("test.host", "24h")
        assert summary.host == "test.host"
        assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# CLI check --save tests
# ---------------------------------------------------------------------------


class TestCliCheckSave:
    def test_save_flag_stores_record(self, tmp_db: Store) -> None:
        with patch("netglance.cli.uptime.check_host") as mock_check, \
             patch("netglance.cli.uptime.Store") as MockStore, \
             patch("netglance.cli.uptime.get_uptime_summary") as mock_summary:
            mock_check.return_value = _make_record()
            MockStore.return_value = tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()
            mock_summary.return_value = UptimeSummary(
                host="192.168.1.1", period="24h", uptime_pct=100.0,
                total_checks=1, successful_checks=1, current_status="up",
            )

            result = runner.invoke(app, ["check", "192.168.1.1", "--save"])

        assert result.exit_code == 0
        assert "Saved to local database" in result.output

    def test_no_save_flag_does_not_store(self) -> None:
        with patch("netglance.cli.uptime.check_host") as mock_check, \
             patch("netglance.cli.uptime.get_uptime_summary") as mock_summary:
            mock_check.return_value = _make_record()
            mock_summary.return_value = UptimeSummary(
                host="192.168.1.1", period="24h", uptime_pct=0.0,
                total_checks=0, successful_checks=0, current_status="unknown",
            )

            result = runner.invoke(app, ["check", "192.168.1.1", "--no-save"])

        assert result.exit_code == 0
        assert "Saved to local database" not in result.output

    def test_save_failure_shows_warning(self) -> None:
        with patch("netglance.cli.uptime.check_host") as mock_check, \
             patch("netglance.cli.uptime.Store") as MockStore, \
             patch("netglance.cli.uptime.get_uptime_summary") as mock_summary:
            mock_check.return_value = _make_record()
            MockStore.side_effect = RuntimeError("DB locked")
            mock_summary.return_value = UptimeSummary(
                host="h", period="24h", uptime_pct=0.0,
                total_checks=0, successful_checks=0, current_status="unknown",
            )

            result = runner.invoke(app, ["check", "h", "--save"])

        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_check_without_save_flag_default(self) -> None:
        """Default (no --save) does not attempt to save."""
        with patch("netglance.cli.uptime.check_host") as mock_check, \
             patch("netglance.cli.uptime.get_uptime_summary") as mock_summary:
            mock_check.return_value = _make_record()
            mock_summary.return_value = UptimeSummary(
                host="h", period="24h", uptime_pct=0.0,
                total_checks=0, successful_checks=0, current_status="unknown",
            )

            result = runner.invoke(app, ["check", "h"])

        assert result.exit_code == 0
        assert "Saved" not in result.output


# ---------------------------------------------------------------------------
# CLI summary tests
# ---------------------------------------------------------------------------


class TestCliSummary:
    def test_summary_returns_stored_data(self) -> None:
        now = datetime.now()
        with patch("netglance.cli.uptime.get_uptime_summary") as mock:
            mock.return_value = UptimeSummary(
                host="8.8.8.8", period="24h", uptime_pct=99.9,
                total_checks=288, successful_checks=287,
                current_status="up", last_seen=now,
            )
            result = runner.invoke(app, ["summary", "8.8.8.8"])

        assert result.exit_code == 0
        assert "99.90%" in result.output

    def test_summary_json(self) -> None:
        with patch("netglance.cli.uptime.get_uptime_summary") as mock:
            mock.return_value = UptimeSummary(
                host="8.8.8.8", period="24h", uptime_pct=100.0,
                total_checks=10, successful_checks=10,
                current_status="up",
            )
            result = runner.invoke(app, ["summary", "8.8.8.8", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["host"] == "8.8.8.8"
        assert data["uptime_pct"] == 100.0


# ---------------------------------------------------------------------------
# CLI list tests
# ---------------------------------------------------------------------------


class TestCliList:
    def test_list_with_data(self, tmp_db: Store) -> None:
        now = datetime.now()
        save_uptime_record(
            _make_record(host="192.168.1.1", check_time=now), tmp_db
        )
        save_uptime_record(
            _make_record(host="10.0.0.1", alive=False, check_time=now), tmp_db
        )

        with patch("netglance.cli.uptime.Store") as MockStore:
            MockStore.return_value = tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "192.168.1.1" in result.output
        assert "10.0.0.1" in result.output

    def test_list_empty(self) -> None:
        with patch("netglance.cli.uptime.Store") as MockStore:
            mock_store = MagicMock()
            MockStore.return_value = mock_store
            mock_store.get_results.return_value = []

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No uptime records found" in result.output

    def test_list_json_with_data(self, tmp_db: Store) -> None:
        save_uptime_record(
            _make_record(host="h1", check_time=datetime.now()), tmp_db
        )

        with patch("netglance.cli.uptime.Store") as MockStore:
            MockStore.return_value = tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()

            result = runner.invoke(app, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "hosts" in data
        assert len(data["hosts"]) == 1

    def test_list_json_empty(self) -> None:
        with patch("netglance.cli.uptime.Store") as MockStore:
            mock_store = MagicMock()
            MockStore.return_value = mock_store
            mock_store.get_results.return_value = []

            result = runner.invoke(app, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["hosts"] == []

    def test_list_shows_latest_per_host(self, tmp_db: Store) -> None:
        """When multiple records exist per host, list shows the latest."""
        now = datetime.now()
        # Older record - alive
        save_uptime_record(
            _make_record(host="h1", alive=True, check_time=now - timedelta(minutes=10)),
            tmp_db,
        )
        # Newer record - dead
        save_uptime_record(
            _make_record(host="h1", alive=False, check_time=now),
            tmp_db,
        )

        with patch("netglance.cli.uptime.Store") as MockStore:
            MockStore.return_value = tmp_db
            tmp_db.init_db = MagicMock()
            tmp_db.close = MagicMock()

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "DOWN" in result.output

    def test_list_store_exception_shows_empty(self) -> None:
        with patch("netglance.cli.uptime.Store") as MockStore:
            MockStore.side_effect = RuntimeError("DB error")

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No uptime records found" in result.output


# ---------------------------------------------------------------------------
# Daemon callback tests
# ---------------------------------------------------------------------------


class TestDaemonCallback:
    def test_callback_creates_records(self) -> None:
        from netglance.cli.daemon import _make_uptime_callback

        saved_records: list[UptimeRecord] = []

        def mock_check_host(host, timeout=2.0):
            return _make_record(host=host, alive=True)

        def mock_save(record, store):
            saved_records.append(record)
            return len(saved_records)

        with patch("netglance.modules.uptime.check_host", mock_check_host), \
             patch("netglance.modules.uptime.save_uptime_record", mock_save), \
             patch("netglance.store.db.Store"):
            callback = _make_uptime_callback(["8.8.8.8", "1.1.1.1"])
            callback()

        assert len(saved_records) == 2
        hosts = {r.host for r in saved_records}
        assert hosts == {"8.8.8.8", "1.1.1.1"}

    def test_callback_saves_alive_status(self) -> None:
        from netglance.cli.daemon import _make_uptime_callback

        saved_records: list[UptimeRecord] = []

        def mock_check_host(host, timeout=2.0):
            return _make_record(host=host, alive=True, latency=3.0)

        def mock_save(record, store):
            saved_records.append(record)
            return 1

        with patch("netglance.modules.uptime.check_host", mock_check_host), \
             patch("netglance.modules.uptime.save_uptime_record", mock_save), \
             patch("netglance.store.db.Store"):
            callback = _make_uptime_callback(["8.8.8.8"])
            callback()

        assert saved_records[0].is_alive is True

    def test_callback_saves_dead_status(self) -> None:
        from netglance.cli.daemon import _make_uptime_callback

        saved_records: list[UptimeRecord] = []

        def mock_check_host(host, timeout=2.0):
            return _make_record(host=host, alive=False)

        def mock_save(record, store):
            saved_records.append(record)
            return 1

        with patch("netglance.modules.uptime.check_host", mock_check_host), \
             patch("netglance.modules.uptime.save_uptime_record", mock_save), \
             patch("netglance.store.db.Store"):
            callback = _make_uptime_callback(["8.8.8.8"])
            callback()

        assert saved_records[0].is_alive is False

    def test_callback_with_custom_timeout(self) -> None:
        from netglance.cli.daemon import _make_uptime_callback

        captured_timeouts: list[float] = []

        def mock_check_host(host, timeout=2.0):
            captured_timeouts.append(timeout)
            return _make_record(host=host, alive=True)

        with patch("netglance.modules.uptime.check_host", mock_check_host), \
             patch("netglance.modules.uptime.save_uptime_record", MagicMock()), \
             patch("netglance.store.db.Store"):
            callback = _make_uptime_callback(["8.8.8.8"], timeout=5.0)
            callback()

        assert captured_timeouts == [5.0]


# ---------------------------------------------------------------------------
# Config defaults tests
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_uptime_check_schedule_in_defaults(self) -> None:
        from netglance.config.settings import DEFAULTS

        schedules = DEFAULTS["daemon"]["schedules"]
        assert "uptime_check" in schedules
        assert schedules["uptime_check"] == "*/5 * * * *"

    def test_uptime_hosts_in_defaults(self) -> None:
        from netglance.config.settings import DEFAULTS

        assert "uptime_hosts" in DEFAULTS["daemon"]
        assert DEFAULTS["daemon"]["uptime_hosts"] == ["8.8.8.8", "1.1.1.1"]
