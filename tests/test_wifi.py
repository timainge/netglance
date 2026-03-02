"""Tests for the wifi module -- all network calls are mocked."""

from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.wifi import (
    _parse_info_output,
    _parse_scan_output,
    channel_utilization,
    current_connection,
    detect_rogue_aps,
    scan_wifi,
    signal_bar,
)
from netglance.store.models import WifiNetwork

runner = CliRunner()

# ---------------------------------------------------------------------------
# Sample airport outputs used across tests
# ---------------------------------------------------------------------------

AIRPORT_SCAN_OUTPUT = """\
                            SSID BSSID             RSSI CHANNEL HT CC SECURITY (auth/unicast/group, 802.1X/AES/AES)
                        HomeWifi aa:bb:cc:dd:ee:01  -45 6       Y  -- WPA2(PSK/AES/AES)
                    NeighborWifi aa:bb:cc:dd:ee:02  -72 11      Y  -- WPA2(PSK/AES/AES)
                      CoffeeShop aa:bb:cc:dd:ee:03  -85 1       Y  -- WPA(PSK/TKIP/TKIP)
                        Office5G aa:bb:cc:dd:ee:04  -55 36      Y  -- WPA2(PSK/AES/AES)
                                 aa:bb:cc:dd:ee:05  -90 149     Y  -- NONE
"""

AIRPORT_INFO_OUTPUT = """\
     agrCtlRSSI: -55
     agrCtlNoise: -88
           SSID: HomeWifi
          BSSID: aa:bb:cc:dd:ee:01
     channel: 6
     link auth: wpa2-psk
"""

AIRPORT_INFO_DISCONNECTED = """\
AirPort: Off
"""


# ---------------------------------------------------------------------------
# Helpers -- mock subprocess.run
# ---------------------------------------------------------------------------

def _make_run_fn(stdout: str, returncode: int = 0):
    """Create a mock subprocess.run that returns given stdout."""
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else [],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )
    return _run


# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------

