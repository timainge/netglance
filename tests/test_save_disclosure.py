"""Tests for --save/--no-save flags and disclosure messages across CLI modules."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.store.models import (
    ArpEntry,
    CertInfo,
    Device,
    DnsHealthReport,
    DnsResolverResult,
    HostScanResult,
    NetworkTopology,
    PingResult,
    PortResult,
    SpeedTestResult,
    TlsCheckResult,
    TopologyEdge,
    TopologyNode,
    WifiNetwork,
)

runner = CliRunner()

DISCLOSURE = "✓ Saved to local database."


# ---------------------------------------------------------------------------
# Helpers / mock factories
# ---------------------------------------------------------------------------

def _make_ping_result(host: str = "8.8.8.8") -> PingResult:
    return PingResult(
        host=host,
        is_alive=True,
        avg_latency_ms=10.0,
        min_latency_ms=8.0,
        max_latency_ms=12.0,
        packet_loss=0.0,
    )


def _make_scan_result(host: str = "192.168.1.1") -> HostScanResult:
    return HostScanResult(
        host=host,
        ports=[PortResult(port=22, state="open", service="ssh")],
        scan_duration_s=1.0,
    )


def _make_device() -> Device:
    return Device(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff", hostname="test-host")


def _make_trace_result():
    from netglance.store.models import Hop
    from netglance.modules.route import TraceResult

    return TraceResult(
        destination="8.8.8.8",
        hops=[Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0)],
        reached=True,
    )


def _make_speed_result() -> SpeedTestResult:
    return SpeedTestResult(
        download_mbps=100.0,
        upload_mbps=50.0,
        latency_ms=10.0,
        download_bytes=10_000_000,
        upload_bytes=5_000_000,
        server="speed.cloudflare.com",
        provider="cloudflare",
    )


def _make_topology() -> NetworkTopology:
    return NetworkTopology(
        nodes=[TopologyNode(id="gw", label="Gateway", node_type="gateway", ip="192.168.1.1")],
        edges=[],
    )


def _make_dns_report() -> DnsHealthReport:
    return DnsHealthReport(
        resolvers_checked=4,
        consistent=True,
        fastest_resolver="1.1.1.1",
        dnssec_supported=True,
        potential_hijack=False,
        details=[],
    )


def _make_tls_result(host: str = "example.com") -> TlsCheckResult:
    cert = CertInfo(host=host, issuer="Let's Encrypt", root_ca="ISRG Root X1", fingerprint_sha256="abc123")
    return TlsCheckResult(host=host, cert=cert, is_trusted=True, is_intercepted=False)


def _make_wifi_network() -> WifiNetwork:
    return WifiNetwork(
        ssid="TestNet",
        bssid="aa:bb:cc:dd:ee:ff",
        channel=6,
        band="2.4 GHz",
        signal_dbm=-50,
        security="WPA2",
    )


def _make_arp_entry() -> ArpEntry:
    return ArpEntry(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:ff", interface="en0")


# ===========================================================================
# ping module tests
# ===========================================================================


class TestPingSaveDisclosure:
    """Tests for --save/--no-save on ping host, internet, gateway commands."""

    @patch("netglance.cli.ping.emit_ping_metrics")
    @patch("netglance.cli.ping.Store")
    @patch("netglance.cli.ping.ping_host")
    def test_ping_host_save(self, mock_ping, mock_store_cls, mock_emit):
        from netglance.cli.ping import app

        mock_ping.return_value = _make_ping_result()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["host", "8.8.8.8", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()
        mock_emit.assert_called_once()

    @patch("netglance.cli.ping.ping_host")
    def test_ping_host_no_save_default(self, mock_ping):
        from netglance.cli.ping import app

        mock_ping.return_value = _make_ping_result()

        result = runner.invoke(app, ["host", "8.8.8.8"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.ping.ping_host")
    def test_ping_host_no_save_explicit(self, mock_ping):
        from netglance.cli.ping import app

        mock_ping.return_value = _make_ping_result()

        result = runner.invoke(app, ["host", "8.8.8.8", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.ping.emit_ping_metrics")
    @patch("netglance.cli.ping.Store")
    @patch("netglance.cli.ping.check_internet")
    def test_ping_internet_save(self, mock_check, mock_store_cls, mock_emit):
        from netglance.cli.ping import app

        mock_check.return_value = [_make_ping_result("1.1.1.1"), _make_ping_result("8.8.8.8")]
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["internet", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        assert mock_store.save_result.call_count == 2
        assert mock_emit.call_count == 2

    @patch("netglance.cli.ping.check_internet")
    def test_ping_internet_no_save(self, mock_check):
        from netglance.cli.ping import app

        mock_check.return_value = [_make_ping_result()]

        result = runner.invoke(app, ["internet"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.ping.emit_ping_metrics")
    @patch("netglance.cli.ping.Store")
    @patch("netglance.cli.ping.check_gateway")
    def test_ping_gateway_save(self, mock_gw, mock_store_cls, mock_emit):
        from netglance.cli.ping import app

        mock_gw.return_value = _make_ping_result("192.168.1.1")
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["gateway", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()

    @patch("netglance.cli.ping.check_gateway")
    def test_ping_gateway_no_save(self, mock_gw):
        from netglance.cli.ping import app

        mock_gw.return_value = _make_ping_result("192.168.1.1")

        result = runner.invoke(app, ["gateway"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# discover module tests
# ===========================================================================


class TestDiscoverSaveDisclosure:

    @patch("netglance.cli.discover.Store")
    @patch("netglance.cli.discover.discover_all")
    def test_discover_save_shows_disclosure(self, mock_discover, mock_store_cls):
        from netglance.cli.discover import app

        mock_discover.return_value = [_make_device()]
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output

    @patch("netglance.cli.discover.discover_all")
    def test_discover_no_save_default(self, mock_discover):
        from netglance.cli.discover import app

        mock_discover.return_value = [_make_device()]

        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.discover.discover_all")
    def test_discover_no_save_explicit(self, mock_discover):
        from netglance.cli.discover import app

        mock_discover.return_value = [_make_device()]

        result = runner.invoke(app, ["--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# scan module tests
# ===========================================================================


class TestScanSaveDisclosure:
    """Use main CLI app because typer sub-app has arg parsing issues with 'host' subcommand."""

    @patch("netglance.cli.scan.Store")
    @patch("netglance.cli.scan.quick_scan")
    def test_scan_save_shows_disclosure(self, mock_scan, mock_store_cls):
        from netglance.cli import app

        mock_scan.return_value = _make_scan_result()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["scan", "host", "192.168.1.1", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()

    @patch("netglance.cli.scan.quick_scan")
    def test_scan_no_save_default(self, mock_scan):
        from netglance.cli import app

        mock_scan.return_value = _make_scan_result()

        result = runner.invoke(app, ["scan", "host", "192.168.1.1"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.scan.quick_scan")
    def test_scan_no_save_explicit(self, mock_scan):
        from netglance.cli import app

        mock_scan.return_value = _make_scan_result()

        result = runner.invoke(app, ["scan", "host", "192.168.1.1", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# route module tests
# ===========================================================================


class TestRouteSaveDisclosure:
    """Use main CLI app because typer sub-app has arg parsing issues with 'host' param name."""

    @patch("netglance.cli.route.Store")
    @patch("netglance.cli.route.traceroute")
    def test_route_save_shows_disclosure(self, mock_trace, mock_store_cls):
        from netglance.cli import app

        mock_trace.return_value = _make_trace_result()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["route", "trace", "8.8.8.8", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output

    @patch("netglance.cli.route.traceroute")
    def test_route_no_save_default(self, mock_trace):
        from netglance.cli import app

        mock_trace.return_value = _make_trace_result()

        result = runner.invoke(app, ["route", "trace", "8.8.8.8"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# speed module tests
# ===========================================================================


class TestSpeedSaveDisclosure:

    @patch("netglance.cli.speed.Store")
    @patch("netglance.cli.speed.run_speedtest")
    def test_speed_save_shows_disclosure(self, mock_speed, mock_store_cls):
        from netglance.cli.speed import app

        mock_speed.return_value = _make_speed_result()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()

    @patch("netglance.cli.speed.run_speedtest")
    def test_speed_no_save(self, mock_speed):
        from netglance.cli.speed import app

        mock_speed.return_value = _make_speed_result()

        result = runner.invoke(app, ["--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# topology module tests
# ===========================================================================


class TestTopologySaveDisclosure:

    @patch("netglance.store.db.Store")
    @patch("netglance.cli.topology.discover_topology")
    def test_topology_save_shows_disclosure(self, mock_topo, mock_store_cls):
        from netglance.cli.topology import app

        mock_topo.return_value = _make_topology()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["show", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output

    @patch("netglance.cli.topology.discover_topology")
    def test_topology_no_save(self, mock_topo):
        from netglance.cli.topology import app

        mock_topo.return_value = _make_topology()

        result = runner.invoke(app, ["show", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# dns module tests
# ===========================================================================


class TestDnsSaveDisclosure:

    @patch("netglance.cli.dns.Store")
    @patch("netglance.cli.dns.check_consistency")
    def test_dns_check_save(self, mock_check, mock_store_cls):
        from netglance.cli.dns import app

        mock_check.return_value = _make_dns_report()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["check", "example.com", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[0][0] == "dns"

    @patch("netglance.cli.dns.check_consistency")
    def test_dns_check_no_save_default(self, mock_check):
        from netglance.cli.dns import app

        mock_check.return_value = _make_dns_report()

        result = runner.invoke(app, ["check", "example.com"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.dns.check_consistency")
    def test_dns_check_no_save_explicit(self, mock_check):
        from netglance.cli.dns import app

        mock_check.return_value = _make_dns_report()

        result = runner.invoke(app, ["check", "example.com", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# tls module tests
# ===========================================================================


class TestTlsSaveDisclosure:

    @patch("netglance.cli.tls.Store")
    @patch("netglance.cli.tls.check_certificate")
    def test_tls_verify_save(self, mock_check, mock_store_cls):
        from netglance.cli.tls import app

        mock_check.return_value = _make_tls_result()
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["verify", "example.com", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[0][0] == "tls"
        saved_data = call_args[0][1]
        assert saved_data["hosts_checked"] == 1
        assert saved_data["all_trusted"] is True

    @patch("netglance.cli.tls.check_certificate")
    def test_tls_verify_no_save_default(self, mock_check):
        from netglance.cli.tls import app

        mock_check.return_value = _make_tls_result()

        result = runner.invoke(app, ["verify", "example.com"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.tls.check_certificate")
    def test_tls_verify_no_save_explicit(self, mock_check):
        from netglance.cli.tls import app

        mock_check.return_value = _make_tls_result()

        result = runner.invoke(app, ["verify", "example.com", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# wifi module tests
# ===========================================================================


class TestWifiSaveDisclosure:

    @patch("netglance.cli.wifi.current_connection", return_value=None)
    @patch("netglance.cli.wifi.Store")
    @patch("netglance.cli.wifi.scan_wifi")
    def test_wifi_scan_save(self, mock_scan, mock_store_cls, mock_conn):
        from netglance.cli.wifi import app

        mock_scan.return_value = [_make_wifi_network()]
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["scan", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[0][0] == "wifi"
        saved_data = call_args[0][1]
        assert saved_data["networks_found"] == 1

    @patch("netglance.cli.wifi.scan_wifi")
    def test_wifi_scan_no_save_default(self, mock_scan):
        from netglance.cli.wifi import app

        mock_scan.return_value = [_make_wifi_network()]

        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.wifi.scan_wifi")
    def test_wifi_scan_no_save_explicit(self, mock_scan):
        from netglance.cli.wifi import app

        mock_scan.return_value = [_make_wifi_network()]

        result = runner.invoke(app, ["scan", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output


# ===========================================================================
# arp module tests
# ===========================================================================


class TestArpSaveDisclosure:

    @patch("netglance.cli.arp.Store")
    @patch("netglance.cli.arp.get_arp_table")
    def test_arp_table_save(self, mock_arp, mock_store_cls):
        from netglance.cli.arp import app

        mock_arp.return_value = [_make_arp_entry()]
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = runner.invoke(app, ["table", "--save"])
        assert result.exit_code == 0
        assert DISCLOSURE in result.output
        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[0][0] == "arp"

    @patch("netglance.cli.arp.get_arp_table")
    def test_arp_table_no_save_default(self, mock_arp):
        from netglance.cli.arp import app

        mock_arp.return_value = [_make_arp_entry()]

        result = runner.invoke(app, ["table"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output

    @patch("netglance.cli.arp.get_arp_table")
    def test_arp_table_no_save_explicit(self, mock_arp):
        from netglance.cli.arp import app

        mock_arp.return_value = [_make_arp_entry()]

        result = runner.invoke(app, ["table", "--no-save"])
        assert result.exit_code == 0
        assert DISCLOSURE not in result.output
