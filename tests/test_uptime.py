"""Tests for the uptime module."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from netglance.cli.uptime import app
from netglance.modules.uptime import check_host, compute_uptime, get_uptime_summary, _parse_period
from netglance.store.models import PingResult, UptimeRecord, UptimeSummary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ping_result(host: str, alive: bool, latency: float | None = 5.0) -> PingResult:
    return PingResult(
        host=host,
        is_alive=alive,
        avg_latency_ms=latency if alive else None,
        min_latency_ms=latency if alive else None,
        max_latency_ms=latency if alive else None,
        packet_loss=0.0 if alive else 1.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )


def _make_records(host: str, statuses: list[bool], base: datetime | None = None) -> list[UptimeRecord]:
    """Build a list of UptimeRecord from a list of bool statuses, 1-minute apart."""
    if base is None:
        base = datetime(2024, 1, 1, 10, 0, 0)
    records = []
    for i, alive in enumerate(statuses):
        records.append(
            UptimeRecord(
                host=host,
                check_time=base + timedelta(minutes=i),
                is_alive=alive,
                latency_ms=10.0 if alive else None,
            )
        )
    return records


runner = CliRunner()

# ---------------------------------------------------------------------------
# _parse_period tests
# ---------------------------------------------------------------------------

def test_parse_period_known_strings():
    assert _parse_period("24h") == timedelta(hours=24)
    assert _parse_period("7d") == timedelta(days=7)
    assert _parse_period("1h") == timedelta(hours=1)
    assert _parse_period("30d") == timedelta(days=30)


def test_parse_period_dynamic_hours():
    assert _parse_period("48h") == timedelta(hours=48)


def test_parse_period_dynamic_days():
    assert _parse_period("3d") == timedelta(days=3)


def test_parse_period_invalid():
    with pytest.raises(ValueError, match="Unknown period format"):
        _parse_period("bad")


# ---------------------------------------------------------------------------
# check_host tests
# ---------------------------------------------------------------------------

def test_check_host_alive():
    mock_fn = MagicMock(return_value=MagicMock(
        is_alive=True,
        avg_rtt=12.5,
        min_rtt=10.0,
        max_rtt=15.0,
        packet_loss=0.0,
    ))

    record = check_host("192.168.1.1", timeout=1.0, _ping_fn=mock_fn)

    assert record.host == "192.168.1.1"
    assert record.is_alive is True
    assert record.latency_ms == pytest.approx(12.5)
    assert isinstance(record.check_time, datetime)


def test_check_host_dead():
    mock_fn = MagicMock(return_value=MagicMock(
        is_alive=False,
        avg_rtt=0.0,
        min_rtt=0.0,
        max_rtt=0.0,
        packet_loss=1.0,
    ))

    record = check_host("10.0.0.1", timeout=1.0, _ping_fn=mock_fn)

    assert record.host == "10.0.0.1"
    assert record.is_alive is False
    assert record.latency_ms is None


def test_check_host_returns_uptime_record():
    mock_fn = MagicMock(return_value=MagicMock(
        is_alive=True,
        avg_rtt=5.0,
        min_rtt=4.0,
        max_rtt=6.0,
        packet_loss=0.0,
    ))
    record = check_host("example.com", _ping_fn=mock_fn)
    assert isinstance(record, UptimeRecord)


# ---------------------------------------------------------------------------
# compute_uptime tests
# ---------------------------------------------------------------------------

def test_compute_uptime_empty_records():
    summary = compute_uptime([], period="24h")
    assert summary.current_status == "unknown"
    assert summary.total_checks == 0
    assert summary.successful_checks == 0
    assert summary.uptime_pct == 0.0
    assert summary.outages == []
    assert summary.last_seen is None
    assert summary.avg_latency_ms is None


def test_compute_uptime_all_alive():
    records = _make_records("host", [True, True, True, True])
    summary = compute_uptime(records, period="24h")
    assert summary.uptime_pct == pytest.approx(100.0)
    assert summary.total_checks == 4
    assert summary.successful_checks == 4
    assert summary.current_status == "up"
    assert summary.outages == []


def test_compute_uptime_all_dead():
    records = _make_records("host", [False, False, False])
    summary = compute_uptime(records, period="24h")
    assert summary.uptime_pct == pytest.approx(0.0)
    assert summary.total_checks == 3
    assert summary.successful_checks == 0
    assert summary.current_status == "down"
    # One continuous outage
    assert len(summary.outages) == 1


def test_compute_uptime_mixed():
    # 3 alive, 1 dead → 75%
    records = _make_records("host", [True, True, False, True])
    summary = compute_uptime(records, period="24h")
    assert summary.uptime_pct == pytest.approx(75.0)
    assert summary.current_status == "up"
    assert len(summary.outages) == 1


def test_compute_uptime_single_alive_record():
    records = _make_records("host", [True])
    summary = compute_uptime(records, period="24h")
    assert summary.uptime_pct == pytest.approx(100.0)
    assert summary.total_checks == 1
    assert summary.current_status == "up"
    assert summary.outages == []


def test_compute_uptime_single_dead_record():
    records = _make_records("host", [False])
    summary = compute_uptime(records, period="24h")
    assert summary.uptime_pct == pytest.approx(0.0)
    assert summary.total_checks == 1
    assert summary.current_status == "down"
    assert len(summary.outages) == 1


def test_compute_uptime_outage_window_detection():
    base = datetime(2024, 1, 1, 10, 0, 0)
    records = _make_records("host", [True, False, False, False, True], base=base)
    summary = compute_uptime(records, period="24h")
    assert len(summary.outages) == 1
    outage = summary.outages[0]
    # Outage starts at minute 1 (index 1), ends at minute 3 (index 3)
    assert outage["start"] == base + timedelta(minutes=1)
    assert outage["end"] == base + timedelta(minutes=3)
    # duration: 2 minutes = 120 seconds
    assert outage["duration_s"] == pytest.approx(120.0)


def test_compute_uptime_multiple_outages():
    # [T, F, T, F, T] → 2 outages
    records = _make_records("host", [True, False, True, False, True])
    summary = compute_uptime(records, period="24h")
    assert len(summary.outages) == 2
    assert summary.uptime_pct == pytest.approx(60.0)


def test_compute_uptime_trailing_outage():
    # Ends on False — outage remains open
    records = _make_records("host", [True, True, False, False])
    summary = compute_uptime(records, period="24h")
    assert len(summary.outages) == 1
    assert summary.current_status == "down"


def test_compute_uptime_avg_latency():
    base = datetime(2024, 1, 1, 12, 0, 0)
    records = [
        UptimeRecord(host="h", check_time=base, is_alive=True, latency_ms=10.0),
        UptimeRecord(host="h", check_time=base + timedelta(minutes=1), is_alive=True, latency_ms=20.0),
        UptimeRecord(host="h", check_time=base + timedelta(minutes=2), is_alive=False, latency_ms=None),
    ]
    summary = compute_uptime(records)
    assert summary.avg_latency_ms == pytest.approx(15.0)


def test_compute_uptime_no_latency_when_all_dead():
    records = _make_records("host", [False, False])
    summary = compute_uptime(records)
    assert summary.avg_latency_ms is None


def test_compute_uptime_host_extracted_from_records():
    records = _make_records("myhost.local", [True])
    summary = compute_uptime(records)
    assert summary.host == "myhost.local"


def test_compute_uptime_period_label_preserved():
    records = _make_records("host", [True])
    summary = compute_uptime(records, period="7d")
    assert summary.period == "7d"


def test_compute_uptime_last_seen_when_up():
    base = datetime(2024, 1, 1, 10, 0, 0)
    records = _make_records("host", [True, True], base=base)
    summary = compute_uptime(records)
    assert summary.last_seen == base + timedelta(minutes=1)


def test_compute_uptime_last_seen_when_down_but_was_up():
    base = datetime(2024, 1, 1, 10, 0, 0)
    records = _make_records("host", [True, False], base=base)
    summary = compute_uptime(records)
    assert summary.last_seen == base  # last alive was minute 0


# ---------------------------------------------------------------------------
# get_uptime_summary tests
# ---------------------------------------------------------------------------

def test_get_uptime_summary_uses_store_fn():
    base = datetime(2024, 1, 1, 10, 0, 0)
    fake_records = _make_records("192.168.1.1", [True, True, True], base=base)

    def store_fn(host, period):
        assert host == "192.168.1.1"
        assert period == "24h"
        return fake_records

    summary = get_uptime_summary("192.168.1.1", period="24h", _store_fn=store_fn)
    assert summary.host == "192.168.1.1"
    assert summary.uptime_pct == pytest.approx(100.0)


def test_get_uptime_summary_no_store_fn_returns_unknown():
    summary = get_uptime_summary("10.0.0.1")
    assert summary.current_status == "unknown"
    assert summary.host == "10.0.0.1"
    assert summary.total_checks == 0


def test_get_uptime_summary_empty_store():
    summary = get_uptime_summary("host.local", _store_fn=lambda h, p: [])
    assert summary.host == "host.local"
    assert summary.current_status == "unknown"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_list_command():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Monitored Hosts" in result.output or "No monitored hosts" in result.output


def test_cli_list_command_json():
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output)
    assert "hosts" in data


def test_cli_summary_command_no_store(monkeypatch):
    """summary command with no store integration returns unknown status."""
    import netglance.cli.uptime as cli_mod

    monkeypatch.setattr(cli_mod, "get_uptime_summary", lambda host, period="24h", **kw: UptimeSummary(
        host=host,
        period=period,
        uptime_pct=0.0,
        total_checks=0,
        successful_checks=0,
        current_status="unknown",
    ))
    result = runner.invoke(app, ["summary", "192.168.1.1"])
    assert result.exit_code == 0


def test_cli_summary_command_json(monkeypatch):
    import netglance.cli.uptime as cli_mod

    monkeypatch.setattr(cli_mod, "get_uptime_summary", lambda host, period="24h", **kw: UptimeSummary(
        host=host,
        period=period,
        uptime_pct=99.5,
        total_checks=100,
        successful_checks=99,
        current_status="up",
    ))
    result = runner.invoke(app, ["summary", "8.8.8.8", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output)
    assert data["host"] == "8.8.8.8"
    assert data["uptime_pct"] == pytest.approx(99.5)
