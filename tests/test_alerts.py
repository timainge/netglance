"""Tests for the alerts module and CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from typer.testing import CliRunner

from netglance.cli.alerts import app
from netglance.modules.alerts import (
    acknowledge_alert,
    create_alert_rule,
    delete_alert_rule,
    evaluate_metric_alerts,
    fire_event_alert,
    get_alert_log,
    get_alert_rule,
    list_alert_rules,
    toggle_alert_rule,
)
from netglance.notify import NotificationManager
from netglance.store.db import Store
from netglance.store.models import Alert


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    """Provide an initialised in-memory-equivalent store backed by a temp file."""
    s = Store(tmp_path / "test.db")
    s.init_db()
    return s


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# create_alert_rule
# ---------------------------------------------------------------------------


def test_create_alert_rule_above(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    assert isinstance(rule_id, int)
    assert rule_id > 0


def test_create_alert_rule_below(store: Store) -> None:
    rule_id = create_alert_rule(store, "speed.download_mbps", "below", 50.0)
    assert isinstance(rule_id, int)
    assert rule_id > 0


def test_create_alert_rule_with_message(store: Store) -> None:
    rule_id = create_alert_rule(
        store, "ping.latency_ms", "above", 100.0, message="High latency detected"
    )
    rule = get_alert_rule(store, rule_id)
    assert rule is not None
    assert rule["message"] == "High latency detected"


def test_create_alert_rule_with_window(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0, window_s=600)
    rule = get_alert_rule(store, rule_id)
    assert rule is not None
    assert rule["window_s"] == 600


def test_create_alert_rule_invalid_condition(store: Store) -> None:
    with pytest.raises(ValueError, match="above.*below"):
        create_alert_rule(store, "ping.latency_ms", "equals", 100.0)


def test_create_alert_rule_invalid_condition_empty(store: Store) -> None:
    with pytest.raises(ValueError):
        create_alert_rule(store, "ping.latency_ms", "", 100.0)


# ---------------------------------------------------------------------------
# list_alert_rules
# ---------------------------------------------------------------------------


def test_list_alert_rules_empty(store: Store) -> None:
    rules = list_alert_rules(store)
    assert rules == []


def test_list_alert_rules_one(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    rules = list_alert_rules(store)
    assert len(rules) == 1
    assert rules[0]["metric"] == "ping.latency_ms"
    assert rules[0]["condition"] == "above"
    assert rules[0]["threshold"] == 100.0
    assert rules[0]["enabled"] == 1


def test_list_alert_rules_multiple(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    create_alert_rule(store, "speed.download_mbps", "below", 50.0)
    create_alert_rule(store, "dns.response_ms", "above", 500.0)
    rules = list_alert_rules(store)
    assert len(rules) == 3
    metrics = [r["metric"] for r in rules]
    assert "ping.latency_ms" in metrics
    assert "speed.download_mbps" in metrics
    assert "dns.response_ms" in metrics


def test_list_alert_rules_keys(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    rules = list_alert_rules(store)
    expected_keys = {"id", "metric", "condition", "threshold", "window_s", "enabled", "message"}
    assert set(rules[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# get_alert_rule
# ---------------------------------------------------------------------------


def test_get_alert_rule_existing(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    rule = get_alert_rule(store, rule_id)
    assert rule is not None
    assert rule["id"] == rule_id
    assert rule["metric"] == "ping.latency_ms"


def test_get_alert_rule_not_found(store: Store) -> None:
    rule = get_alert_rule(store, 9999)
    assert rule is None


# ---------------------------------------------------------------------------
# delete_alert_rule
# ---------------------------------------------------------------------------


def test_delete_alert_rule_existing(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    result = delete_alert_rule(store, rule_id)
    assert result is True
    assert get_alert_rule(store, rule_id) is None


def test_delete_alert_rule_not_found(store: Store) -> None:
    result = delete_alert_rule(store, 9999)
    assert result is False


def test_delete_alert_rule_removes_from_list(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    delete_alert_rule(store, rule_id)
    assert list_alert_rules(store) == []


# ---------------------------------------------------------------------------
# toggle_alert_rule
# ---------------------------------------------------------------------------


def test_toggle_alert_rule_disable(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    result = toggle_alert_rule(store, rule_id, enabled=False)
    assert result is True
    rule = get_alert_rule(store, rule_id)
    assert rule is not None
    assert rule["enabled"] == 0


def test_toggle_alert_rule_enable(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    toggle_alert_rule(store, rule_id, enabled=False)
    result = toggle_alert_rule(store, rule_id, enabled=True)
    assert result is True
    rule = get_alert_rule(store, rule_id)
    assert rule is not None
    assert rule["enabled"] == 1


def test_toggle_alert_rule_not_found(store: Store) -> None:
    result = toggle_alert_rule(store, 9999, enabled=False)
    assert result is False


# ---------------------------------------------------------------------------
# evaluate_metric_alerts
# ---------------------------------------------------------------------------


def test_evaluate_metric_alerts_above_triggered(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    assert len(fired) == 1


def test_evaluate_metric_alerts_above_not_triggered(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 50.0)
    assert fired == []


def test_evaluate_metric_alerts_below_triggered(store: Store) -> None:
    create_alert_rule(store, "speed.download_mbps", "below", 50.0)
    fired = evaluate_metric_alerts(store, "speed.download_mbps", 10.0)
    assert len(fired) == 1


def test_evaluate_metric_alerts_below_not_triggered(store: Store) -> None:
    create_alert_rule(store, "speed.download_mbps", "below", 50.0)
    fired = evaluate_metric_alerts(store, "speed.download_mbps", 100.0)
    assert fired == []


def test_evaluate_metric_alerts_at_threshold_not_triggered(store: Store) -> None:
    """Exact threshold value should NOT trigger (strictly above/below)."""
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 100.0)
    assert fired == []


def test_evaluate_metric_alerts_disabled_rule_skipped(store: Store) -> None:
    rule_id = create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    toggle_alert_rule(store, rule_id, enabled=False)
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 200.0)
    assert fired == []


def test_evaluate_metric_alerts_wrong_metric_skipped(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    fired = evaluate_metric_alerts(store, "speed.download_mbps", 0.0)
    assert fired == []


def test_evaluate_metric_alerts_logs_to_alert_log(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    log = get_alert_log(store)
    assert len(log) == 1
    assert log[0]["metric"] == "ping.latency_ms"
    assert log[0]["value"] == 150.0
    assert log[0]["threshold"] == 100.0
    assert log[0]["acknowledged"] == 0


def test_evaluate_metric_alerts_uses_rule_message(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0, message="Latency is high!")
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 200.0)
    assert fired[0] == "Latency is high!"


def test_evaluate_metric_alerts_default_message(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    assert "ping.latency_ms" in fired[0]
    assert "150" in fired[0]
    assert "100" in fired[0]


def test_evaluate_metric_alerts_with_notify_manager(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    create_alert_rule(store, "ping.latency_ms", "above", 100.0, message="High latency!")
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 200.0, notify_manager=mock_manager)
    assert len(fired) == 1
    mock_manager.notify.assert_called_once()
    alert_arg = mock_manager.notify.call_args[0][0]
    assert isinstance(alert_arg, Alert)
    assert alert_arg.category == "metric_threshold"
    assert alert_arg.message == "High latency!"


def test_evaluate_metric_alerts_no_notify_when_not_triggered(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 50.0, notify_manager=mock_manager)
    mock_manager.notify.assert_not_called()


def test_evaluate_metric_alerts_multiple_rules(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0, message="Slow ping")
    create_alert_rule(store, "ping.latency_ms", "above", 200.0, message="Very slow ping")
    fired = evaluate_metric_alerts(store, "ping.latency_ms", 250.0)
    assert len(fired) == 2


# ---------------------------------------------------------------------------
# get_alert_log
# ---------------------------------------------------------------------------


def test_get_alert_log_empty(store: Store) -> None:
    log = get_alert_log(store)
    assert log == []


def test_get_alert_log_basic(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    log = get_alert_log(store)
    assert len(log) == 1
    entry = log[0]
    assert set(entry.keys()) == {"id", "ts", "rule_id", "metric", "value", "threshold", "message", "acknowledged"}


def test_get_alert_log_since_filter(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    # since future: should return nothing
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    log = get_alert_log(store, since=future)
    assert log == []


def test_get_alert_log_since_past(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    log = get_alert_log(store, since=past)
    assert len(log) == 1


def test_get_alert_log_limit(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    for _ in range(5):
        evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    log = get_alert_log(store, limit=3)
    assert len(log) == 3


def test_get_alert_log_unacknowledged_only(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 200.0)
    log = get_alert_log(store)
    # Acknowledge the first
    acknowledge_alert(store, log[0]["id"])
    unacked = get_alert_log(store, unacknowledged_only=True)
    assert all(entry["acknowledged"] == 0 for entry in unacked)
    assert len(unacked) == 1


# ---------------------------------------------------------------------------
# acknowledge_alert
# ---------------------------------------------------------------------------


def test_acknowledge_alert_existing(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    log = get_alert_log(store)
    alert_id = log[0]["id"]

    result = acknowledge_alert(store, alert_id)
    assert result is True

    log_after = get_alert_log(store)
    assert log_after[0]["acknowledged"] == 1


def test_acknowledge_alert_not_found(store: Store) -> None:
    result = acknowledge_alert(store, 9999)
    assert result is False


def test_acknowledge_alert_idempotent(store: Store) -> None:
    create_alert_rule(store, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(store, "ping.latency_ms", 150.0)
    log = get_alert_log(store)
    alert_id = log[0]["id"]

    acknowledge_alert(store, alert_id)
    result = acknowledge_alert(store, alert_id)
    assert result is True


# ---------------------------------------------------------------------------
# fire_event_alert
# ---------------------------------------------------------------------------


def test_fire_event_alert_calls_notify(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    fire_event_alert(
        mock_manager,
        category="new_device",
        title="New device detected",
        message="192.168.1.50 joined the network",
    )
    mock_manager.notify.assert_called_once()
    alert_arg = mock_manager.notify.call_args[0][0]
    assert isinstance(alert_arg, Alert)
    assert alert_arg.category == "new_device"
    assert alert_arg.title == "New device detected"
    assert alert_arg.message == "192.168.1.50 joined the network"
    assert alert_arg.severity == "warning"


def test_fire_event_alert_custom_severity(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    fire_event_alert(
        mock_manager,
        category="arp_spoof",
        title="ARP spoofing detected",
        message="Gateway MAC changed!",
        severity="critical",
    )
    alert_arg = mock_manager.notify.call_args[0][0]
    assert alert_arg.severity == "critical"


def test_fire_event_alert_with_data(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    extra = {"ip": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"}
    fire_event_alert(
        mock_manager,
        category="new_device",
        title="New device",
        message="Device joined",
        data=extra,
    )
    alert_arg = mock_manager.notify.call_args[0][0]
    assert alert_arg.data == extra


def test_fire_event_alert_no_data_defaults_to_empty(store: Store) -> None:
    mock_manager = MagicMock(spec=NotificationManager)
    fire_event_alert(mock_manager, category="info", title="T", message="M")
    alert_arg = mock_manager.notify.call_args[0][0]
    assert alert_arg.data == {}


# ---------------------------------------------------------------------------
# CLI tests via CliRunner
# ---------------------------------------------------------------------------


def _db_arg(tmp_path: Path) -> str:
    return str(tmp_path / "cli_test.db")


def test_cli_add_below(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    result = runner.invoke(
        app,
        ["add", "--metric", "speed.download_mbps", "--below", "50", "--db", db],
    )
    assert result.exit_code == 0
    assert "Created alert rule" in result.output


def test_cli_add_above(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    result = runner.invoke(
        app,
        ["add", "--metric", "ping.latency_ms", "--above", "100", "--db", db],
    )
    assert result.exit_code == 0
    assert "Created alert rule" in result.output


def test_cli_add_no_condition(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    result = runner.invoke(app, ["add", "--metric", "ping.latency_ms", "--db", db])
    assert result.exit_code != 0
    assert "above" in result.output.lower() or "below" in result.output.lower()


def test_cli_add_both_conditions(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    result = runner.invoke(
        app,
        ["add", "--metric", "ping.latency_ms", "--above", "100", "--below", "50", "--db", db],
    )
    assert result.exit_code != 0


def test_cli_list_empty(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    # Init DB first
    s = Store(db)
    s.init_db()
    s.close()
    result = runner.invoke(app, ["list", "--db", db])
    assert result.exit_code == 0
    assert "No alert rules" in result.output


def test_cli_list_shows_rules(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    runner.invoke(app, ["add", "--metric", "ping.latency_ms", "--above", "100", "--db", db])
    result = runner.invoke(app, ["list", "--db", db])
    assert result.exit_code == 0
    assert "ping.latency_ms" in result.output


def test_cli_list_json(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    runner.invoke(app, ["add", "--metric", "ping.latency_ms", "--above", "100", "--db", db])
    result = runner.invoke(app, ["list", "--json", "--db", db])
    assert result.exit_code == 0
    data = _json_mod.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["metric"] == "ping.latency_ms"


def test_cli_delete_existing(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    runner.invoke(app, ["add", "--metric", "ping.latency_ms", "--above", "100", "--db", db])
    result = runner.invoke(app, ["delete", "1", "--db", db])
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_cli_delete_not_found(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    s.close()
    result = runner.invoke(app, ["delete", "999", "--db", db])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_enable_disable(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    runner.invoke(app, ["add", "--metric", "ping.latency_ms", "--above", "100", "--db", db])

    result = runner.invoke(app, ["disable", "1", "--db", db])
    assert result.exit_code == 0
    assert "Disabled" in result.output

    result = runner.invoke(app, ["enable", "1", "--db", db])
    assert result.exit_code == 0
    assert "Enabled" in result.output


def test_cli_log_empty(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    s.close()
    result = runner.invoke(app, ["log", "--db", db])
    assert result.exit_code == 0
    assert "No alert log" in result.output


def test_cli_log_shows_entries(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    create_alert_rule(s, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(s, "ping.latency_ms", 150.0)
    s.close()

    result = runner.invoke(app, ["log", "--db", db])
    assert result.exit_code == 0
    # Rich table may truncate column content in narrow terminal; verify the table was rendered
    assert "Alert Log" in result.output


def test_cli_log_since(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    create_alert_rule(s, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(s, "ping.latency_ms", 150.0)
    s.close()

    result = runner.invoke(app, ["log", "--since", "1h", "--db", db])
    assert result.exit_code == 0
    assert "Alert Log" in result.output


def test_cli_log_since_invalid(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    s.close()
    result = runner.invoke(app, ["log", "--since", "invalid", "--db", db])
    assert result.exit_code != 0


def test_cli_ack(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    create_alert_rule(s, "ping.latency_ms", "above", 100.0)
    evaluate_metric_alerts(s, "ping.latency_ms", 150.0)
    log = get_alert_log(s)
    alert_id = log[0]["id"]
    s.close()

    result = runner.invoke(app, ["ack", str(alert_id), "--db", db])
    assert result.exit_code == 0
    assert "Acknowledged" in result.output


def test_cli_ack_not_found(tmp_path: Path, runner: CliRunner) -> None:
    db = _db_arg(tmp_path)
    s = Store(db)
    s.init_db()
    s.close()
    result = runner.invoke(app, ["ack", "9999", "--db", db])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


import json as _json_mod  # noqa: E402 (re-import needed for JSON test helper)
