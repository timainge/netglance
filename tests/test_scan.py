"""Tests for the scan module -- fully mocked, no real network access."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.scan import (
    SUSPICIOUS_PORTS,
    TOP_100_PORTS,
    _parse_port_range,
    _scan_with_nmap,
    _scan_with_scapy,
    diff_scans,
    has_nmap,
    quick_scan,
    scan_host,
)
from netglance.store.models import HostScanResult, PortResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Unit tests: has_nmap
# ---------------------------------------------------------------------------


class TestHasNmap:
    def test_nmap_available(self) -> None:
        with patch("netglance.modules.scan.shutil.which", return_value="/usr/bin/nmap"):
            assert has_nmap() is True

    def test_nmap_not_available(self) -> None:
        with patch("netglance.modules.scan.shutil.which", return_value=None):
            assert has_nmap() is False


# ---------------------------------------------------------------------------
# Unit tests: _parse_port_range
# ---------------------------------------------------------------------------


class TestParsePortRange:
    def test_single_port(self) -> None:
        assert _parse_port_range("80") == [80]

    def test_comma_separated(self) -> None:
        assert _parse_port_range("22,80,443") == [22, 80, 443]

    def test_range(self) -> None:
        result = _parse_port_range("1-5")
        assert result == [1, 2, 3, 4, 5]

    def test_mixed(self) -> None:
        result = _parse_port_range("22,80,100-102")
        assert result == [22, 80, 100, 101, 102]

    def test_deduplication(self) -> None:
        result = _parse_port_range("80,80,80")
        assert result == [80]


# ---------------------------------------------------------------------------
# Synthetic nmap data factory
# ---------------------------------------------------------------------------


def _make_nmap_result(host: str, ports: list[dict]) -> dict:
    """Build a synthetic python3-nmap scan_top_ports result dict."""
    port_entries = []
    for p in ports:
        port_entries.append(
            {
                "portid": str(p["port"]),
                "state": p.get("state", "open"),
                "service": {
                    "name": p.get("service", "unknown"),
                    "version": p.get("version", ""),
                    "product": p.get("product", ""),
                },
            }
        )
    return {
        host: {
            "ports": port_entries,
        },
        "runtime": {"elapsed": "0.5"},
        "stats": {},
    }


# ---------------------------------------------------------------------------
# Unit tests: _scan_with_nmap
# ---------------------------------------------------------------------------


class TestScanWithNmap:
    def test_nmap_parses_open_ports(self) -> None:
        fake_result = _make_nmap_result(
            "192.168.1.1",
            [
                {"port": 22, "state": "open", "service": "ssh", "version": "8.9"},
                {"port": 80, "state": "open", "service": "http"},
                {"port": 443, "state": "filtered", "service": "https"},
            ],
        )

        mock_nmap = MagicMock()
        mock_nmap.scan_top_ports.return_value = fake_result

        with patch("netglance.modules.scan.nmap3") as mock_nmap3_module:
            mock_nmap3_module.Nmap.return_value = mock_nmap
            result = _scan_with_nmap("192.168.1.1", ports="22,80,443")

        assert result.host == "192.168.1.1"
        assert len(result.ports) == 3

        ssh = next(p for p in result.ports if p.port == 22)
        assert ssh.state == "open"
        assert ssh.service == "ssh"
        assert ssh.version == "8.9"

        https = next(p for p in result.ports if p.port == 443)
        assert https.state == "filtered"

    def test_nmap_no_open_ports(self) -> None:
        fake_result = _make_nmap_result("192.168.1.1", [])
        mock_nmap = MagicMock()
        mock_nmap.scan_top_ports.return_value = fake_result

        with patch("netglance.modules.scan.nmap3") as mock_nmap3_module:
            mock_nmap3_module.Nmap.return_value = mock_nmap
            result = _scan_with_nmap("192.168.1.1")

        assert result.host == "192.168.1.1"
        assert result.ports == []

    def test_nmap_closed_ports_excluded(self) -> None:
        fake_result = _make_nmap_result(
            "10.0.0.1",
            [
                {"port": 80, "state": "open", "service": "http"},
                {"port": 81, "state": "closed", "service": "unknown"},
            ],
        )
        mock_nmap = MagicMock()
        mock_nmap.scan_top_ports.return_value = fake_result

        with patch("netglance.modules.scan.nmap3") as mock_nmap3_module:
            mock_nmap3_module.Nmap.return_value = mock_nmap
            result = _scan_with_nmap("10.0.0.1")

        assert len(result.ports) == 1
        assert result.ports[0].port == 80


# ---------------------------------------------------------------------------
# Unit tests: _scan_with_scapy
# ---------------------------------------------------------------------------


class TestScanWithScapy:
    def _make_syn_ack_response(self) -> MagicMock:
        """Create a mock scapy response with SYN-ACK flags."""
        resp = MagicMock()
        tcp_layer = MagicMock()
        tcp_layer.flags = 0x12  # SYN-ACK
        resp.haslayer.return_value = True
        resp.getlayer.return_value = tcp_layer
        return resp

    def _make_rst_response(self) -> MagicMock:
        """Create a mock scapy response with RST-ACK flags."""
        resp = MagicMock()
        tcp_layer = MagicMock()
        tcp_layer.flags = 0x14  # RST-ACK
        resp.haslayer.return_value = True
        resp.getlayer.return_value = tcp_layer
        return resp

    def test_scapy_detects_open_port(self) -> None:
        syn_ack = self._make_syn_ack_response()

        with (
            patch("netglance.modules.scan.IP") as mock_ip,
            patch("netglance.modules.scan.TCP") as mock_tcp,
            patch("netglance.modules.scan.sr1", return_value=syn_ack) as mock_sr1,
        ):
            mock_ip.return_value = MagicMock()
            mock_tcp.return_value = MagicMock()
            mock_ip.return_value.__truediv__ = lambda self, other: MagicMock()

            result = _scan_with_scapy("192.168.1.1", ports="80")

        assert len(result.ports) == 1
        assert result.ports[0].port == 80
        assert result.ports[0].state == "open"

    def test_scapy_closed_port_excluded(self) -> None:
        rst = self._make_rst_response()

        with (
            patch("netglance.modules.scan.IP") as mock_ip,
            patch("netglance.modules.scan.TCP") as mock_tcp,
            patch("netglance.modules.scan.sr1", return_value=rst),
        ):
            mock_ip.return_value = MagicMock()
            mock_tcp.return_value = MagicMock()
            mock_ip.return_value.__truediv__ = lambda self, other: MagicMock()

            result = _scan_with_scapy("192.168.1.1", ports="80")

        assert result.ports == []

    def test_scapy_no_response(self) -> None:
        with (
            patch("netglance.modules.scan.IP") as mock_ip,
            patch("netglance.modules.scan.TCP") as mock_tcp,
            patch("netglance.modules.scan.sr1", return_value=None),
        ):
            mock_ip.return_value = MagicMock()
            mock_tcp.return_value = MagicMock()
            mock_ip.return_value.__truediv__ = lambda self, other: MagicMock()

            result = _scan_with_scapy("192.168.1.1", ports="80")

        assert result.ports == []

    def test_scapy_multiple_ports(self) -> None:
        syn_ack = self._make_syn_ack_response()
        rst = self._make_rst_response()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # port 22 open, port 80 closed, port 443 open
            if call_count == 1:
                return syn_ack
            elif call_count == 2:
                return rst
            else:
                return syn_ack

        with (
            patch("netglance.modules.scan.IP") as mock_ip,
            patch("netglance.modules.scan.TCP") as mock_tcp,
            patch("netglance.modules.scan.sr1", side_effect=side_effect),
        ):
            mock_ip.return_value = MagicMock()
            mock_tcp.return_value = MagicMock()
            mock_ip.return_value.__truediv__ = lambda self, other: MagicMock()

            result = _scan_with_scapy("192.168.1.1", ports="22,80,443")

        assert len(result.ports) == 2
        port_nums = {p.port for p in result.ports}
        assert port_nums == {22, 443}


# ---------------------------------------------------------------------------
# Unit tests: scan_host dispatching
# ---------------------------------------------------------------------------


class TestScanHost:
    def test_uses_nmap_when_available(self) -> None:
        fake_result = _make_nmap_result(
            "10.0.0.1",
            [{"port": 22, "state": "open", "service": "ssh"}],
        )
        mock_nmap = MagicMock()
        mock_nmap.scan_top_ports.return_value = fake_result

        with (
            patch("netglance.modules.scan.has_nmap", return_value=True),
            patch("netglance.modules.scan.nmap3") as mock_nmap3_module,
        ):
            mock_nmap3_module.Nmap.return_value = mock_nmap
            result = scan_host("10.0.0.1", ports="22")

        assert result.host == "10.0.0.1"
        assert len(result.ports) == 1
        assert result.ports[0].service == "ssh"

    def test_falls_back_to_scapy(self) -> None:
        syn_ack = MagicMock()
        tcp_layer = MagicMock()
        tcp_layer.flags = 0x12
        syn_ack.haslayer.return_value = True
        syn_ack.getlayer.return_value = tcp_layer

        with (
            patch("netglance.modules.scan.has_nmap", return_value=False),
            patch("netglance.modules.scan.IP") as mock_ip,
            patch("netglance.modules.scan.TCP") as mock_tcp,
            patch("netglance.modules.scan.sr1", return_value=syn_ack),
        ):
            mock_ip.return_value = MagicMock()
            mock_tcp.return_value = MagicMock()
            mock_ip.return_value.__truediv__ = lambda self, other: MagicMock()

            result = scan_host("10.0.0.1", ports="80")

        assert result.host == "10.0.0.1"
        assert len(result.ports) == 1
        assert result.ports[0].port == 80


# ---------------------------------------------------------------------------
# Unit tests: quick_scan
# ---------------------------------------------------------------------------


class TestQuickScan:
    def test_quick_scan_uses_top_100(self) -> None:
        fake_result = _make_nmap_result(
            "192.168.1.1",
            [{"port": 80, "state": "open", "service": "http"}],
        )
        mock_nmap = MagicMock()
        mock_nmap.scan_top_ports.return_value = fake_result

        with (
            patch("netglance.modules.scan.has_nmap", return_value=True),
            patch("netglance.modules.scan.nmap3") as mock_nmap3_module,
        ):
            mock_nmap3_module.Nmap.return_value = mock_nmap
            result = quick_scan("192.168.1.1")

        assert result.host == "192.168.1.1"
        # Verify the ports string passed to nmap includes top 100 ports
        call_args = mock_nmap.scan_top_ports.call_args
        args_str = call_args[1].get("args", "") if call_args[1] else call_args[0][1]
        # It should contain the ports from TOP_100_PORTS
        assert "80" in args_str


# ---------------------------------------------------------------------------
# Unit tests: diff_scans (pure data, no mocks needed)
# ---------------------------------------------------------------------------


class TestDiffScans:
    def test_new_ports_detected(self) -> None:
        previous = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh"),
                PortResult(port=80, state="open", service="http"),
            ],
        )
        current = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh"),
                PortResult(port=80, state="open", service="http"),
                PortResult(port=443, state="open", service="https"),
            ],
        )

        changes = diff_scans(current, previous)

        assert len(changes["new_ports"]) == 1
        assert changes["new_ports"][0]["port"] == 443
        assert changes["closed_ports"] == []
        assert changes["changed_services"] == []

    def test_closed_ports_detected(self) -> None:
        previous = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh"),
                PortResult(port=80, state="open", service="http"),
            ],
        )
        current = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh"),
            ],
        )

        changes = diff_scans(current, previous)

        assert changes["new_ports"] == []
        assert len(changes["closed_ports"]) == 1
        assert changes["closed_ports"][0]["port"] == 80

    def test_changed_services_detected(self) -> None:
        previous = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=80, state="open", service="http", version="1.0"),
            ],
        )
        current = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=80, state="open", service="http", version="2.0"),
            ],
        )

        changes = diff_scans(current, previous)

        assert changes["new_ports"] == []
        assert changes["closed_ports"] == []
        assert len(changes["changed_services"]) == 1
        assert changes["changed_services"][0]["port"] == 80
        assert changes["changed_services"][0]["old_version"] == "1.0"
        assert changes["changed_services"][0]["new_version"] == "2.0"

    def test_service_name_change(self) -> None:
        previous = HostScanResult(
            host="10.0.0.1",
            ports=[PortResult(port=8080, state="open", service="http-proxy")],
        )
        current = HostScanResult(
            host="10.0.0.1",
            ports=[PortResult(port=8080, state="open", service="http")],
        )

        changes = diff_scans(current, previous)

        assert len(changes["changed_services"]) == 1
        assert changes["changed_services"][0]["old_service"] == "http-proxy"
        assert changes["changed_services"][0]["new_service"] == "http"

    def test_no_changes(self) -> None:
        scan = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh"),
                PortResult(port=80, state="open", service="http"),
            ],
        )

        changes = diff_scans(scan, scan)

        assert changes["new_ports"] == []
        assert changes["closed_ports"] == []
        assert changes["changed_services"] == []

    def test_empty_scans(self) -> None:
        empty = HostScanResult(host="192.168.1.1", ports=[])
        changes = diff_scans(empty, empty)

        assert changes["new_ports"] == []
        assert changes["closed_ports"] == []
        assert changes["changed_services"] == []

    def test_combined_changes(self) -> None:
        previous = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh", version="7.0"),
                PortResult(port=80, state="open", service="http"),
                PortResult(port=3306, state="open", service="mysql"),
            ],
        )
        current = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh", version="9.0"),
                PortResult(port=443, state="open", service="https"),
                PortResult(port=3306, state="open", service="mysql"),
            ],
        )

        changes = diff_scans(current, previous)

        # port 443 is new
        assert len(changes["new_ports"]) == 1
        assert changes["new_ports"][0]["port"] == 443

        # port 80 is closed
        assert len(changes["closed_ports"]) == 1
        assert changes["closed_ports"][0]["port"] == 80

        # port 22 service version changed
        assert len(changes["changed_services"]) == 1
        assert changes["changed_services"][0]["port"] == 22


# ---------------------------------------------------------------------------
# SUSPICIOUS_PORTS sanity check
# ---------------------------------------------------------------------------


class TestSuspiciousPorts:
    def test_contains_telnet(self) -> None:
        assert 23 in SUSPICIOUS_PORTS

    def test_contains_ftp(self) -> None:
        assert 21 in SUSPICIOUS_PORTS

    def test_contains_rdp(self) -> None:
        assert 3389 in SUSPICIOUS_PORTS


# ---------------------------------------------------------------------------
# CLI tests via CliRunner
# ---------------------------------------------------------------------------


class TestScanCLI:
    def test_scan_help(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output.lower() or "scan" in result.output.lower()

    def test_scan_host_default(self) -> None:
        """Test `netglance scan host <ip>` with mocked quick_scan."""
        fake_result = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open", service="ssh", version="8.9"),
                PortResult(port=80, state="open", service="http"),
            ],
            scan_duration_s=0.5,
        )

        with patch("netglance.cli.scan.quick_scan", return_value=fake_result):
            result = runner.invoke(app, ["scan", "host", "192.168.1.1"])

        assert result.exit_code == 0
        assert "22" in result.output
        assert "80" in result.output
        assert "ssh" in result.output
        assert "http" in result.output

    def test_scan_host_custom_ports(self) -> None:
        """Test `netglance scan host <ip> --ports 22,443`."""
        fake_result = HostScanResult(
            host="10.0.0.1",
            ports=[
                PortResult(port=443, state="open", service="https"),
            ],
            scan_duration_s=0.3,
        )

        with patch("netglance.cli.scan.scan_host", return_value=fake_result):
            result = runner.invoke(app, ["scan", "host", "10.0.0.1", "--ports", "22,443"])

        assert result.exit_code == 0
        assert "443" in result.output
        assert "https" in result.output

    def test_scan_host_suspicious_port_displayed(self) -> None:
        """Suspicious ports (e.g. telnet/23) should appear in output."""
        fake_result = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=23, state="open", service="telnet"),
            ],
            scan_duration_s=0.2,
        )

        with patch("netglance.cli.scan.quick_scan", return_value=fake_result):
            result = runner.invoke(app, ["scan", "host", "192.168.1.1"])

        assert result.exit_code == 0
        assert "23" in result.output
        assert "telnet" in result.output

    def test_scan_host_no_ports(self) -> None:
        """Test output when no open ports are found."""
        fake_result = HostScanResult(
            host="192.168.1.1",
            ports=[],
            scan_duration_s=1.0,
        )

        with patch("netglance.cli.scan.quick_scan", return_value=fake_result):
            result = runner.invoke(app, ["scan", "host", "192.168.1.1"])

        assert result.exit_code == 0
        assert "0 open" in result.output
