"""Tests for the firewall module."""

from __future__ import annotations

import dataclasses
import json

import pytest
from typer.testing import CliRunner

from netglance.cli.firewall import app
import netglance.modules.firewall as _fw
from netglance.modules.firewall import COMMON_EGRESS_PORTS, run_firewall_audit
from netglance.store.models import FirewallAuditReport, FirewallTestResult

runner = CliRunner()

# Aliases to avoid pytest collecting the module functions as test cases
# (those functions start with "test_" per spec but are not pytest tests)
egress_port = _fw.test_egress_port
egress_common = _fw.test_egress_common
ingress_port = _fw.test_ingress_port

# ---------------------------------------------------------------------------
# Helpers / mock connect functions
# ---------------------------------------------------------------------------


def _connect_open(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    """Simulates a successful TCP connection."""
    return True, 12.5


def _connect_blocked(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    """Simulates a refused/timed-out connection."""
    return False, None


def _make_connect_fn(open_ports: set[int]):
    """Returns a connect_fn that opens only the specified ports."""
    def _fn(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
        if port in open_ports:
            return True, 10.0
        return False, None
    return _fn


def _external_reachable(port: int, protocol: str) -> tuple[bool, float | None]:
    return True, 25.0


def _external_blocked(port: int, protocol: str) -> tuple[bool, float | None]:
    return False, None


# ---------------------------------------------------------------------------
# egress_port (test_egress_port)
# ---------------------------------------------------------------------------


def test_egress_port_open_returns_open_status():
    result = egress_port(80, _connect_fn=_connect_open)
    assert result.status == "open"


def test_egress_port_blocked_returns_blocked_status():
    result = egress_port(25, _connect_fn=_connect_blocked)
    assert result.status == "blocked"


def test_egress_port_open_has_latency():
    result = egress_port(443, _connect_fn=_connect_open)
    assert result.latency_ms == 12.5


def test_egress_port_blocked_latency_is_none():
    result = egress_port(443, _connect_fn=_connect_blocked)
    assert result.latency_ms is None


def test_egress_port_direction_is_egress():
    result = egress_port(80, _connect_fn=_connect_open)
    assert result.direction == "egress"


def test_egress_port_protocol_default_tcp():
    result = egress_port(80, _connect_fn=_connect_open)
    assert result.protocol == "tcp"


def test_egress_port_custom_protocol():
    result = egress_port(53, protocol="udp", _connect_fn=_connect_open)
    assert result.protocol == "udp"


def test_egress_port_port_stored_correctly():
    result = egress_port(8443, _connect_fn=_connect_open)
    assert result.port == 8443


def test_egress_port_target_default():
    result = egress_port(80, _connect_fn=_connect_open)
    assert result.target == "portquiz.net"


def test_egress_port_custom_target():
    result = egress_port(80, target="example.com", _connect_fn=_connect_open)
    assert result.target == "example.com"


def test_egress_port_returns_firewall_test_result():
    result = egress_port(80, _connect_fn=_connect_open)
    assert isinstance(result, FirewallTestResult)


# ---------------------------------------------------------------------------
# egress_common (test_egress_common)
# ---------------------------------------------------------------------------


def test_egress_common_returns_all_ports():
    results = egress_common(_connect_fn=_connect_open)
    assert len(results) == len(COMMON_EGRESS_PORTS)


def test_egress_common_tests_correct_ports():
    tested_ports: set[int] = set()

    def _recording_connect(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
        tested_ports.add(port)
        return True, 5.0

    egress_common(_connect_fn=_recording_connect)
    assert tested_ports == set(COMMON_EGRESS_PORTS)


def test_egress_common_all_open():
    results = egress_common(_connect_fn=_connect_open)
    assert all(r.status == "open" for r in results)


def test_egress_common_all_blocked():
    results = egress_common(_connect_fn=_connect_blocked)
    assert all(r.status == "blocked" for r in results)


def test_egress_common_mixed_results():
    open_ports = {80, 443}
    results = egress_common(_connect_fn=_make_connect_fn(open_ports))
    open_results = [r for r in results if r.status == "open"]
    blocked_results = [r for r in results if r.status == "blocked"]
    assert {r.port for r in open_results} == open_ports
    assert len(blocked_results) == len(COMMON_EGRESS_PORTS) - len(open_ports)


def test_egress_common_results_are_firewall_test_results():
    results = egress_common(_connect_fn=_connect_open)
    assert all(isinstance(r, FirewallTestResult) for r in results)


def test_egress_common_all_direction_egress():
    results = egress_common(_connect_fn=_connect_open)
    assert all(r.direction == "egress" for r in results)


# ---------------------------------------------------------------------------
# ingress_port (test_ingress_port)
# ---------------------------------------------------------------------------


def test_ingress_port_reachable():
    result = ingress_port(443, _external_fn=_external_reachable)
    assert result.status == "open"


def test_ingress_port_not_reachable():
    result = ingress_port(443, _external_fn=_external_blocked)
    assert result.status == "blocked"


def test_ingress_port_no_external_fn_returns_unknown():
    result = ingress_port(443)
    assert result.status == "unknown"


def test_ingress_port_direction_is_ingress():
    result = ingress_port(443, _external_fn=_external_reachable)
    assert result.direction == "ingress"


def test_ingress_port_stores_port():
    result = ingress_port(8080, _external_fn=_external_reachable)
    assert result.port == 8080


def test_ingress_port_stores_protocol():
    result = ingress_port(443, protocol="tcp", _external_fn=_external_reachable)
    assert result.protocol == "tcp"


def test_ingress_port_latency_on_reachable():
    result = ingress_port(443, _external_fn=_external_reachable)
    assert result.latency_ms == 25.0


def test_ingress_port_latency_none_when_blocked():
    result = ingress_port(443, _external_fn=_external_blocked)
    assert result.latency_ms is None


def test_ingress_port_returns_firewall_test_result():
    result = ingress_port(443)
    assert isinstance(result, FirewallTestResult)


# ---------------------------------------------------------------------------
# run_firewall_audit
# ---------------------------------------------------------------------------


def test_audit_returns_firewall_audit_report():
    report = run_firewall_audit(_connect_fn=_connect_open)
    assert isinstance(report, FirewallAuditReport)


def test_audit_egress_results_count():
    report = run_firewall_audit(_connect_fn=_connect_open)
    assert len(report.egress_results) == len(COMMON_EGRESS_PORTS)


def test_audit_blocked_egress_ports_populated():
    open_ports = {80, 443}
    report = run_firewall_audit(_connect_fn=_make_connect_fn(open_ports))
    expected_blocked = set(COMMON_EGRESS_PORTS) - open_ports
    assert set(report.blocked_egress_ports) == expected_blocked


def test_audit_blocked_egress_ports_empty_when_all_open():
    report = run_firewall_audit(_connect_fn=_connect_open)
    assert report.blocked_egress_ports == []


def test_audit_open_ingress_ports_empty_without_external_fn():
    report = run_firewall_audit(_connect_fn=_connect_open)
    assert report.open_ingress_ports == []


def test_audit_recommendation_for_port_25():
    report = run_firewall_audit(_connect_fn=_connect_open)
    spam_recs = [r for r in report.recommendations if "port 25" in r and "spam" in r]
    assert len(spam_recs) == 1


def test_audit_no_port25_recommendation_when_blocked():
    report = run_firewall_audit(_connect_fn=_connect_blocked)
    spam_recs = [r for r in report.recommendations if "spam" in r]
    assert len(spam_recs) == 0


def test_audit_strict_egress_recommendation_when_mostly_blocked():
    # Only 1 port open → blocked > open → strict egress recommendation
    report = run_firewall_audit(_connect_fn=_make_connect_fn({80}))
    strict_recs = [r for r in report.recommendations if "strict egress" in r]
    assert len(strict_recs) == 1


def test_audit_no_strict_egress_recommendation_when_mostly_open():
    # All ports open → no strict egress recommendation
    all_ports = set(COMMON_EGRESS_PORTS)
    report = run_firewall_audit(_connect_fn=_make_connect_fn(all_ports))
    strict_recs = [r for r in report.recommendations if "strict egress" in r]
    assert len(strict_recs) == 0


def test_audit_has_timestamp():
    report = run_firewall_audit(_connect_fn=_connect_open)
    assert report.timestamp is not None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_egress_no_args():
    result = runner.invoke(app, ["egress"], catch_exceptions=False)
    assert result.exit_code in (0, 1)


def test_cli_egress_specific_port():
    result = runner.invoke(app, ["egress", "--port", "80"], catch_exceptions=False)
    assert result.exit_code in (0, 1)


def test_cli_ingress_requires_port():
    result = runner.invoke(app, ["ingress"])
    # Should fail because --port is required
    assert result.exit_code != 0


def test_cli_ingress_with_port():
    result = runner.invoke(app, ["ingress", "--port", "443"], catch_exceptions=False)
    # status="unknown" since no external fn, should still succeed
    assert result.exit_code == 0


def test_cli_egress_json_output():
    result = runner.invoke(app, ["egress", "--json"], catch_exceptions=False)
    assert result.exit_code in (0, 1)
