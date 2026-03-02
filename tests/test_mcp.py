"""Tests for the MCP server module — all network I/O is mocked."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from netglance.cli.main import app
from netglance.mcp_server import _period_to_since, _to_dict, create_mcp_server
from netglance.store.db import Store
from netglance.store.models import (
    ArpAlert,
    ArpEntry,
    CertInfo,
    CheckStatus,
    Device,
    DeviceFingerprint,
    DeviceProfile,
    DhcpEvent,
    DnsHealthReport,
    DnsResolverResult,
    FirewallAuditReport,
    HealthReport,
    Hop,
    HostScanResult,
    HttpProbeResult,
    IoTAuditReport,
    IPv6AuditResult,
    NetworkBaseline,
    NetworkPerformanceResult,
    NetworkTopology,
    PingResult,
    PortResult,
    SpeedTestResult,
    TlsCheckResult,
    TraceResult,
    UptimeSummary,
    VpnLeakReport,
    WifiNetwork,
    WolResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_tool(mcp, tool_name: str, params: dict) -> Any:
    """Run an MCP tool by name and return the structured result.

    FastMCP wraps list returns in {"result": [...]}, while dict returns are
    returned directly as the structured_content dict.
    """
    tools = await mcp._tool_manager.get_tools()
    result = await tools[tool_name].run(params)
    sc = result.structured_content
    if sc is None:
        return None
    # List results are wrapped in {"result": [...]}
    if isinstance(sc, dict) and list(sc.keys()) == ["result"]:
        return sc["result"]
    # Dict results are the structured_content itself
    return sc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path: Path) -> Store:
    """Return an in-memory Store backed by a temp file."""
    store = Store(db_path=tmp_path / "test.db")
    store.init_db()
    return store


@pytest.fixture()
def sample_device() -> Device:
    return Device(
        ip="192.168.1.10",
        mac="aa:bb:cc:dd:ee:ff",
        hostname="myhost.local",
        vendor="Apple Inc.",
    )


@pytest.fixture()
def sample_ping() -> PingResult:
    return PingResult(
        host="192.168.1.1",
        is_alive=True,
        avg_latency_ms=5.0,
        min_latency_ms=3.0,
        max_latency_ms=8.0,
        packet_loss=0.0,
    )


@pytest.fixture()
def sample_cert() -> CertInfo:
    return CertInfo(
        host="google.com",
        port=443,
        subject="google.com",
        issuer="Google Trust Services LLC",
        root_ca="Google Trust Services LLC",
        fingerprint_sha256="abcdef1234",
    )


@pytest.fixture()
def sample_tls(sample_cert: CertInfo) -> TlsCheckResult:
    return TlsCheckResult(
        host="google.com",
        cert=sample_cert,
        is_trusted=True,
        is_intercepted=False,
    )


@pytest.fixture()
def sample_health_report() -> HealthReport:
    return HealthReport(
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        overall_status="pass",
        checks=[
            CheckStatus(module="ping", status="pass", summary="OK"),
            CheckStatus(module="dns", status="warn", summary="Inconsistent"),
        ],
    )


# ---------------------------------------------------------------------------
# Serialisation helper tests
# ---------------------------------------------------------------------------


class TestToDict:
    def test_dataclass_converted(self, sample_device: Device) -> None:
        d = _to_dict(sample_device)
        assert isinstance(d, dict)
        assert d["ip"] == "192.168.1.10"
        assert d["mac"] == "aa:bb:cc:dd:ee:ff"
        assert d["hostname"] == "myhost.local"

    def test_datetime_converted_to_isoformat(self) -> None:
        dt = datetime(2026, 2, 18, 12, 0, 0)
        assert _to_dict(dt) == "2026-02-18T12:00:00"

    def test_nested_dataclass(self, sample_tls: TlsCheckResult) -> None:
        d = _to_dict(sample_tls)
        assert isinstance(d, dict)
        assert "cert" in d
        assert isinstance(d["cert"], dict)
        assert d["cert"]["host"] == "google.com"

    def test_list_of_dataclasses(self, sample_device: Device) -> None:
        result = _to_dict([sample_device, sample_device])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(x, dict) for x in result)

    def test_passthrough_primitives(self) -> None:
        assert _to_dict(42) == 42
        assert _to_dict("hello") == "hello"
        assert _to_dict(None) is None

    def test_dict_of_dicts(self) -> None:
        d = _to_dict({"a": 1, "b": {"c": 2}})
        assert d == {"a": 1, "b": {"c": 2}}


class TestPeriodToSince:
    def test_hours(self) -> None:
        since = _period_to_since("24h")
        now = datetime.now(timezone.utc)
        diff = (now - since).total_seconds()
        assert 23 * 3600 < diff < 25 * 3600

    def test_days(self) -> None:
        since = _period_to_since("7d")
        now = datetime.now(timezone.utc)
        diff = (now - since).total_seconds()
        assert 6 * 86400 < diff < 8 * 86400

    def test_default_on_unrecognised(self) -> None:
        since = _period_to_since("invalid")
        now = datetime.now(timezone.utc)
        diff = (now - since).total_seconds()
        # Default is 24h
        assert 23 * 3600 < diff < 25 * 3600

    def test_1h(self) -> None:
        since = _period_to_since("1h")
        now = datetime.now(timezone.utc)
        diff = (now - since).total_seconds()
        assert 0 < diff < 3700


# ---------------------------------------------------------------------------
# create_mcp_server factory
# ---------------------------------------------------------------------------


class TestCreateMcpServer:
    def test_returns_fastmcp_instance(self) -> None:
        import fastmcp

        mcp = create_mcp_server()
        assert isinstance(mcp, fastmcp.FastMCP)

    def test_server_has_expected_tools(self) -> None:
        mcp = create_mcp_server()

        async def _get_tool_names():
            tools = await mcp._tool_manager.get_tools()
            return list(tools.keys())

        names = asyncio.run(_get_tool_names())
        expected = [
            "discover_devices",
            "check_connectivity",
            "check_dns_health",
            "scan_ports",
            "check_arp_table",
            "check_tls_certificates",
            "scan_wifi_environment",
            "run_health_check",
            "compare_to_baseline",
            "run_speed_test",
            "check_vpn_leaks",
            "identify_devices",
            "get_metrics",
            "get_alert_log",
            "check_http_headers",
            "trace_route",
            "check_dhcp",
            "audit_firewall",
            "check_ipv6",
            "assess_performance",
            "get_uptime_summary",
            "audit_iot_devices",
            "send_wake_on_lan",
            "get_network_topology",
            "get_server_capabilities",
        ]
        for tool in expected:
            assert tool in names, f"Expected tool '{tool}' not found in MCP server"

    def test_server_has_resources(self) -> None:
        mcp = create_mcp_server()

        async def _get_resource_uris():
            resources = await mcp._resource_manager.get_resources()
            return list(resources.keys())

        uris = asyncio.run(_get_resource_uris())
        assert "netglance://baseline/current" in uris
        assert "netglance://config" in uris
        assert "netglance://devices" in uris

    def test_tool_count(self) -> None:
        mcp = create_mcp_server()

        async def _count():
            tools = await mcp._tool_manager.get_tools()
            return len(tools)

        count = asyncio.run(_count())
        assert count >= 25


# ---------------------------------------------------------------------------
# Tool: discover_devices
# ---------------------------------------------------------------------------


class TestDiscoverDevicesTool:
    def test_returns_list_of_dicts(self, sample_device: Device) -> None:
        mock_discover = MagicMock(return_value=[sample_device])
        mcp = create_mcp_server(_discover_fn=mock_discover)

        result = asyncio.run(_run_tool(mcp, "discover_devices", {"subnet": "192.168.1.0/24"}))
        assert len(result) == 1
        assert result[0]["ip"] == "192.168.1.10"
        mock_discover.assert_called_once_with("192.168.1.0/24")

    def test_empty_network(self) -> None:
        mock_discover = MagicMock(return_value=[])
        mcp = create_mcp_server(_discover_fn=mock_discover)

        result = asyncio.run(_run_tool(mcp, "discover_devices", {"subnet": "10.0.0.0/24"}))
        assert result == []

    def test_multiple_devices(self) -> None:
        devices = [
            Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01"),
            Device(ip="192.168.1.2", mac="aa:bb:cc:dd:ee:02"),
            Device(ip="192.168.1.3", mac="aa:bb:cc:dd:ee:03"),
        ]
        mock_discover = MagicMock(return_value=devices)
        mcp = create_mcp_server(_discover_fn=mock_discover)

        result = asyncio.run(_run_tool(mcp, "discover_devices", {"subnet": "192.168.1.0/24"}))
        assert len(result) == 3
        assert result[1]["ip"] == "192.168.1.2"


# ---------------------------------------------------------------------------
# Tool: check_connectivity
# ---------------------------------------------------------------------------


class TestCheckConnectivityTool:
    def test_gateway_and_internet(self, sample_ping: PingResult) -> None:
        mock_gw = MagicMock(return_value=sample_ping)
        internet_results = [
            PingResult(host="1.1.1.1", is_alive=True, avg_latency_ms=10.0),
            PingResult(host="8.8.8.8", is_alive=True, avg_latency_ms=12.0),
        ]
        mock_internet = MagicMock(return_value=internet_results)
        mcp = create_mcp_server(
            _ping_gateway_fn=mock_gw,
            _ping_internet_fn=mock_internet,
        )

        result = asyncio.run(_run_tool(mcp, "check_connectivity", {"count": 4}))
        assert "gateway" in result
        assert "internet" in result
        assert result["gateway"]["host"] == "192.168.1.1"
        assert len(result["internet"]) == 2

    def test_gateway_error_returns_error_dict(self) -> None:
        mock_gw = MagicMock(side_effect=RuntimeError("No gateway detected"))
        mock_internet = MagicMock(return_value=[])
        mcp = create_mcp_server(
            _ping_gateway_fn=mock_gw,
            _ping_internet_fn=mock_internet,
        )

        result = asyncio.run(_run_tool(mcp, "check_connectivity", {"count": 4}))
        assert "error" in result["gateway"]
        assert "No gateway detected" in result["gateway"]["error"]

    def test_custom_hosts(self, sample_ping: PingResult) -> None:
        mock_gw = MagicMock(return_value=sample_ping)
        mock_internet = MagicMock(return_value=[])
        mock_host = MagicMock(return_value=PingResult(host="example.com", is_alive=True))
        mcp = create_mcp_server(
            _ping_gateway_fn=mock_gw,
            _ping_internet_fn=mock_internet,
            _ping_host_fn=mock_host,
        )

        result = asyncio.run(
            _run_tool(mcp, "check_connectivity", {"hosts": ["example.com"], "count": 2})
        )
        assert "custom" in result
        assert result["custom"][0]["host"] == "example.com"

    def test_no_custom_hosts_no_custom_key(self, sample_ping: PingResult) -> None:
        mock_gw = MagicMock(return_value=sample_ping)
        mock_internet = MagicMock(return_value=[])
        mcp = create_mcp_server(
            _ping_gateway_fn=mock_gw,
            _ping_internet_fn=mock_internet,
        )

        result = asyncio.run(_run_tool(mcp, "check_connectivity", {"count": 2}))
        assert "custom" not in result


# ---------------------------------------------------------------------------
# Tool: check_dns_health
# ---------------------------------------------------------------------------


class TestCheckDnsHealthTool:
    def test_returns_report_dict(self) -> None:
        report = DnsHealthReport(
            resolvers_checked=3,
            consistent=True,
            fastest_resolver="1.1.1.1",
            potential_hijack=False,
        )
        mock_dns = MagicMock(return_value=report)
        mcp = create_mcp_server(_dns_fn=mock_dns)

        result = asyncio.run(_run_tool(mcp, "check_dns_health", {"domain": "example.com"}))
        assert result["consistent"] is True
        assert result["fastest_resolver"] == "1.1.1.1"
        assert result["potential_hijack"] is False
        mock_dns.assert_called_once_with("example.com")

    def test_potential_hijack(self) -> None:
        report = DnsHealthReport(
            resolvers_checked=2,
            consistent=False,
            potential_hijack=True,
        )
        mock_dns = MagicMock(return_value=report)
        mcp = create_mcp_server(_dns_fn=mock_dns)

        result = asyncio.run(_run_tool(mcp, "check_dns_health", {"domain": "example.com"}))
        assert result["potential_hijack"] is True
        assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Tool: scan_ports
# ---------------------------------------------------------------------------


class TestScanPortsTool:
    def test_returns_scan_result(self) -> None:
        scan_result = HostScanResult(
            host="192.168.1.10",
            ports=[PortResult(port=22, state="open", service="ssh")],
        )
        mock_scan = MagicMock(return_value=scan_result)
        mcp = create_mcp_server(_scan_fn=mock_scan)

        result = asyncio.run(
            _run_tool(mcp, "scan_ports", {"host": "192.168.1.10", "ports": "1-1024"})
        )
        assert result["host"] == "192.168.1.10"
        assert result["ports"][0]["port"] == 22
        assert result["ports"][0]["state"] == "open"
        mock_scan.assert_called_once_with("192.168.1.10", ports="1-1024")

    def test_no_open_ports(self) -> None:
        scan_result = HostScanResult(host="10.0.0.1", ports=[])
        mock_scan = MagicMock(return_value=scan_result)
        mcp = create_mcp_server(_scan_fn=mock_scan)

        result = asyncio.run(
            _run_tool(mcp, "scan_ports", {"host": "10.0.0.1", "ports": "1-100"})
        )
        assert result["ports"] == []


# ---------------------------------------------------------------------------
# Tool: check_arp_table
# ---------------------------------------------------------------------------


class TestCheckArpTableTool:
    def test_returns_entries_and_alerts(self) -> None:
        entries = [ArpEntry(ip="192.168.1.1", mac="de:ad:be:ef:00:01", interface="en0")]
        alerts = [
            ArpAlert(
                alert_type="duplicate_ip",
                severity="warning",
                description="Duplicate IP detected",
            )
        ]
        mock_table = MagicMock(return_value=entries)
        mock_anomalies = MagicMock(return_value=alerts)
        mcp = create_mcp_server(
            _arp_table_fn=mock_table,
            _arp_anomalies_fn=mock_anomalies,
        )

        result = asyncio.run(_run_tool(mcp, "check_arp_table", {}))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["ip"] == "192.168.1.1"
        assert len(result["alerts"]) == 1
        assert result["alerts"][0]["alert_type"] == "duplicate_ip"

    def test_no_alerts(self) -> None:
        mock_table = MagicMock(return_value=[])
        mock_anomalies = MagicMock(return_value=[])
        mcp = create_mcp_server(
            _arp_table_fn=mock_table,
            _arp_anomalies_fn=mock_anomalies,
        )

        result = asyncio.run(_run_tool(mcp, "check_arp_table", {}))
        assert result["entries"] == []
        assert result["alerts"] == []

    def test_anomalies_called_with_entries(self) -> None:
        entries = [ArpEntry(ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")]
        mock_table = MagicMock(return_value=entries)
        mock_anomalies = MagicMock(return_value=[])
        mcp = create_mcp_server(
            _arp_table_fn=mock_table,
            _arp_anomalies_fn=mock_anomalies,
        )

        asyncio.run(_run_tool(mcp, "check_arp_table", {}))
        mock_anomalies.assert_called_once_with(entries)


# ---------------------------------------------------------------------------
# Tool: check_tls_certificates
# ---------------------------------------------------------------------------


class TestCheckTlsCertificatesTool:
    def test_returns_list_of_results(self, sample_tls: TlsCheckResult) -> None:
        mock_tls = MagicMock(return_value=[sample_tls])
        mcp = create_mcp_server(_tls_fn=mock_tls)

        result = asyncio.run(_run_tool(mcp, "check_tls_certificates", {}))
        assert len(result) == 1
        assert result[0]["host"] == "google.com"
        assert result[0]["is_trusted"] is True

    def test_default_hosts_when_none(self, sample_tls: TlsCheckResult) -> None:
        mock_tls = MagicMock(return_value=[sample_tls])
        mcp = create_mcp_server(_tls_fn=mock_tls)

        asyncio.run(_run_tool(mcp, "check_tls_certificates", {}))
        # Called with no args → uses defaults inside tls module
        mock_tls.assert_called_once_with()

    def test_custom_hosts_passed_through(self, sample_tls: TlsCheckResult) -> None:
        mock_tls = MagicMock(return_value=[sample_tls])
        mcp = create_mcp_server(_tls_fn=mock_tls)

        asyncio.run(_run_tool(mcp, "check_tls_certificates", {"hosts": ["myserver.com"]}))
        mock_tls.assert_called_once_with(["myserver.com"])

    def test_intercepted_cert(self, sample_cert: CertInfo) -> None:
        intercepted = TlsCheckResult(
            host="evil.example.com",
            cert=sample_cert,
            is_trusted=False,
            is_intercepted=True,
            details="Root CA not trusted",
        )
        mock_tls = MagicMock(return_value=[intercepted])
        mcp = create_mcp_server(_tls_fn=mock_tls)

        result = asyncio.run(_run_tool(mcp, "check_tls_certificates", {}))
        assert result[0]["is_intercepted"] is True
        assert result[0]["is_trusted"] is False


# ---------------------------------------------------------------------------
# Tool: scan_wifi_environment
# ---------------------------------------------------------------------------


class TestScanWifiEnvironmentTool:
    def test_returns_networks_and_channels(self) -> None:
        networks = [
            WifiNetwork(
                ssid="HomeNet",
                bssid="aa:bb:cc:dd:ee:ff",
                channel=6,
                band="2.4 GHz",
                signal_dbm=-55,
                security="WPA2",
            )
        ]
        channel_info = {"2.4ghz": {"6": 1}, "5ghz": {}}
        mock_scan = MagicMock(return_value=networks)
        mock_channel = MagicMock(return_value=channel_info)
        mcp = create_mcp_server(
            _wifi_scan_fn=mock_scan,
            _wifi_channel_fn=mock_channel,
        )

        result = asyncio.run(_run_tool(mcp, "scan_wifi_environment", {}))
        assert len(result["networks"]) == 1
        assert result["networks"][0]["ssid"] == "HomeNet"
        assert "2.4ghz" in result["channel_analysis"]

    def test_channel_utilization_called_with_networks(self) -> None:
        networks = [WifiNetwork(ssid="Test", bssid="00:00:00:00:00:00")]
        mock_scan = MagicMock(return_value=networks)
        mock_channel = MagicMock(return_value={})
        mcp = create_mcp_server(
            _wifi_scan_fn=mock_scan,
            _wifi_channel_fn=mock_channel,
        )

        asyncio.run(_run_tool(mcp, "scan_wifi_environment", {}))
        mock_channel.assert_called_once_with(networks)


# ---------------------------------------------------------------------------
# Tool: run_health_check
# ---------------------------------------------------------------------------


class TestRunHealthCheckTool:
    def test_returns_health_report(self, sample_health_report: HealthReport) -> None:
        mock_report = MagicMock(return_value=sample_health_report)
        mcp = create_mcp_server(_report_fn=mock_report)

        result = asyncio.run(_run_tool(mcp, "run_health_check", {"subnet": "192.168.1.0/24"}))
        assert result["overall_status"] == "pass"
        assert len(result["checks"]) == 2
        assert result["checks"][0]["module"] == "ping"
        mock_report.assert_called_once_with(subnet="192.168.1.0/24")

    def test_fail_status_propagated(self) -> None:
        report = HealthReport(
            timestamp=datetime.now(),
            overall_status="fail",
            checks=[CheckStatus(module="tls", status="fail", summary="MITM detected")],
        )
        mock_report = MagicMock(return_value=report)
        mcp = create_mcp_server(_report_fn=mock_report)

        result = asyncio.run(_run_tool(mcp, "run_health_check", {"subnet": "192.168.1.0/24"}))
        assert result["overall_status"] == "fail"


# ---------------------------------------------------------------------------
# Tool: compare_to_baseline
# ---------------------------------------------------------------------------


class TestCompareToBaselineTool:
    def test_no_baseline_returns_error(self, tmp_store: Store) -> None:
        mock_capture = MagicMock()
        mock_load = MagicMock(return_value=None)
        mock_diff = MagicMock()
        mcp = create_mcp_server(
            _baseline_capture_fn=mock_capture,
            _baseline_load_fn=mock_load,
            _baseline_diff_fn=mock_diff,
            _store=tmp_store,
        )

        result = asyncio.run(_run_tool(mcp, "compare_to_baseline", {}))
        assert "error" in result
        assert "No baseline found" in result["error"]

    def test_with_baseline_returns_diff(self, tmp_store: Store) -> None:
        baseline = MagicMock()
        diff_result = {"new_devices": [], "missing_devices": [], "changes": []}
        mock_capture = MagicMock(return_value=baseline)
        mock_load = MagicMock(return_value=baseline)
        mock_diff = MagicMock(return_value=diff_result)
        mcp = create_mcp_server(
            _baseline_capture_fn=mock_capture,
            _baseline_load_fn=mock_load,
            _baseline_diff_fn=mock_diff,
            _store=tmp_store,
        )

        result = asyncio.run(_run_tool(mcp, "compare_to_baseline", {}))
        assert "new_devices" in result
        assert "missing_devices" in result


# ---------------------------------------------------------------------------
# Tool: run_speed_test
# ---------------------------------------------------------------------------


class TestRunSpeedTestTool:
    def test_returns_speed_result(self) -> None:
        speed_result = SpeedTestResult(
            download_mbps=150.0,
            upload_mbps=30.0,
            latency_ms=12.0,
            provider="cloudflare",
        )
        mock_speed = MagicMock(return_value=speed_result)
        mcp = create_mcp_server(_speed_fn=mock_speed)

        result = asyncio.run(_run_tool(mcp, "run_speed_test", {"provider": "cloudflare"}))
        assert result["download_mbps"] == 150.0
        assert result["upload_mbps"] == 30.0
        assert result["latency_ms"] == 12.0
        mock_speed.assert_called_once_with(provider="cloudflare")

    def test_ookla_provider(self) -> None:
        speed_result = SpeedTestResult(
            download_mbps=200.0,
            upload_mbps=50.0,
            latency_ms=8.0,
            provider="ookla",
        )
        mock_speed = MagicMock(return_value=speed_result)
        mcp = create_mcp_server(_speed_fn=mock_speed)

        result = asyncio.run(_run_tool(mcp, "run_speed_test", {"provider": "ookla"}))
        assert result["provider"] == "ookla"
        mock_speed.assert_called_once_with(provider="ookla")


# ---------------------------------------------------------------------------
# Tool: check_vpn_leaks
# ---------------------------------------------------------------------------


class TestCheckVpnLeaksTool:
    def test_no_vpn_detected(self) -> None:
        report = VpnLeakReport(vpn_detected=False, dns_leak=False, ipv6_leak=False)
        mock_vpn = MagicMock(return_value=report)
        mcp = create_mcp_server(_vpn_fn=mock_vpn)

        result = asyncio.run(_run_tool(mcp, "check_vpn_leaks", {}))
        assert result["vpn_detected"] is False
        assert result["dns_leak"] is False

    def test_dns_leak_detected(self) -> None:
        report = VpnLeakReport(
            vpn_detected=True,
            dns_leak=True,
            dns_leak_resolvers=["8.8.8.8"],
        )
        mock_vpn = MagicMock(return_value=report)
        mcp = create_mcp_server(_vpn_fn=mock_vpn)

        result = asyncio.run(_run_tool(mcp, "check_vpn_leaks", {}))
        assert result["dns_leak"] is True
        assert "8.8.8.8" in result["dns_leak_resolvers"]

    def test_ipv6_leak_detected(self) -> None:
        report = VpnLeakReport(
            vpn_detected=True,
            ipv6_leak=True,
            ipv6_addresses=["2001:db8::1"],
        )
        mock_vpn = MagicMock(return_value=report)
        mcp = create_mcp_server(_vpn_fn=mock_vpn)

        result = asyncio.run(_run_tool(mcp, "check_vpn_leaks", {}))
        assert result["ipv6_leak"] is True


# ---------------------------------------------------------------------------
# Tool: identify_devices
# ---------------------------------------------------------------------------


class TestIdentifyDevicesTool:
    def test_returns_device_profiles(self) -> None:
        profile = DeviceProfile(
            ip="192.168.1.5",
            mac="11:22:33:44:55:66",
            device_type="smartphone",
            manufacturer="Apple",
            confidence=0.85,
        )
        mock_fingerprint = MagicMock(return_value=[profile])
        mcp = create_mcp_server(_fingerprint_fn=mock_fingerprint)

        result = asyncio.run(
            _run_tool(mcp, "identify_devices", {"subnet": "192.168.1.0/24"})
        )
        assert len(result) == 1
        assert result[0]["device_type"] == "smartphone"
        assert result[0]["manufacturer"] == "Apple"
        mock_fingerprint.assert_called_once_with("192.168.1.0/24")

    def test_empty_profile_list(self) -> None:
        mock_fingerprint = MagicMock(return_value=[])
        mcp = create_mcp_server(_fingerprint_fn=mock_fingerprint)

        result = asyncio.run(
            _run_tool(mcp, "identify_devices", {"subnet": "192.168.1.0/24"})
        )
        assert result == []


# ---------------------------------------------------------------------------
# Tool: get_metrics
# ---------------------------------------------------------------------------


class TestGetMetricsTool:
    def test_returns_metrics_data(self, tmp_store: Store) -> None:
        tmp_store.save_metric("download_mbps", 150.0)
        tmp_store.save_metric("download_mbps", 120.0)
        mcp = create_mcp_server(_store=tmp_store)

        result = asyncio.run(
            _run_tool(mcp, "get_metrics", {"metric": "download_mbps", "period": "24h"})
        )
        assert result["metric"] == "download_mbps"
        assert result["period"] == "24h"
        assert len(result["series"]) == 2
        assert "stats" in result
        assert result["stats"]["count"] == 2

    def test_empty_metric(self, tmp_store: Store) -> None:
        mcp = create_mcp_server(_store=tmp_store)

        result = asyncio.run(
            _run_tool(mcp, "get_metrics", {"metric": "nonexistent", "period": "1h"})
        )
        assert result["series"] == []
        assert result["stats"]["count"] == 0

    def test_stats_values(self, tmp_store: Store) -> None:
        tmp_store.save_metric("latency_ms", 10.0)
        tmp_store.save_metric("latency_ms", 20.0)
        tmp_store.save_metric("latency_ms", 30.0)
        mcp = create_mcp_server(_store=tmp_store)

        result = asyncio.run(
            _run_tool(mcp, "get_metrics", {"metric": "latency_ms", "period": "24h"})
        )
        assert result["stats"]["min"] == 10.0
        assert result["stats"]["max"] == 30.0
        assert result["stats"]["avg"] == 20.0


# ---------------------------------------------------------------------------
# Tool: get_alert_log
# ---------------------------------------------------------------------------


class TestGetAlertLogTool:
    def test_returns_alert_entries(self, tmp_store: Store) -> None:
        # Insert a fake alert log entry
        tmp_store.conn.execute(
            "INSERT INTO alert_rules (metric, condition, threshold, window_s, message) "
            "VALUES (?, ?, ?, ?, ?)",
            ("download_mbps", "lt", 25.0, 300, "Speed is low"),
        )
        rule_id = tmp_store.conn.execute(
            "SELECT last_insert_rowid() as id"
        ).fetchone()["id"]
        tmp_store.conn.execute(
            "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                rule_id,
                "download_mbps",
                10.0,
                25.0,
                "Speed is low",
            ),
        )
        tmp_store.conn.commit()
        mcp = create_mcp_server(_store=tmp_store)

        result = asyncio.run(_run_tool(mcp, "get_alert_log", {"hours": 24}))
        assert len(result) == 1
        assert result[0]["metric"] == "download_mbps"
        assert result[0]["value"] == 10.0

    def test_no_recent_alerts(self, tmp_store: Store) -> None:
        mcp = create_mcp_server(_store=tmp_store)

        result = asyncio.run(_run_tool(mcp, "get_alert_log", {"hours": 1}))
        assert result == []


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


async def _read_resource(mcp, uri: str) -> Any:
    """Read an MCP resource and return parsed JSON content."""
    resources = await mcp._resource_manager.get_resources()
    raw = await resources[uri].read()
    # Resources return a plain string in fastmcp 2.x
    return json.loads(raw)


class TestMcpResources:
    def test_baseline_resource_no_data(self, tmp_store: Store) -> None:
        mcp = create_mcp_server(_store=tmp_store)
        content = asyncio.run(_read_resource(mcp, "netglance://baseline/current"))
        assert "error" in content

    def test_baseline_resource_with_data(self, tmp_store: Store) -> None:
        tmp_store.save_baseline({"devices": ["192.168.1.1"]}, label="test")
        mcp = create_mcp_server(_store=tmp_store)
        content = asyncio.run(_read_resource(mcp, "netglance://baseline/current"))
        assert "devices" in content

    def test_devices_resource_no_data(self, tmp_store: Store) -> None:
        mcp = create_mcp_server(_store=tmp_store)
        content = asyncio.run(_read_resource(mcp, "netglance://devices"))
        assert "error" in content

    def test_devices_resource_with_data(self, tmp_store: Store) -> None:
        tmp_store.save_result("discover", {"devices": [{"ip": "192.168.1.10"}]})
        mcp = create_mcp_server(_store=tmp_store)
        content = asyncio.run(_read_resource(mcp, "netglance://devices"))
        assert "devices" in content

    def test_config_resource(self, tmp_store: Store) -> None:
        mcp = create_mcp_server(_store=tmp_store)
        # Should return something (either config or error), not raise
        content = asyncio.run(_read_resource(mcp, "netglance://config"))
        assert isinstance(content, dict)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

runner = CliRunner()


class TestMcpCliTools:
    def test_tools_command_lists_tools(self) -> None:
        result = runner.invoke(app, ["mcp", "tools"])
        assert result.exit_code == 0
        assert "discover_devices" in result.output

    def test_tools_command_json(self) -> None:
        result = runner.invoke(app, ["mcp", "tools", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        names = [t["name"] for t in data]
        assert "discover_devices" in names
        assert "check_connectivity" in names

    def test_tools_command_includes_all_expected(self) -> None:
        result = runner.invoke(app, ["mcp", "tools", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        names = [t["name"] for t in data]
        for expected in [
            "discover_devices",
            "check_connectivity",
            "check_dns_health",
            "scan_ports",
            "check_arp_table",
            "check_tls_certificates",
            "scan_wifi_environment",
            "run_health_check",
            "compare_to_baseline",
            "run_speed_test",
            "check_vpn_leaks",
            "identify_devices",
            "get_metrics",
            "get_alert_log",
            "check_http_headers",
            "trace_route",
            "check_dhcp",
            "audit_firewall",
            "check_ipv6",
            "assess_performance",
            "get_uptime_summary",
            "audit_iot_devices",
            "send_wake_on_lan",
            "get_network_topology",
            "get_server_capabilities",
        ]:
            assert expected in names, f"'{expected}' missing from mcp tools output"

    def test_serve_unknown_transport(self) -> None:
        result = runner.invoke(app, ["mcp", "serve", "--transport", "grpc"])
        assert result.exit_code == 1
        assert "Unknown transport" in result.output
        assert "stdio" in result.output or "http" in result.output

    def test_serve_sse_deprecation_warning(self) -> None:
        """SSE transport should show deprecation warning."""
        result = runner.invoke(app, ["mcp", "serve", "--transport", "sse"])
        # It will fail because no real server, but should print the warning before that
        assert "deprecated" in result.output.lower() or result.exit_code != 0

    def test_mcp_help(self) -> None:
        result = runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "tools" in result.output


# ---------------------------------------------------------------------------
# Tool: check_http_headers
# ---------------------------------------------------------------------------


class TestCheckHttpHeadersTool:
    def test_returns_probe_result(self) -> None:
        result = HttpProbeResult(
            url="http://example.com",
            status_code=200,
            suspicious_headers={},
            injected_content=False,
            proxy_detected=False,
        )
        mock_http = MagicMock(return_value=result)
        mcp = create_mcp_server(_http_fn=mock_http)
        data = asyncio.run(_run_tool(mcp, "check_http_headers", {"url": "http://example.com"}))
        assert data["url"] == "http://example.com"
        assert data["status_code"] == 200
        mock_http.assert_called_once_with("http://example.com")

    def test_proxy_detected(self) -> None:
        result = HttpProbeResult(
            url="http://example.com",
            status_code=200,
            suspicious_headers={"Via": "1.1 proxy.local"},
            injected_content=False,
            proxy_detected=True,
        )
        mock_http = MagicMock(return_value=result)
        mcp = create_mcp_server(_http_fn=mock_http)
        data = asyncio.run(_run_tool(mcp, "check_http_headers", {"url": "http://example.com"}))
        assert data["proxy_detected"] is True
        assert "Via" in data["suspicious_headers"]


# ---------------------------------------------------------------------------
# Tool: trace_route
# ---------------------------------------------------------------------------


class TestTraceRouteTool:
    def test_returns_trace(self) -> None:
        trace = TraceResult(
            destination="8.8.8.8",
            hops=[Hop(ttl=1, ip="192.168.1.1", rtt_ms=2.0)],
            reached=True,
        )
        mock_route = MagicMock(return_value=trace)
        mcp = create_mcp_server(_route_fn=mock_route)
        data = asyncio.run(_run_tool(mcp, "trace_route", {"host": "8.8.8.8"}))
        assert data["destination"] == "8.8.8.8"
        assert data["reached"] is True
        assert len(data["hops"]) == 1
        mock_route.assert_called_once_with("8.8.8.8", max_hops=30)

    def test_custom_max_hops(self) -> None:
        trace = TraceResult(destination="1.1.1.1", hops=[], reached=False)
        mock_route = MagicMock(return_value=trace)
        mcp = create_mcp_server(_route_fn=mock_route)
        asyncio.run(_run_tool(mcp, "trace_route", {"host": "1.1.1.1", "max_hops": 15}))
        mock_route.assert_called_once_with("1.1.1.1", max_hops=15)


# ---------------------------------------------------------------------------
# Tool: check_dhcp
# ---------------------------------------------------------------------------


class TestCheckDhcpTool:
    def test_returns_dhcp_events(self) -> None:
        event = DhcpEvent(
            event_type="offer",
            client_mac="aa:bb:cc:dd:ee:ff",
            client_ip="192.168.1.100",
            server_ip="192.168.1.1",
        )
        mock_dhcp = MagicMock(return_value=[event])
        mcp = create_mcp_server(_dhcp_fn=mock_dhcp)
        data = asyncio.run(_run_tool(mcp, "check_dhcp", {"timeout": 5.0}))
        assert len(data) == 1
        assert data[0]["event_type"] == "offer"
        assert data[0]["client_mac"] == "aa:bb:cc:dd:ee:ff"
        mock_dhcp.assert_called_once_with(timeout=5.0)

    def test_no_dhcp_events(self) -> None:
        mock_dhcp = MagicMock(return_value=[])
        mcp = create_mcp_server(_dhcp_fn=mock_dhcp)
        data = asyncio.run(_run_tool(mcp, "check_dhcp", {}))
        assert data == []


# ---------------------------------------------------------------------------
# Tool: audit_firewall
# ---------------------------------------------------------------------------


class TestAuditFirewallTool:
    def test_returns_audit_report(self) -> None:
        report = FirewallAuditReport(
            egress_results=[],
            ingress_results=[],
            blocked_egress_ports=[25, 587],
            open_ingress_ports=[],
            recommendations=["Consider allowing port 587 for email"],
        )
        mock_firewall = MagicMock(return_value=report)
        mcp = create_mcp_server(_firewall_fn=mock_firewall)
        data = asyncio.run(_run_tool(mcp, "audit_firewall", {}))
        assert "blocked_egress_ports" in data
        assert 25 in data["blocked_egress_ports"]
        mock_firewall.assert_called_once_with()

    def test_no_blocked_ports(self) -> None:
        report = FirewallAuditReport(blocked_egress_ports=[], open_ingress_ports=[])
        mock_firewall = MagicMock(return_value=report)
        mcp = create_mcp_server(_firewall_fn=mock_firewall)
        data = asyncio.run(_run_tool(mcp, "audit_firewall", {}))
        assert data["blocked_egress_ports"] == []


# ---------------------------------------------------------------------------
# Tool: check_ipv6
# ---------------------------------------------------------------------------


class TestCheckIpv6Tool:
    def test_returns_ipv6_audit(self) -> None:
        result = IPv6AuditResult(
            neighbors=[],
            local_addresses=[],
            privacy_extensions=True,
            eui64_exposed=False,
            dual_stack=True,
        )
        mock_ipv6 = MagicMock(return_value=result)
        mcp = create_mcp_server(_ipv6_fn=mock_ipv6)
        data = asyncio.run(_run_tool(mcp, "check_ipv6", {}))
        assert data["privacy_extensions"] is True
        assert data["dual_stack"] is True
        assert data["eui64_exposed"] is False
        mock_ipv6.assert_called_once_with()

    def test_eui64_exposed(self) -> None:
        result = IPv6AuditResult(eui64_exposed=True, ipv6_dns_leak=True)
        mock_ipv6 = MagicMock(return_value=result)
        mcp = create_mcp_server(_ipv6_fn=mock_ipv6)
        data = asyncio.run(_run_tool(mcp, "check_ipv6", {}))
        assert data["eui64_exposed"] is True
        assert data["ipv6_dns_leak"] is True


# ---------------------------------------------------------------------------
# Tool: assess_performance
# ---------------------------------------------------------------------------


class TestAssessPerformanceTool:
    def test_returns_performance_result(self) -> None:
        result = NetworkPerformanceResult(
            target="1.1.1.1",
            avg_latency_ms=12.5,
            jitter_ms=1.2,
            p95_latency_ms=18.0,
            p99_latency_ms=22.0,
            packet_loss_pct=0.0,
            path_mtu=1500,
            bufferbloat_rating="good",
        )
        mock_perf = MagicMock(return_value=result)
        mcp = create_mcp_server(_perf_fn=mock_perf)
        data = asyncio.run(_run_tool(mcp, "assess_performance", {"host": "1.1.1.1"}))
        assert data["target"] == "1.1.1.1"
        assert data["jitter_ms"] == 1.2
        assert data["path_mtu"] == 1500
        assert data["bufferbloat_rating"] == "good"
        mock_perf.assert_called_once_with("1.1.1.1")

    def test_high_packet_loss(self) -> None:
        result = NetworkPerformanceResult(
            target="10.0.0.1",
            avg_latency_ms=200.0,
            jitter_ms=50.0,
            p95_latency_ms=350.0,
            p99_latency_ms=400.0,
            packet_loss_pct=15.0,
        )
        mock_perf = MagicMock(return_value=result)
        mcp = create_mcp_server(_perf_fn=mock_perf)
        data = asyncio.run(_run_tool(mcp, "assess_performance", {"host": "10.0.0.1"}))
        assert data["packet_loss_pct"] == 15.0


# ---------------------------------------------------------------------------
# Tool: get_uptime_summary
# ---------------------------------------------------------------------------


class TestGetUptimeSummaryTool:
    def test_returns_uptime_summary(self) -> None:
        summary = UptimeSummary(
            host="192.168.1.1",
            period="24h",
            uptime_pct=99.5,
            total_checks=100,
            successful_checks=99,
        )
        mock_uptime = MagicMock(return_value=summary)
        mcp = create_mcp_server(_uptime_fn=mock_uptime)
        data = asyncio.run(
            _run_tool(mcp, "get_uptime_summary", {"host": "192.168.1.1", "period": "24h"})
        )
        assert data["host"] == "192.168.1.1"
        assert data["uptime_pct"] == 99.5
        assert data["total_checks"] == 100
        mock_uptime.assert_called_once_with("192.168.1.1", period="24h")

    def test_default_period(self) -> None:
        summary = UptimeSummary(
            host="10.0.0.1",
            period="24h",
            uptime_pct=100.0,
            total_checks=24,
            successful_checks=24,
        )
        mock_uptime = MagicMock(return_value=summary)
        mcp = create_mcp_server(_uptime_fn=mock_uptime)
        asyncio.run(_run_tool(mcp, "get_uptime_summary", {"host": "10.0.0.1"}))
        mock_uptime.assert_called_once_with("10.0.0.1", period="24h")


# ---------------------------------------------------------------------------
# Tool: audit_iot_devices
# ---------------------------------------------------------------------------


class TestAuditIotDevicesTool:
    def test_returns_iot_report(self) -> None:
        devices = [Device(ip="192.168.1.100", mac="aa:bb:cc:dd:ee:ff")]
        report = IoTAuditReport(
            devices=[],
            high_risk_count=0,
            total_issues=0,
            recommendations=[],
        )
        mock_discover = MagicMock(return_value=devices)
        mock_iot = MagicMock(return_value=report)
        mcp = create_mcp_server(_discover_fn=mock_discover, _iot_fn=mock_iot)
        data = asyncio.run(
            _run_tool(mcp, "audit_iot_devices", {"subnet": "192.168.1.0/24"})
        )
        assert "devices" in data
        assert "high_risk_count" in data
        mock_discover.assert_called_once_with("192.168.1.0/24")
        mock_iot.assert_called_once_with(devices)

    def test_no_iot_devices(self) -> None:
        report = IoTAuditReport(devices=[], high_risk_count=0, total_issues=0)
        mock_discover = MagicMock(return_value=[])
        mock_iot = MagicMock(return_value=report)
        mcp = create_mcp_server(_discover_fn=mock_discover, _iot_fn=mock_iot)
        data = asyncio.run(_run_tool(mcp, "audit_iot_devices", {}))
        assert data["high_risk_count"] == 0


# ---------------------------------------------------------------------------
# Tool: send_wake_on_lan
# ---------------------------------------------------------------------------


class TestSendWakeOnLanTool:
    def test_sends_wol(self) -> None:
        result = WolResult(
            mac="aa:bb:cc:dd:ee:ff",
            broadcast="255.255.255.255",
            port=9,
            sent=True,
        )
        mock_wol = MagicMock(return_value=result)
        mcp = create_mcp_server(_wol_fn=mock_wol)
        data = asyncio.run(
            _run_tool(mcp, "send_wake_on_lan", {"mac": "aa:bb:cc:dd:ee:ff"})
        )
        assert data["sent"] is True
        assert data["mac"] == "aa:bb:cc:dd:ee:ff"
        mock_wol.assert_called_once_with("aa:bb:cc:dd:ee:ff", broadcast="255.255.255.255")

    def test_custom_broadcast(self) -> None:
        result = WolResult(
            mac="11:22:33:44:55:66",
            broadcast="192.168.1.255",
            port=9,
            sent=True,
        )
        mock_wol = MagicMock(return_value=result)
        mcp = create_mcp_server(_wol_fn=mock_wol)
        asyncio.run(
            _run_tool(
                mcp,
                "send_wake_on_lan",
                {"mac": "11:22:33:44:55:66", "broadcast": "192.168.1.255"},
            )
        )
        mock_wol.assert_called_once_with("11:22:33:44:55:66", broadcast="192.168.1.255")


# ---------------------------------------------------------------------------
# Tool: get_network_topology
# ---------------------------------------------------------------------------


class TestGetNetworkTopologyTool:
    def test_returns_topology_with_ascii(self) -> None:
        devices = [Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01")]
        arp_entries = []
        topology = NetworkTopology(nodes=[], edges=[])
        mock_discover = MagicMock(return_value=devices)
        mock_arp = MagicMock(return_value=arp_entries)
        mock_topology = MagicMock(return_value=topology)
        mcp = create_mcp_server(
            _discover_fn=mock_discover,
            _arp_table_fn=mock_arp,
            _topology_fn=mock_topology,
        )
        data = asyncio.run(
            _run_tool(mcp, "get_network_topology", {"subnet": "192.168.1.0/24"})
        )
        assert "nodes" in data
        assert "edges" in data
        assert "ascii" in data
        mock_discover.assert_called_once_with("192.168.1.0/24")
        mock_arp.assert_called_once_with()
        mock_topology.assert_called_once_with(devices, arp_entries, [], None)

    def test_ascii_key_present(self) -> None:
        topology = NetworkTopology(nodes=[], edges=[])
        mock_discover = MagicMock(return_value=[])
        mock_arp = MagicMock(return_value=[])
        mock_topology = MagicMock(return_value=topology)
        mcp = create_mcp_server(
            _discover_fn=mock_discover,
            _arp_table_fn=mock_arp,
            _topology_fn=mock_topology,
        )
        data = asyncio.run(_run_tool(mcp, "get_network_topology", {}))
        assert isinstance(data["ascii"], str)


class TestMcpCliRegistered:
    def test_mcp_in_top_level_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "mcp" in result.output


# ---------------------------------------------------------------------------
# Entry point: main()
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    def test_main_exists_and_callable(self) -> None:
        from netglance.mcp_server import main
        assert callable(main)

    def test_main_calls_run_with_stdio(self) -> None:
        """main() should create a server and call mcp.run(transport='stdio')."""
        from unittest.mock import patch, MagicMock
        mock_server = MagicMock()
        with patch("netglance.mcp_server.create_mcp_server", return_value=mock_server):
            from netglance.mcp_server import main
            main()
            mock_server.run.assert_called_once_with(transport="stdio")


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------


class TestToolAnnotations:
    """Verify all tools have correct MCP annotations."""

    def _get_tool_annotations(self, mcp, tool_name: str) -> dict:
        """Get annotations for a specific tool as a plain dict."""
        async def _get():
            tools = await mcp._tool_manager.get_tools()
            tool = tools[tool_name]
            if hasattr(tool, "annotations") and tool.annotations is not None:
                if hasattr(tool.annotations, "model_dump"):
                    return tool.annotations.model_dump(exclude_none=True)
                elif isinstance(tool.annotations, dict):
                    return tool.annotations
            return {}
        return asyncio.run(_get())

    def test_readonly_tools_annotated(self) -> None:
        mcp = create_mcp_server()
        readonly_tools = [
            "discover_devices", "check_connectivity", "check_dns_health",
            "scan_ports", "check_arp_table", "check_tls_certificates",
            "scan_wifi_environment", "run_health_check", "run_speed_test",
            "check_vpn_leaks", "identify_devices", "get_metrics", "get_alert_log",
            "check_http_headers", "trace_route", "check_dhcp", "audit_firewall",
            "check_ipv6", "assess_performance", "get_uptime_summary",
            "audit_iot_devices", "get_network_topology", "get_server_capabilities",
        ]
        for name in readonly_tools:
            annot = self._get_tool_annotations(mcp, name)
            assert annot.get("readOnlyHint") is True, f"{name} should be readOnlyHint=True"

    def test_baseline_not_readonly(self) -> None:
        mcp = create_mcp_server()
        annot = self._get_tool_annotations(mcp, "compare_to_baseline")
        assert annot.get("readOnlyHint") is not True, "compare_to_baseline writes to DB"

    def test_openworld_tools_annotated(self) -> None:
        mcp = create_mcp_server()
        openworld_tools = [
            "discover_devices", "check_connectivity", "check_dns_health",
            "scan_ports", "check_tls_certificates", "run_health_check",
            "compare_to_baseline", "run_speed_test", "check_vpn_leaks",
            "identify_devices", "check_http_headers", "trace_route",
            "audit_firewall", "assess_performance", "audit_iot_devices",
            "get_network_topology",
        ]
        for name in openworld_tools:
            annot = self._get_tool_annotations(mcp, name)
            assert annot.get("openWorldHint") is True, f"{name} should be openWorldHint=True"

    def test_local_only_tools_not_openworld(self) -> None:
        mcp = create_mcp_server()
        local_tools = [
            "check_arp_table", "scan_wifi_environment", "get_metrics", "get_alert_log",
            "check_dhcp", "check_ipv6", "get_uptime_summary", "get_server_capabilities",
        ]
        for name in local_tools:
            annot = self._get_tool_annotations(mcp, name)
            assert annot.get("openWorldHint") is not True, f"{name} should NOT be openWorldHint"

    def test_wol_not_readonly(self) -> None:
        mcp = create_mcp_server()
        annot = self._get_tool_annotations(mcp, "send_wake_on_lan")
        assert annot.get("readOnlyHint") is not True, "send_wake_on_lan sends packets"

    def test_no_destructive_tools(self) -> None:
        mcp = create_mcp_server()
        all_tools = [
            "discover_devices", "check_connectivity", "check_dns_health",
            "scan_ports", "check_arp_table", "check_tls_certificates",
            "scan_wifi_environment", "run_health_check", "compare_to_baseline",
            "run_speed_test", "check_vpn_leaks", "identify_devices",
            "get_metrics", "get_alert_log", "check_http_headers", "trace_route",
            "check_dhcp", "audit_firewall", "check_ipv6", "assess_performance",
            "get_uptime_summary", "audit_iot_devices", "send_wake_on_lan",
            "get_network_topology", "get_server_capabilities",
        ]
        for name in all_tools:
            annot = self._get_tool_annotations(mcp, name)
            assert annot.get("destructiveHint") is not True, f"{name} should NOT be destructiveHint"


# ---------------------------------------------------------------------------
# Privilege degradation (PermissionError handling)
# ---------------------------------------------------------------------------


class TestPrivilegeDegradation:
    def test_discover_permission_error(self) -> None:
        mock_discover = MagicMock(side_effect=PermissionError("Need root"))
        mcp = create_mcp_server(_discover_fn=mock_discover)
        result = asyncio.run(_run_tool(mcp, "discover_devices", {"subnet": "192.168.1.0/24"}))
        assert len(result) == 1
        assert "error" in result[0]
        assert "elevated privileges" in result[0]["error"]

    def test_scan_ports_permission_error(self) -> None:
        mock_scan = MagicMock(side_effect=PermissionError("Need root"))
        mcp = create_mcp_server(_scan_fn=mock_scan)
        result = asyncio.run(_run_tool(mcp, "scan_ports", {"host": "192.168.1.1", "ports": "1-1024"}))
        assert "error" in result

    def test_check_dhcp_permission_error(self) -> None:
        mock_dhcp = MagicMock(side_effect=PermissionError("Need root"))
        mcp = create_mcp_server(_dhcp_fn=mock_dhcp)
        result = asyncio.run(_run_tool(mcp, "check_dhcp", {"timeout": 5.0}))
        assert len(result) == 1
        assert "error" in result[0]
        assert "elevated privileges" in result[0]["error"]

    def test_trace_route_permission_error(self) -> None:
        mock_route = MagicMock(side_effect=PermissionError("Need root"))
        mcp = create_mcp_server(_route_fn=mock_route)
        result = asyncio.run(_run_tool(mcp, "trace_route", {"host": "8.8.8.8"}))
        assert "error" in result
        assert "elevated privileges" in result["error"]


# ---------------------------------------------------------------------------
# Tool: get_server_capabilities
# ---------------------------------------------------------------------------


class TestGetServerCapabilitiesTool:
    def test_returns_capabilities_dict(self) -> None:
        mcp = create_mcp_server()
        result = asyncio.run(_run_tool(mcp, "get_server_capabilities", {}))
        assert "privileged" in result
        assert "version" in result
        assert "total_tools" in result
        assert "tools_needing_privileges" in result

    def test_reports_privilege_status(self) -> None:
        mcp = create_mcp_server()
        result = asyncio.run(_run_tool(mcp, "get_server_capabilities", {}))
        assert isinstance(result["privileged"], bool)
        # Tests run as non-root
        assert result["privileged"] is False

    def test_lists_privileged_tools(self) -> None:
        mcp = create_mcp_server()
        result = asyncio.run(_run_tool(mcp, "get_server_capabilities", {}))
        priv_tools = result["tools_needing_privileges"]
        assert "discover_devices" in priv_tools
        assert "scan_ports" in priv_tools
        assert "check_dhcp" in priv_tools
        assert "trace_route" in priv_tools
        for name, info in priv_tools.items():
            assert info["available"] is True
            assert info["privileged_mode"] is False
            assert info["note"] is not None  # Has explanation when non-root

    def test_version_matches_package(self) -> None:
        from netglance import __version__
        mcp = create_mcp_server()
        result = asyncio.run(_run_tool(mcp, "get_server_capabilities", {}))
        assert result["version"] == __version__


# ---------------------------------------------------------------------------
# CLI: mcp tools --verbose
# ---------------------------------------------------------------------------


class TestMcpCliToolsVerbose:
    def test_verbose_shows_annotations(self) -> None:
        result = runner.invoke(app, ["mcp", "tools", "--verbose"])
        assert result.exit_code == 0
        assert "RO" in result.output or "readOnly" in result.output.lower()

    def test_verbose_json_includes_annotations(self) -> None:
        result = runner.invoke(app, ["mcp", "tools", "--json", "--verbose"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "annotations" in data[0]

    def test_json_includes_annotations_key(self) -> None:
        result = runner.invoke(app, ["mcp", "tools", "--json", "--verbose"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        tool = next(t for t in data if t["name"] == "discover_devices")
        assert "readOnlyHint" in tool["annotations"]
