"""Comprehensive tests for the netglance REST API server."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from netglance.api.server import _parse_period, _to_dict, create_app
from netglance.store.db import Store
from netglance.store.models import (
    ArpAlert,
    ArpEntry,
    CheckStatus,
    Device,
    DnsHealthReport,
    DnsResolverResult,
    HealthReport,
    HostScanResult,
    NetworkPerformanceResult,
    PingResult,
    PortResult,
    SpeedTestResult,
    TlsCheckResult,
    CertInfo,
    UptimeSummary,
    VpnLeakReport,
    WifiNetwork,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    """Create a temporary SQLite database and return its path."""
    db_path = str(tmp_path / "test.db")
    store = Store(db_path=db_path)
    store.init_db()
    return db_path


@pytest.fixture()
def store(tmp_db: str) -> Store:
    s = Store(db_path=tmp_db)
    s.init_db()
    return s


def _make_ping_result(host: str = "192.168.1.1", alive: bool = True) -> PingResult:
    return PingResult(
        host=host,
        is_alive=alive,
        avg_latency_ms=5.0 if alive else None,
        min_latency_ms=4.0 if alive else None,
        max_latency_ms=6.0 if alive else None,
        packet_loss=0.0 if alive else 1.0,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )


def _make_device(ip: str = "192.168.1.100") -> Device:
    return Device(
        ip=ip,
        mac="aa:bb:cc:dd:ee:ff",
        hostname="test-device",
        vendor="TestCorp",
        discovery_method="arp",
        first_seen=datetime(2026, 1, 1),
        last_seen=datetime(2026, 1, 1),
    )


def _make_dns_report() -> DnsHealthReport:
    return DnsHealthReport(
        resolvers_checked=2,
        consistent=True,
        fastest_resolver="1.1.1.1",
        dnssec_supported=False,
        potential_hijack=False,
        details=[
            DnsResolverResult(
                resolver="1.1.1.1",
                resolver_name="Cloudflare",
                query="example.com",
                answers=["93.184.216.34"],
                response_time_ms=10.0,
            )
        ],
    )


def _make_scan_result(host: str = "192.168.1.1") -> HostScanResult:
    return HostScanResult(
        host=host,
        ports=[PortResult(port=80, state="open", service="http")],
        scan_time=datetime(2026, 1, 1),
        scan_duration_s=1.5,
    )


def _make_cert() -> CertInfo:
    return CertInfo(
        host="example.com",
        port=443,
        subject="CN=example.com",
        issuer="O=DigiCert Inc",
        root_ca="DigiCert Inc",
        fingerprint_sha256="ab" * 32,
        not_before=datetime(2025, 1, 1),
        not_after=datetime(2027, 1, 1),
        san=["example.com", "www.example.com"],
        chain_length=3,
    )


def _make_tls_result(host: str = "example.com") -> TlsCheckResult:
    return TlsCheckResult(
        host=host,
        cert=_make_cert(),
        is_trusted=True,
        is_intercepted=False,
        details="OK",
    )


def _make_speed_result() -> SpeedTestResult:
    return SpeedTestResult(
        download_mbps=150.0,
        upload_mbps=50.0,
        latency_ms=10.0,
        jitter_ms=2.0,
        server="speed.cloudflare.com",
        provider="cloudflare",
        timestamp=datetime(2026, 1, 1),
    )


def _make_vpn_report() -> VpnLeakReport:
    return VpnLeakReport(
        vpn_detected=False,
        dns_leak=False,
        ipv6_leak=False,
        timestamp=datetime(2026, 1, 1),
    )


def _make_uptime_summary(host: str = "8.8.8.8") -> UptimeSummary:
    return UptimeSummary(
        host=host,
        period="24h",
        uptime_pct=99.9,
        total_checks=100,
        successful_checks=99,
        avg_latency_ms=5.0,
        outages=[],
        current_status="up",
        last_seen=datetime(2026, 1, 1),
    )


def _make_perf_result(host: str = "8.8.8.8") -> NetworkPerformanceResult:
    return NetworkPerformanceResult(
        target=host,
        avg_latency_ms=10.0,
        jitter_ms=2.0,
        p95_latency_ms=15.0,
        p99_latency_ms=20.0,
        packet_loss_pct=0.0,
        path_mtu=1500,
        bufferbloat_rating="A",
        timestamp=datetime(2026, 1, 1),
    )


def _make_health_report() -> HealthReport:
    return HealthReport(
        timestamp=datetime(2026, 1, 1),
        checks=[
            CheckStatus(module="ping", status="pass", summary="All OK", details=[])
        ],
        overall_status="pass",
    )


def _make_arp_entries() -> list[ArpEntry]:
    return [ArpEntry(ip="192.168.1.1", mac="aa:bb:cc:11:22:33", interface="en0")]


def _make_arp_alerts() -> list[ArpAlert]:
    return []


def _make_wifi_network() -> WifiNetwork:
    return WifiNetwork(
        ssid="TestNet",
        bssid="aa:bb:cc:dd:ee:ff",
        channel=6,
        band="2.4GHz",
        signal_dbm=-60,
        security="WPA2",
    )


# ---------------------------------------------------------------------------
# App factory helper
# ---------------------------------------------------------------------------


def _make_client(api_key=None, tmp_db=None, **overrides) -> TestClient:
    """Build a TestClient with mock DI functions."""
    defaults = dict(
        _discover_fn=lambda subnet: [_make_device()],
        _ping_fn=lambda host, **kw: _make_ping_result(host),
        _gateway_fn=lambda: _make_ping_result("192.168.1.1"),
        _dns_fn=lambda: _make_dns_report(),
        _scan_fn=lambda host, **kw: _make_scan_result(host),
        _arp_fn=lambda: (_make_arp_entries(), _make_arp_alerts()),
        _tls_fn=lambda host, **kw: _make_tls_result(host),
        _wifi_fn=lambda: {"current": None, "networks": []},
        _report_fn=lambda **kw: _make_health_report(),
        _speed_fn=lambda **kw: _make_speed_result(),
        _vpn_fn=lambda: _make_vpn_report(),
        _uptime_fn=lambda host, **kw: _make_uptime_summary(host),
        _perf_fn=lambda host: _make_perf_result(host),
    )
    defaults.update(overrides)
    app = create_app(api_key=api_key, db_path=tmp_db, **defaults)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Serialization helper tests
# ---------------------------------------------------------------------------


def test_to_dict_primitive():
    assert _to_dict(42) == 42
    assert _to_dict("hello") == "hello"
    assert _to_dict(None) is None


def test_to_dict_datetime():
    dt = datetime(2026, 1, 15, 12, 0, 0)
    result = _to_dict(dt)
    assert result == "2026-01-15T12:00:00"


def test_to_dict_dataclass():
    device = _make_device()
    result = _to_dict(device)
    assert isinstance(result, dict)
    assert result["ip"] == "192.168.1.100"
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"


def test_to_dict_list():
    devices = [_make_device("192.168.1.1"), _make_device("192.168.1.2")]
    result = _to_dict(devices)
    assert len(result) == 2
    assert result[0]["ip"] == "192.168.1.1"


def test_to_dict_nested():
    report = _make_dns_report()
    result = _to_dict(report)
    assert "details" in result
    assert isinstance(result["details"], list)


def test_parse_period_hours():
    from datetime import timedelta
    delta = _parse_period("24h")
    assert delta == timedelta(hours=24)


def test_parse_period_days():
    from datetime import timedelta
    delta = _parse_period("7d")
    assert delta == timedelta(days=7)


def test_parse_period_minutes():
    from datetime import timedelta
    delta = _parse_period("30m")
    assert delta == timedelta(minutes=30)


def test_parse_period_invalid():
    with pytest.raises(ValueError, match="Unknown period format"):
        _parse_period("invalid")


# ---------------------------------------------------------------------------
# Health endpoint (no auth)
# ---------------------------------------------------------------------------


def test_health_endpoint():
    client = _make_client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_health_endpoint_no_auth_required():
    """Health check should work even when API key is set."""
    client = _make_client(api_key="secret123")
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


def test_auth_disabled_by_default():
    client = _make_client()
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 200


def test_auth_required_when_key_set():
    client = _make_client(api_key="mysecret")
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 401


def test_auth_valid_key_accepted():
    client = _make_client(api_key="mysecret")
    resp = client.get("/api/v1/discover", headers={"X-API-Key": "mysecret"})
    assert resp.status_code == 200


def test_auth_wrong_key_rejected():
    client = _make_client(api_key="mysecret")
    resp = client.get("/api/v1/discover", headers={"X-API-Key": "wrongkey"})
    assert resp.status_code == 401


def test_auth_env_var(monkeypatch):
    monkeypatch.setenv("NETGLANCE_API_KEY", "envkey")
    app = create_app(
        _discover_fn=lambda subnet: [_make_device()],
    )
    client = TestClient(app)
    # Without key → 401
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 401
    # With correct key → 200
    resp = client.get("/api/v1/discover", headers={"X-API-Key": "envkey"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CORS tests
# ---------------------------------------------------------------------------


def test_cors_headers():
    client = _make_client()
    resp = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" in resp.headers


# ---------------------------------------------------------------------------
# /api/v1/discover
# ---------------------------------------------------------------------------


def test_discover_returns_devices():
    client = _make_client()
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["ip"] == "192.168.1.100"
    assert data[0]["mac"] == "aa:bb:cc:dd:ee:ff"


def test_discover_subnet_param():
    seen_subnets = []

    def mock_discover(subnet):
        seen_subnets.append(subnet)
        return [_make_device()]

    client = _make_client(_discover_fn=mock_discover)
    resp = client.get("/api/v1/discover?subnet=10.0.0.0/24")
    assert resp.status_code == 200
    assert seen_subnets == ["10.0.0.0/24"]


def test_discover_error_returns_500():
    def failing_discover(subnet):
        raise RuntimeError("Network unreachable")

    client = _make_client(_discover_fn=failing_discover)
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 500
    assert "Network unreachable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /api/v1/ping/{host}
# ---------------------------------------------------------------------------


def test_ping_host():
    client = _make_client()
    resp = client.get("/api/v1/ping/8.8.8.8")
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"] == "8.8.8.8"
    assert data["is_alive"] is True
    assert "avg_latency_ms" in data


def test_ping_host_count_param():
    seen = {}

    def mock_ping(host, **kwargs):
        seen["count"] = kwargs.get("count")
        return _make_ping_result(host)

    client = _make_client(_ping_fn=mock_ping)
    resp = client.get("/api/v1/ping/8.8.8.8?count=10")
    assert resp.status_code == 200
    assert seen["count"] == 10


def test_ping_host_error():
    def failing_ping(host, **kwargs):
        raise RuntimeError("Ping failed")

    client = _make_client(_ping_fn=failing_ping)
    resp = client.get("/api/v1/ping/8.8.8.8")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /api/v1/ping/gateway
# ---------------------------------------------------------------------------


def test_ping_gateway():
    client = _make_client()
    resp = client.get("/api/v1/ping/gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"] == "192.168.1.1"
    assert data["is_alive"] is True


def test_ping_gateway_not_found():
    def failing_gateway():
        raise RuntimeError("Could not detect default gateway")

    client = _make_client(_gateway_fn=failing_gateway)
    resp = client.get("/api/v1/ping/gateway")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /api/v1/dns/health
# ---------------------------------------------------------------------------


def test_dns_health():
    client = _make_client()
    resp = client.get("/api/v1/dns/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "consistent" in data
    assert data["consistent"] is True
    assert "resolvers_checked" in data
    assert isinstance(data["details"], list)


# ---------------------------------------------------------------------------
# /api/v1/scan/{host}
# ---------------------------------------------------------------------------


def test_scan_host():
    client = _make_client()
    resp = client.get("/api/v1/scan/192.168.1.1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"] == "192.168.1.1"
    assert isinstance(data["ports"], list)
    assert data["ports"][0]["port"] == 80


def test_scan_host_ports_param():
    seen = {}

    def mock_scan(host, **kwargs):
        seen["ports"] = kwargs.get("ports")
        return _make_scan_result(host)

    client = _make_client(_scan_fn=mock_scan)
    resp = client.get("/api/v1/scan/192.168.1.1?ports=22,80,443")
    assert resp.status_code == 200
    assert seen["ports"] == "22,80,443"


# ---------------------------------------------------------------------------
# /api/v1/arp
# ---------------------------------------------------------------------------


def test_arp_table():
    client = _make_client()
    resp = client.get("/api/v1/arp")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert "alerts" in data
    assert isinstance(data["entries"], list)
    assert isinstance(data["alerts"], list)
    assert data["entries"][0]["ip"] == "192.168.1.1"


# ---------------------------------------------------------------------------
# /api/v1/tls/{host}
# ---------------------------------------------------------------------------


def test_tls_check():
    client = _make_client()
    resp = client.get("/api/v1/tls/example.com")
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"] == "example.com"
    assert data["is_trusted"] is True
    assert "cert" in data


def test_tls_check_port_param():
    seen = {}

    def mock_tls(host, **kwargs):
        seen["port"] = kwargs.get("port")
        return _make_tls_result(host)

    client = _make_client(_tls_fn=mock_tls)
    resp = client.get("/api/v1/tls/example.com?port=8443")
    assert resp.status_code == 200
    assert seen["port"] == 8443


# ---------------------------------------------------------------------------
# /api/v1/wifi
# ---------------------------------------------------------------------------


def test_wifi_scan():
    wifi_data = {
        "current": {"ssid": "TestNet", "bssid": "aa:bb:cc:dd:ee:ff"},
        "networks": [],
    }
    client = _make_client(_wifi_fn=lambda: wifi_data)
    resp = client.get("/api/v1/wifi")
    assert resp.status_code == 200
    data = resp.json()
    assert "current" in data
    assert "networks" in data


def test_wifi_scan_runtime_error():
    def failing_wifi():
        raise RuntimeError("WiFi not available")

    client = _make_client(_wifi_fn=failing_wifi)
    resp = client.get("/api/v1/wifi")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /api/v1/report
# ---------------------------------------------------------------------------


def test_full_report():
    client = _make_client()
    resp = client.get("/api/v1/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)


def test_full_report_subnet_param():
    seen = {}

    def mock_report(**kwargs):
        seen["subnet"] = kwargs.get("subnet")
        return _make_health_report()

    client = _make_client(_report_fn=mock_report)
    resp = client.get("/api/v1/report?subnet=10.0.0.0/16")
    assert resp.status_code == 200
    assert seen["subnet"] == "10.0.0.0/16"


# ---------------------------------------------------------------------------
# /api/v1/speed
# ---------------------------------------------------------------------------


def test_speed_test():
    client = _make_client()
    resp = client.get("/api/v1/speed")
    assert resp.status_code == 200
    data = resp.json()
    assert "download_mbps" in data
    assert "upload_mbps" in data
    assert "latency_ms" in data
    assert data["download_mbps"] == 150.0


def test_speed_test_provider_param():
    seen = {}

    def mock_speed(**kwargs):
        seen["provider"] = kwargs.get("provider")
        return _make_speed_result()

    client = _make_client(_speed_fn=mock_speed)
    resp = client.get("/api/v1/speed?provider=ookla")
    assert resp.status_code == 200
    assert seen["provider"] == "ookla"


# ---------------------------------------------------------------------------
# /api/v1/vpn
# ---------------------------------------------------------------------------


def test_vpn_check():
    client = _make_client()
    resp = client.get("/api/v1/vpn")
    assert resp.status_code == 200
    data = resp.json()
    assert "vpn_detected" in data
    assert "dns_leak" in data
    assert "ipv6_leak" in data


# ---------------------------------------------------------------------------
# /api/v1/uptime/{host}
# ---------------------------------------------------------------------------


def test_uptime_summary():
    client = _make_client()
    resp = client.get("/api/v1/uptime/8.8.8.8")
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"] == "8.8.8.8"
    assert "uptime_pct" in data
    assert data["uptime_pct"] == 99.9


def test_uptime_period_param():
    seen = {}

    def mock_uptime(host, **kwargs):
        seen["period"] = kwargs.get("period")
        return _make_uptime_summary(host)

    client = _make_client(_uptime_fn=mock_uptime)
    resp = client.get("/api/v1/uptime/8.8.8.8?period=7d")
    assert resp.status_code == 200
    assert seen["period"] == "7d"


# ---------------------------------------------------------------------------
# /api/v1/perf/{host}
# ---------------------------------------------------------------------------


def test_perf_check():
    client = _make_client()
    resp = client.get("/api/v1/perf/8.8.8.8")
    assert resp.status_code == 200
    data = resp.json()
    assert data["target"] == "8.8.8.8"
    assert "avg_latency_ms" in data
    assert "jitter_ms" in data


# ---------------------------------------------------------------------------
# /api/v1/baseline
# ---------------------------------------------------------------------------


def test_get_baseline_not_found(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/baseline")
    assert resp.status_code == 404


def test_get_baseline_returns_data(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    store.save_baseline(
        {"devices": [{"ip": "192.168.1.1"}], "arp_table": []},
        label="test",
    )
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/baseline")
    assert resp.status_code == 200
    data = resp.json()
    assert "devices" in data


def test_get_baseline_with_fn():
    client = _make_client(_baseline_fn=lambda: {"devices": [], "arp_table": []})
    resp = client.get("/api/v1/baseline")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/v1/baselines
# ---------------------------------------------------------------------------


def test_list_baselines_empty(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/baselines")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_baselines_with_data(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    store.save_baseline({"devices": []}, label="baseline-1")
    store.save_baseline({"devices": []}, label="baseline-2")

    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/baselines")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert any(b["label"] == "baseline-1" for b in data)


# ---------------------------------------------------------------------------
# /api/v1/devices
# ---------------------------------------------------------------------------


def test_devices_empty_when_no_baseline(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_devices_from_baseline(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    store.save_baseline(
        {"devices": [{"ip": "192.168.1.50", "mac": "de:ad:be:ef:00:01"}]},
        label="test",
    )
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ip"] == "192.168.1.50"


# ---------------------------------------------------------------------------
# /api/v1/metrics
# ---------------------------------------------------------------------------


def test_metrics_empty(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/metrics?metric=ping.latency&period=24h")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metric"] == "ping.latency"
    assert data["series"] == []


def test_metrics_with_data(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    store.save_metric("ping.latency", 5.5)
    store.save_metric("ping.latency", 6.0)

    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/metrics?metric=ping.latency&period=24h")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2


def test_metrics_invalid_period(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/metrics?metric=ping.latency&period=badformat")
    assert resp.status_code == 400


def test_metrics_list_empty(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/metrics/list")
    assert resp.status_code == 200
    assert resp.json() == []


def test_metrics_list_with_data(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    store.save_metric("ping.latency", 5.0)
    store.save_metric("download.speed", 100.0)

    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/metrics/list")
    assert resp.status_code == 200
    names = resp.json()
    assert "ping.latency" in names
    assert "download.speed" in names


# ---------------------------------------------------------------------------
# /api/v1/alerts
# ---------------------------------------------------------------------------


def test_alerts_empty(tmp_db):
    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_alerts_with_data(tmp_db):
    store = Store(db_path=tmp_db)
    store.init_db()
    # Insert a rule first (alert_log has FK to rule_id)
    store.conn.execute(
        "INSERT INTO alert_rules (metric, condition, threshold, window_s, message) "
        "VALUES (?, ?, ?, ?, ?)",
        ("ping.latency", "gt", 100.0, 300, "High latency"),
    )
    rule_id = store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    store.conn.execute(
        "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-01-01T12:00:00", rule_id, "ping.latency", 150.0, 100.0, "Latency spike"),
    )
    store.conn.commit()

    client = _make_client(tmp_db=tmp_db)
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["metric"] == "ping.latency"
    assert data[0]["value"] == 150.0
    assert data[0]["acknowledged"] is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_serve_help():
    from typer.testing import CliRunner
    from netglance.cli.api import app as api_cli_app

    runner = CliRunner()
    result = runner.invoke(api_cli_app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.output.lower() or "host" in result.output.lower()


def test_cli_app_help():
    from typer.testing import CliRunner
    from netglance.cli.api import app as api_cli_app

    runner = CliRunner()
    result = runner.invoke(api_cli_app, ["--help"])
    assert result.exit_code == 0


def test_cli_serve_missing_uvicorn():
    """Test that missing uvicorn produces a helpful error."""
    from typer.testing import CliRunner
    from netglance.cli.api import app as api_cli_app
    import sys

    runner = CliRunner()

    # Temporarily hide uvicorn
    uvicorn_module = sys.modules.pop("uvicorn", None)
    try:
        with patch.dict("sys.modules", {"uvicorn": None}):
            result = runner.invoke(api_cli_app, ["serve"])
            # Should exit with error about missing uvicorn
            assert result.exit_code != 0 or "uvicorn" in result.output.lower()
    finally:
        if uvicorn_module is not None:
            sys.modules["uvicorn"] = uvicorn_module


# ---------------------------------------------------------------------------
# create_app factory tests
# ---------------------------------------------------------------------------


def test_create_app_returns_fastapi():
    from fastapi import FastAPI

    app = create_app()
    assert isinstance(app, FastAPI)


def test_create_app_title():
    from fastapi import FastAPI

    app = create_app()
    assert "netglance" in app.title.lower()


def test_app_has_openapi():
    client = _make_client()
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    assert "/api/v1/health" in schema["paths"]


def test_all_routes_registered():
    client = _make_client()
    resp = client.get("/openapi.json")
    schema = resp.json()
    paths = schema["paths"]

    expected = [
        "/api/v1/health",
        "/api/v1/discover",
        "/api/v1/ping/gateway",
        "/api/v1/dns/health",
        "/api/v1/arp",
        "/api/v1/wifi",
        "/api/v1/report",
        "/api/v1/speed",
        "/api/v1/vpn",
        "/api/v1/baseline",
        "/api/v1/baselines",
        "/api/v1/devices",
        "/api/v1/metrics/list",
        "/api/v1/metrics",
        "/api/v1/alerts",
    ]

    for path in expected:
        assert path in paths, f"Route {path!r} not found in OpenAPI schema"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_error_handling_discover():
    def boom(subnet):
        raise ValueError("Bad subnet")

    client = _make_client(_discover_fn=boom)
    resp = client.get("/api/v1/discover")
    assert resp.status_code == 500
    assert "Bad subnet" in resp.json()["detail"]


def test_error_handling_scan():
    def boom(host, **kw):
        raise ConnectionError("Scan timed out")

    client = _make_client(_scan_fn=boom)
    resp = client.get("/api/v1/scan/192.168.1.1")
    assert resp.status_code == 500


def test_not_found_route():
    client = _make_client()
    resp = client.get("/api/v1/nonexistent")
    assert resp.status_code == 404
