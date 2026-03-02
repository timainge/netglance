"""Tests for the ARP module -- fully mocked, no real network access."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.arp import (
    check_arp_anomalies,
    get_arp_table,
    get_gateway_mac,
    parse_arp_output,
    parse_gateway_ip,
    watch_arp,
)
from netglance.store.models import ArpEntry

runner = CliRunner()

# ---------------------------------------------------------------------------
# Sample macOS ``arp -a`` output
# ---------------------------------------------------------------------------
SAMPLE_ARP_OUTPUT = """\
? (192.168.1.1) at aa:bb:cc:dd:ee:01 on en0 ifscope [ethernet]
? (192.168.1.10) at aa:bb:cc:dd:ee:10 on en0 ifscope [ethernet]
? (192.168.1.20) at aa:bb:cc:dd:ee:20 on en0 ifscope [ethernet]
? (192.168.1.30) at aa:bb:cc:dd:ee:30 on en1 ifscope [ethernet]
"""

SAMPLE_ROUTE_OUTPUT = """\
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,AUTOCONF>
"""


# ===================================================================
# Unit tests: parse_arp_output
# ===================================================================

class TestParseArpOutput:
    def test_parses_typical_macos_output(self) -> None:
        entries = parse_arp_output(SAMPLE_ARP_OUTPUT)
        assert len(entries) == 4
        assert entries[0].ip == "192.168.1.1"
        assert entries[0].mac == "aa:bb:cc:dd:ee:01"
        assert entries[0].interface == "en0"

    def test_empty_output(self) -> None:
        entries = parse_arp_output("")
        assert entries == []

    def test_ignores_incomplete_lines(self) -> None:
        raw = "? (192.168.1.1) at (incomplete) on en0 ifscope [ethernet]\n"
        entries = parse_arp_output(raw)
        assert entries == []

    def test_mac_normalised_to_lowercase(self) -> None:
        raw = "? (10.0.0.1) at AA:BB:CC:DD:EE:FF on en0 ifscope [ethernet]\n"
        entries = parse_arp_output(raw)
        assert entries[0].mac == "aa:bb:cc:dd:ee:ff"


# ===================================================================
# Unit tests: parse_gateway_ip
# ===================================================================

class TestParseGatewayIp:
    def test_parses_gateway_from_route_output(self) -> None:
        gw = parse_gateway_ip(SAMPLE_ROUTE_OUTPUT)
        assert gw == "192.168.1.1"

    def test_returns_none_when_no_gateway(self) -> None:
        assert parse_gateway_ip("nothing useful here\n") is None


# ===================================================================
# Unit tests: get_arp_table (injected subprocess)
# ===================================================================

class TestGetArpTable:
    def test_returns_parsed_entries(self) -> None:
        entries = get_arp_table(_run_arp=lambda: SAMPLE_ARP_OUTPUT)
        assert len(entries) == 4
        assert all(isinstance(e, ArpEntry) for e in entries)

    def test_empty_table(self) -> None:
        entries = get_arp_table(_run_arp=lambda: "")
        assert entries == []


# ===================================================================
# Unit tests: get_gateway_mac
# ===================================================================

class TestGetGatewayMac:
    def test_returns_gateway_entry(self) -> None:
        entry = get_gateway_mac(
            _run_arp=lambda: SAMPLE_ARP_OUTPUT,
            _run_route=lambda: SAMPLE_ROUTE_OUTPUT,
        )
        assert entry is not None
        assert entry.ip == "192.168.1.1"
        assert entry.mac == "aa:bb:cc:dd:ee:01"

    def test_returns_none_when_gateway_not_in_table(self) -> None:
        route = SAMPLE_ROUTE_OUTPUT.replace("192.168.1.1", "10.0.0.1")
        entry = get_gateway_mac(
            _run_arp=lambda: SAMPLE_ARP_OUTPUT,
            _run_route=lambda: route,
        )
        assert entry is None

    def test_returns_none_when_no_gateway_ip(self) -> None:
        entry = get_gateway_mac(
            _run_arp=lambda: SAMPLE_ARP_OUTPUT,
            _run_route=lambda: "no gateway line\n",
        )
        assert entry is None

    def test_filters_by_interface(self) -> None:
        entry = get_gateway_mac(
            interface="en0",
            _run_arp=lambda: SAMPLE_ARP_OUTPUT,
            _run_route=lambda: SAMPLE_ROUTE_OUTPUT,
        )
        assert entry is not None
        assert entry.interface == "en0"


# ===================================================================
# Unit tests: check_arp_anomalies
# ===================================================================

def _make_entry(ip: str, mac: str, iface: str = "en0") -> ArpEntry:
    return ArpEntry(ip=ip, mac=mac, interface=iface)


class TestCheckArpAnomalies:
    def test_no_anomalies(self) -> None:
        baseline = [
            _make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
        ]
        current = [
            _make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
        ]
        alerts = check_arp_anomalies(current, baseline)
        assert alerts == []

    def test_mac_changed_critical(self) -> None:
        baseline = [_make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10")]
        current = [_make_entry("192.168.1.10", "ff:ff:ff:ff:ff:ff")]

        alerts = check_arp_anomalies(current, baseline)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == "mac_changed"
        assert alert.severity == "critical"
        assert alert.old_value == "aa:bb:cc:dd:ee:10"
        assert alert.new_value == "ff:ff:ff:ff:ff:ff"

    def test_gateway_spoof_critical(self) -> None:
        baseline = [_make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        current = [_make_entry("192.168.1.1", "ff:ff:ff:ff:ff:ff")]

        alerts = check_arp_anomalies(
            current, baseline, gateway_ip="192.168.1.1"
        )
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == "gateway_spoof"
        assert alert.severity == "critical"
        assert "192.168.1.1" in alert.description

    def test_duplicate_mac_warning(self) -> None:
        baseline = [
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
            _make_entry("192.168.1.20", "aa:bb:cc:dd:ee:20"),
        ]
        # Two IPs now share the same MAC
        current = [
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
            _make_entry("192.168.1.20", "aa:bb:cc:dd:ee:10"),
        ]
        alerts = check_arp_anomalies(current, baseline)
        dup_mac_alerts = [a for a in alerts if a.alert_type == "duplicate_mac"]
        assert len(dup_mac_alerts) == 1
        assert dup_mac_alerts[0].severity == "warning"
        assert "aa:bb:cc:dd:ee:10" in dup_mac_alerts[0].description

    def test_duplicate_ip_warning(self) -> None:
        baseline = [_make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10")]
        # Same IP appears with two different MACs
        current = [
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
            _make_entry("192.168.1.10", "ff:ff:ff:ff:ff:ff"),
        ]
        alerts = check_arp_anomalies(current, baseline)
        dup_ip_alerts = [a for a in alerts if a.alert_type == "duplicate_ip"]
        assert len(dup_ip_alerts) == 1
        assert dup_ip_alerts[0].severity == "warning"
        assert "192.168.1.10" in dup_ip_alerts[0].description

    def test_new_device_no_alert(self) -> None:
        """A new device (not in baseline) should NOT trigger mac_changed."""
        baseline = [_make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        current = [
            _make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_entry("192.168.1.99", "cc:cc:cc:cc:cc:cc"),
        ]
        alerts = check_arp_anomalies(current, baseline)
        assert alerts == []

    def test_multiple_anomalies(self) -> None:
        """Multiple anomaly types can fire at once."""
        baseline = [
            _make_entry("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_entry("192.168.1.10", "aa:bb:cc:dd:ee:10"),
        ]
        current = [
            # gateway spoofed
            _make_entry("192.168.1.1", "ff:ff:ff:ff:ff:ff"),
            # duplicate MAC with the spoofed gateway
            _make_entry("192.168.1.10", "ff:ff:ff:ff:ff:ff"),
        ]
        alerts = check_arp_anomalies(
            current, baseline, gateway_ip="192.168.1.1"
        )
        types = {a.alert_type for a in alerts}
        assert "gateway_spoof" in types
        assert "duplicate_mac" in types


# ===================================================================
# Unit tests: watch_arp
# ===================================================================

class TestWatchArp:
    def test_callback_invoked_with_entries(self) -> None:
        call_count = 0

        def fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt

        collected: list[list[ArpEntry]] = []

        def cb(entries: list[ArpEntry]) -> None:
            collected.append(entries)

        with pytest.raises(KeyboardInterrupt):
            watch_arp(
                cb,
                interval=1.0,
                _run_arp=lambda: SAMPLE_ARP_OUTPUT,
                _sleep=fake_sleep,
            )

        assert len(collected) == 3
        assert all(len(e) == 4 for e in collected)

    def test_uses_custom_interval(self) -> None:
        intervals: list[float] = []

        def spy_sleep(secs: float) -> None:
            intervals.append(secs)
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            watch_arp(
                lambda _: None,
                interval=42.0,
                _run_arp=lambda: SAMPLE_ARP_OUTPUT,
                _sleep=spy_sleep,
            )

        assert intervals == [42.0]


# ===================================================================
# CLI tests (via CliRunner)
# ===================================================================

class TestArpCli:
    def test_arp_help(self) -> None:
        result = runner.invoke(app, ["arp", "--help"])
        assert result.exit_code == 0
        assert "ARP" in result.output or "arp" in result.output.lower()

    @patch("netglance.modules.arp._run_arp_command", return_value=SAMPLE_ARP_OUTPUT)
    def test_arp_table(self, mock_arp: MagicMock) -> None:
        result = runner.invoke(app, ["arp", "table"])
        assert result.exit_code == 0
        assert "192.168.1.1" in result.output
        assert "aa:bb:cc:dd:ee:01" in result.output

    @patch("netglance.modules.arp._run_arp_command", return_value=SAMPLE_ARP_OUTPUT)
    def test_arp_table_filter_interface(self, mock_arp: MagicMock) -> None:
        result = runner.invoke(app, ["arp", "table", "--interface", "en1"])
        assert result.exit_code == 0
        assert "192.168.1.30" in result.output
        # en0-only entries should not appear
        assert "192.168.1.10" not in result.output

    @patch("netglance.modules.arp._run_arp_command", return_value="")
    def test_arp_table_empty(self, mock_arp: MagicMock) -> None:
        result = runner.invoke(app, ["arp", "table"])
        assert result.exit_code == 0
        assert "No ARP entries" in result.output

    @patch("netglance.modules.arp._run_arp_command", return_value=SAMPLE_ARP_OUTPUT)
    def test_arp_save_and_check(self, mock_arp: MagicMock, tmp_path) -> None:
        db = str(tmp_path / "test.db")

        # Save baseline
        save_result = runner.invoke(app, ["arp", "save", "--db", db])
        assert save_result.exit_code == 0
        assert "Baseline saved" in save_result.output

        # Check -- no anomalies expected
        check_result = runner.invoke(app, ["arp", "check", "--db", db])
        assert check_result.exit_code == 0
        assert "No anomalies" in check_result.output

    @patch("netglance.modules.arp._run_arp_command", return_value="")
    def test_arp_save_empty_fails(self, mock_arp: MagicMock, tmp_path) -> None:
        db = str(tmp_path / "test.db")
        result = runner.invoke(app, ["arp", "save", "--db", db])
        assert result.exit_code == 1
        assert "No ARP entries" in result.output

    def test_arp_check_no_baseline(self, tmp_path) -> None:
        db = str(tmp_path / "test.db")
        result = runner.invoke(app, ["arp", "check", "--db", db])
        assert result.exit_code == 1
        assert "No ARP baseline" in result.output

    @patch("netglance.modules.arp._run_arp_command")
    def test_arp_check_detects_mac_change(self, mock_arp: MagicMock, tmp_path) -> None:
        db = str(tmp_path / "test.db")

        # Save baseline with original MACs
        mock_arp.return_value = SAMPLE_ARP_OUTPUT
        runner.invoke(app, ["arp", "save", "--db", db])

        # Now change a MAC
        changed_output = SAMPLE_ARP_OUTPUT.replace(
            "aa:bb:cc:dd:ee:10", "ff:ff:ff:ff:ff:ff"
        )
        mock_arp.return_value = changed_output

        result = runner.invoke(app, ["arp", "check", "--db", db])
        assert result.exit_code == 0
        assert "mac_changed" in result.output