class TestParseScanOutput:
    def test_parse_multiple_networks(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        assert len(networks) == 5

    def test_parse_ssid(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        ssids = [n.ssid for n in networks]
        assert "HomeWifi" in ssids
        assert "NeighborWifi" in ssids
        assert "CoffeeShop" in ssids
        assert "Office5G" in ssids

    def test_parse_hidden_ssid(self):
        """A network with empty SSID should still be parsed."""
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        hidden = [n for n in networks if n.ssid == ""]
        assert len(hidden) == 1
        assert hidden[0].bssid == "aa:bb:cc:dd:ee:05"

    def test_parse_bssid(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        bssids = [n.bssid for n in networks]
        assert "aa:bb:cc:dd:ee:01" in bssids
        assert "aa:bb:cc:dd:ee:04" in bssids

    def test_parse_signal(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        home = [n for n in networks if n.ssid == "HomeWifi"][0]
        assert home.signal_dbm == -45

    def test_parse_channel_2g(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        home = [n for n in networks if n.ssid == "HomeWifi"][0]
        assert home.channel == 6
        assert home.band == "2.4 GHz"

    def test_parse_channel_5g(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        office = [n for n in networks if n.ssid == "Office5G"][0]
        assert office.channel == 36
        assert office.band == "5 GHz"

    def test_parse_security(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        home = [n for n in networks if n.ssid == "HomeWifi"][0]
        assert "WPA2" in home.security

    def test_parse_empty(self):
        networks = _parse_scan_output("")
        assert networks == []

    def test_parse_no_header(self):
        networks = _parse_scan_output("some random text\nwithout a header")
        assert networks == []


class TestParseInfoOutput:
    def test_parse_connected(self):
        net = _parse_info_output(AIRPORT_INFO_OUTPUT)
        assert net is not None
        assert net.ssid == "HomeWifi"
        assert net.bssid == "aa:bb:cc:dd:ee:01"
        assert net.signal_dbm == -55
        assert net.noise_dbm == -88
        assert net.channel == 6
        assert net.band == "2.4 GHz"
        assert net.security == "wpa2-psk"

    def test_parse_disconnected(self):
        net = _parse_info_output(AIRPORT_INFO_DISCONNECTED)
        assert net is None

    def test_parse_empty(self):
        net = _parse_info_output("")
        assert net is None


# ---------------------------------------------------------------------------
# Function API tests (with mocked subprocess)
# ---------------------------------------------------------------------------

class TestScanWifi:
    def test_scan_returns_networks(self):
        run_fn = _make_run_fn(AIRPORT_SCAN_OUTPUT)
        networks = scan_wifi(_run_fn=run_fn)
        assert len(networks) == 5
        assert all(isinstance(n, WifiNetwork) for n in networks)

    def test_scan_empty(self):
        run_fn = _make_run_fn("")
        networks = scan_wifi(_run_fn=run_fn)
        assert networks == []


class TestCurrentConnection:
    def test_connected(self):
        run_fn = _make_run_fn(AIRPORT_INFO_OUTPUT)
        conn = current_connection(_run_fn=run_fn)
        assert conn is not None
        assert conn.ssid == "HomeWifi"

    def test_disconnected(self):
        run_fn = _make_run_fn(AIRPORT_INFO_DISCONNECTED)
        conn = current_connection(_run_fn=run_fn)
        assert conn is None


class TestDetectRogueAPs:
    def test_no_rogues_when_all_known(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        known = {"HomeWifi": ["aa:bb:cc:dd:ee:01"]}
        rogues = detect_rogue_aps(known, networks=networks)
        assert rogues == []

    def test_rogue_detected_unknown_bssid(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        # Claim HomeWifi should be at a different BSSID
        known = {"HomeWifi": ["ff:ff:ff:ff:ff:ff"]}
        rogues = detect_rogue_aps(known, networks=networks)
        assert len(rogues) == 1
        assert rogues[0].ssid == "HomeWifi"
        assert rogues[0].bssid == "aa:bb:cc:dd:ee:01"

    def test_rogue_case_insensitive_bssid(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        known = {"HomeWifi": ["AA:BB:CC:DD:EE:01"]}
        rogues = detect_rogue_aps(known, networks=networks)
        assert rogues == []

    def test_unknown_ssid_ignored(self):
        """SSIDs not in known_ssids should never be flagged."""
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        known = {"UnknownNetwork": ["aa:bb:cc:dd:ee:99"]}
        rogues = detect_rogue_aps(known, networks=networks)
        assert rogues == []

    def test_multiple_trusted_bssids(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        known = {"HomeWifi": ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:99"]}
        rogues = detect_rogue_aps(known, networks=networks)
        assert rogues == []

    def test_scans_if_no_networks_provided(self):
        run_fn = _make_run_fn(AIRPORT_SCAN_OUTPUT)
        known = {"HomeWifi": ["ff:ff:ff:ff:ff:ff"]}
        rogues = detect_rogue_aps(known, _run_fn=run_fn)
        assert len(rogues) == 1


class TestChannelUtilization:
    def test_counts_channels(self):
        networks = _parse_scan_output(AIRPORT_SCAN_OUTPUT)
        util = channel_utilization(networks)
        assert util[6] == 1   # HomeWifi on channel 6
        assert util[11] == 1  # NeighborWifi on channel 11
        assert util[1] == 1   # CoffeeShop on channel 1
        assert util[36] == 1  # Office5G on channel 36

    def test_multiple_on_same_channel(self):
        networks = [
            WifiNetwork(ssid="A", bssid="aa:aa:aa:aa:aa:01", channel=6, band="2.4 GHz", signal_dbm=-50),
            WifiNetwork(ssid="B", bssid="aa:aa:aa:aa:aa:02", channel=6, band="2.4 GHz", signal_dbm=-60),
            WifiNetwork(ssid="C", bssid="aa:aa:aa:aa:aa:03", channel=11, band="2.4 GHz", signal_dbm=-70),
        ]
        util = channel_utilization(networks)
        assert util[6] == 2
        assert util[11] == 1

    def test_empty_networks(self):
        util = channel_utilization([])
        assert util == {}

    def test_scans_if_no_networks_provided(self):
        run_fn = _make_run_fn(AIRPORT_SCAN_OUTPUT)
        util = channel_utilization(_run_fn=run_fn)
        assert len(util) > 0


# ---------------------------------------------------------------------------
# signal_bar tests
# ---------------------------------------------------------------------------

class TestSignalBar:
    def test_excellent_signal(self):
        bar = signal_bar(-40)
        assert bar == "\u2588" * 5

    def test_good_signal(self):
        bar = signal_bar(-55)
        assert bar == "\u2588" * 4 + "\u2591" * 1

    def test_fair_signal(self):
        bar = signal_bar(-65)
        assert bar == "\u2588" * 3 + "\u2591" * 2

    def test_weak_signal(self):
        bar = signal_bar(-75)
        assert bar == "\u2588" * 2 + "\u2591" * 3

    def test_very_weak_signal(self):
        bar = signal_bar(-85)
        assert bar == "\u2588" * 1 + "\u2591" * 4

    def test_no_signal(self):
        bar = signal_bar(-95)
        assert bar == "\u2591" * 5

    def test_boundary_minus_50(self):
        bar = signal_bar(-50)
        assert bar == "\u2588" * 5

    def test_boundary_minus_60(self):
        bar = signal_bar(-60)
        assert bar == "\u2588" * 4 + "\u2591" * 1

    def test_boundary_minus_70(self):
        bar = signal_bar(-70)
        assert bar == "\u2588" * 3 + "\u2591" * 2

    def test_boundary_minus_80(self):
        bar = signal_bar(-80)
        assert bar == "\u2588" * 2 + "\u2591" * 3

    def test_boundary_minus_90(self):
        bar = signal_bar(-90)
        assert bar == "\u2588" * 1 + "\u2591" * 4

    def test_bar_length_always_5(self):
        for dbm in range(-100, 0):
            assert len(signal_bar(dbm)) == 5


# ---------------------------------------------------------------------------
# CLI tests via CliRunner
# ---------------------------------------------------------------------------

class TestWifiCLI:
    def test_wifi_help(self):
        result = runner.invoke(app, ["wifi", "--help"])
        assert result.exit_code == 0
        assert "Wireless" in result.output or "wifi" in result.output.lower()

    def test_wifi_scan_cmd(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.scan_wifi",
            lambda **kwargs: _parse_scan_output(AIRPORT_SCAN_OUTPUT),
        )
        result = runner.invoke(app, ["wifi", "scan"])
        assert result.exit_code == 0
        assert "HomeWifi" in result.output
        assert "NeighborWifi" in result.output
        assert "5 networks found" in result.output

    def test_wifi_scan_sort_channel(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.scan_wifi",
            lambda **kwargs: _parse_scan_output(AIRPORT_SCAN_OUTPUT),
        )
        result = runner.invoke(app, ["wifi", "scan", "--sort", "channel"])
        assert result.exit_code == 0

    def test_wifi_scan_sort_ssid(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.scan_wifi",
            lambda **kwargs: _parse_scan_output(AIRPORT_SCAN_OUTPUT),
        )
        result = runner.invoke(app, ["wifi", "scan", "--sort", "ssid"])
        assert result.exit_code == 0

    def test_wifi_info_connected(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.current_connection",
            lambda **kwargs: _parse_info_output(AIRPORT_INFO_OUTPUT),
        )
        result = runner.invoke(app, ["wifi", "info"])
        assert result.exit_code == 0
        assert "HomeWifi" in result.output
        assert "aa:bb:cc:dd:ee:01" in result.output

    def test_wifi_info_disconnected(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.current_connection",
            lambda **kwargs: None,
        )
        result = runner.invoke(app, ["wifi", "info"])
        assert result.exit_code == 0
        assert "Not connected" in result.output

    def test_wifi_channels_cmd(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.scan_wifi",
            lambda **kwargs: _parse_scan_output(AIRPORT_SCAN_OUTPUT),
        )
        result = runner.invoke(app, ["wifi", "channels"])
        assert result.exit_code == 0
        assert "Channel" in result.output

    def test_wifi_channels_empty(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.scan_wifi",
            lambda **kwargs: [],
        )
        monkeypatch.setattr(
            "netglance.cli.wifi.channel_utilization",
            lambda networks, **kwargs: {},
        )
        result = runner.invoke(app, ["wifi", "channels"])
        assert result.exit_code == 0
        assert "No networks found" in result.output

    def test_wifi_rogues_no_rogues(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.wifi.detect_rogue_aps",
            lambda known_ssids, **kwargs: [],
        )
        result = runner.invoke(
            app,
            ["wifi", "rogues", "--ssid", "HomeWifi", "--bssid", "aa:bb:cc:dd:ee:01"],
        )
        assert result.exit_code == 0
        assert "No rogue" in result.output

    def test_wifi_rogues_found(self, monkeypatch):
        rogue = WifiNetwork(
            ssid="HomeWifi",
            bssid="ff:ff:ff:ff:ff:ff",
            channel=6,
            band="2.4 GHz",
            signal_dbm=-60,
            security="WPA2",
        )
        monkeypatch.setattr(
            "netglance.cli.wifi.detect_rogue_aps",
            lambda known_ssids, **kwargs: [rogue],
        )
        result = runner.invoke(
            app,
            ["wifi", "rogues", "--ssid", "HomeWifi", "--bssid", "aa:bb:cc:dd:ee:01"],
        )
        assert result.exit_code == 0
        assert "WARNING" in result.output
        assert "ff:ff:ff:ff:ff:ff" in result.output

    def test_wifi_scan_runtime_error(self, monkeypatch):
        def _raise(**kwargs):
            raise RuntimeError("Not macOS")
        monkeypatch.setattr("netglance.cli.wifi.scan_wifi", _raise)
        result = runner.invoke(app, ["wifi", "scan"])
        assert result.exit_code == 1
        assert "Not macOS" in result.output
