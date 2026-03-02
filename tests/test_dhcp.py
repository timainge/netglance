"""Tests for netglance.modules.dhcp and netglance.cli.dhcp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.dhcp import app
from netglance.modules.dhcp import (
    detect_rogue_servers,
    get_dhcp_fingerprint,
    monitor_dhcp,
    parse_dhcp_packet,
    sniff_dhcp,
)
from netglance.store.models import DhcpAlert, DhcpEvent


# ---------------------------------------------------------------------------
# Helpers: mock scapy packet construction
# ---------------------------------------------------------------------------

def _make_mock_packet(
    *,
    has_dhcp: bool = True,
    has_bootp: bool = True,
    has_ip: bool = True,
    has_ether: bool = True,
    msg_type: int = 1,
    ciaddr: str = "0.0.0.0",
    yiaddr: str = "0.0.0.0",
    siaddr: str = "0.0.0.0",
    chaddr: bytes = b"\xaa\xbb\xcc\xdd\xee\xff" + b"\x00" * 10,
    ip_src: str = "192.168.1.1",
    eth_src: str = "aa:bb:cc:dd:ee:ff",
    extra_options: list | None = None,
    fingerprint: bytes | None = None,
) -> MagicMock:
    """Build a mock scapy-like packet with the given fields."""
    pkt = MagicMock()

    def haslayer(layer: str) -> bool:
        return {
            "DHCP": has_dhcp,
            "BOOTP": has_bootp,
            "IP": has_ip,
            "Ether": has_ether,
        }.get(layer, False)

    pkt.haslayer = haslayer

    # BOOTP layer
    bootp = MagicMock()
    bootp.ciaddr = ciaddr
    bootp.yiaddr = yiaddr
    bootp.siaddr = siaddr
    bootp.chaddr = chaddr
    pkt.getlayer = MagicMock()

    # DHCP options list
    options = [("message-type", msg_type)]
    if extra_options:
        options.extend(extra_options)
    if fingerprint is not None:
        options.append(("param_req_list", fingerprint))
    options.append("end")

    dhcp = MagicMock()
    dhcp.options = options

    # IP layer
    ip_layer = MagicMock()
    ip_layer.src = ip_src

    # Ethernet layer
    eth_layer = MagicMock()
    eth_layer.src = eth_src

    def getlayer(layer: str):
        return {
            "BOOTP": bootp if has_bootp else None,
            "DHCP": dhcp if has_dhcp else None,
            "IP": ip_layer if has_ip else None,
            "Ether": eth_layer if has_ether else None,
        }.get(layer)

    pkt.getlayer = getlayer
    return pkt


# ---------------------------------------------------------------------------
# parse_dhcp_packet tests
# ---------------------------------------------------------------------------

class TestParseDhcpPacket:
    def test_discover_packet(self):
        """Discover packet (type 1) should produce event_type='discover'."""
        pkt = _make_mock_packet(msg_type=1)
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.event_type == "discover"
        assert event.client_mac == "aa:bb:cc:dd:ee:ff"

    def test_offer_packet(self):
        """Offer packet (type 2) should extract server_ip from IP layer."""
        pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="192.168.1.1",
        )
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.event_type == "offer"
        assert event.offered_ip == "192.168.1.100"
        assert event.server_ip == "192.168.1.1"

    def test_ack_packet_with_lease_info(self):
        """ACK packet (type 5) should extract lease time, DNS, gateway."""
        extra_opts = [
            ("router", ["192.168.1.1"]),
            ("name_server", ["8.8.8.8", "8.8.4.4"]),
            ("lease_time", 86400),
        ]
        pkt = _make_mock_packet(
            msg_type=5,
            yiaddr="192.168.1.50",
            ip_src="192.168.1.1",
            extra_options=extra_opts,
        )
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.event_type == "ack"
        assert event.offered_ip == "192.168.1.50"
        assert event.gateway == "192.168.1.1"
        assert event.dns_servers == ["8.8.8.8", "8.8.4.4"]
        assert event.lease_time == 86400

    def test_nak_packet(self):
        """NAK packet (type 6) should produce event_type='nak'."""
        pkt = _make_mock_packet(msg_type=6, ip_src="192.168.1.1")
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.event_type == "nak"

    def test_request_packet(self):
        """Request packet (type 3) should produce event_type='request'."""
        pkt = _make_mock_packet(msg_type=3)
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.event_type == "request"

    def test_no_dhcp_layer_returns_none(self):
        """Packets without DHCP layer should return None."""
        pkt = _make_mock_packet(has_dhcp=False)
        result = parse_dhcp_packet(pkt)
        assert result is None

    def test_no_bootp_layer_returns_none(self):
        """Packets without BOOTP layer should return None."""
        pkt = _make_mock_packet(has_bootp=False)
        result = parse_dhcp_packet(pkt)
        assert result is None

    def test_exception_returns_none(self):
        """Malformed packets that raise exceptions should return None."""
        bad_pkt = MagicMock()
        bad_pkt.haslayer = MagicMock(side_effect=RuntimeError("boom"))
        result = parse_dhcp_packet(bad_pkt)
        assert result is None

    def test_client_ip_extracted_from_ciaddr(self):
        """ciaddr should be used as client_ip when non-zero."""
        pkt = _make_mock_packet(msg_type=3, ciaddr="10.0.0.5")
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.client_ip == "10.0.0.5"

    def test_zero_ciaddr_gives_none_client_ip(self):
        """0.0.0.0 ciaddr should result in client_ip=None."""
        pkt = _make_mock_packet(msg_type=1, ciaddr="0.0.0.0")
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.client_ip is None

    def test_dns_single_server(self):
        """Single DNS server (non-list) should be stored as a list."""
        pkt = _make_mock_packet(
            msg_type=5,
            extra_options=[("name_server", "1.1.1.1")],
        )
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.dns_servers == ["1.1.1.1"]

    def test_gateway_single_value(self):
        """Single router value (non-list) should be stored as gateway."""
        pkt = _make_mock_packet(
            msg_type=5,
            extra_options=[("router", "10.0.0.1")],
        )
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.gateway == "10.0.0.1"

    def test_server_mac_from_ethernet_on_offer(self):
        """Server MAC should be extracted from Ethernet src on Offer."""
        pkt = _make_mock_packet(
            msg_type=2,
            ip_src="192.168.1.1",
            eth_src="11:22:33:44:55:66",
        )
        event = parse_dhcp_packet(pkt)
        assert event is not None
        assert event.server_mac == "11:22:33:44:55:66"

    def test_timestamp_is_recent(self):
        """Parsed events should have a recent timestamp."""
        before = datetime.now()
        pkt = _make_mock_packet(msg_type=1)
        event = parse_dhcp_packet(pkt)
        after = datetime.now()
        assert event is not None
        assert before <= event.timestamp <= after


# ---------------------------------------------------------------------------
# detect_rogue_servers tests
# ---------------------------------------------------------------------------

def _make_event(
    event_type: str,
    server_ip: str,
    server_mac: str = "aa:bb:cc:00:00:01",
) -> DhcpEvent:
    return DhcpEvent(
        event_type=event_type,
        client_mac="de:ad:be:ef:00:01",
        server_ip=server_ip,
        server_mac=server_mac,
    )


class TestDetectRogueServers:
    def test_empty_events_returns_no_alerts(self):
        result = detect_rogue_servers([])
        assert result == []

    def test_all_events_from_expected_server_no_alerts(self):
        events = [
            _make_event("offer", "192.168.1.1"),
            _make_event("ack", "192.168.1.1"),
        ]
        alerts = detect_rogue_servers(events, expected_servers=["192.168.1.1"])
        assert alerts == []

    def test_rogue_server_detected(self):
        events = [
            _make_event("offer", "192.168.1.1"),
            _make_event("offer", "10.0.0.99"),
        ]
        alerts = detect_rogue_servers(events, expected_servers=["192.168.1.1"])
        assert len(alerts) == 1
        assert alerts[0].alert_type == "rogue_server"
        assert alerts[0].severity == "critical"
        assert "10.0.0.99" in alerts[0].description
        assert alerts[0].server_ip == "10.0.0.99"

    def test_auto_detect_flags_minority_server(self):
        """Auto-detect: most common server is expected, others are flagged."""
        events = [
            _make_event("offer", "192.168.1.1"),
            _make_event("ack", "192.168.1.1"),
            _make_event("offer", "192.168.1.1"),
            _make_event("offer", "10.0.0.99"),  # rogue
        ]
        alerts = detect_rogue_servers(events, expected_servers=None)
        assert len(alerts) == 1
        assert alerts[0].server_ip == "10.0.0.99"

    def test_auto_detect_no_server_events_returns_empty(self):
        """Discover/Request events (no server_ip context) should not cause alerts."""
        events = [
            _make_event("discover", ""),
            _make_event("request", ""),
        ]
        # No server_ip in these events, so nothing to flag
        alerts = detect_rogue_servers(events, expected_servers=None)
        assert alerts == []

    def test_only_discover_events_no_alerts(self):
        """Only discover/request events (non-server types) produce no alerts."""
        events = [
            DhcpEvent(event_type="discover", client_mac="aa:bb:cc:00:00:01"),
            DhcpEvent(event_type="request", client_mac="aa:bb:cc:00:00:01"),
        ]
        alerts = detect_rogue_servers(events)
        assert alerts == []

    def test_deduplication_same_rogue_not_alerted_twice(self):
        """Same rogue server IP should only generate one alert."""
        events = [
            _make_event("offer", "10.0.0.99"),
            _make_event("ack", "10.0.0.99"),
        ]
        alerts = detect_rogue_servers(events, expected_servers=["192.168.1.1"])
        assert len(alerts) == 1

    def test_multiple_rogues(self):
        """Multiple distinct rogue servers each generate their own alert."""
        events = [
            _make_event("offer", "10.0.0.99"),
            _make_event("offer", "172.16.0.5"),
        ]
        alerts = detect_rogue_servers(events, expected_servers=["192.168.1.1"])
        assert len(alerts) == 2
        ips = {a.server_ip for a in alerts}
        assert ips == {"10.0.0.99", "172.16.0.5"}


# ---------------------------------------------------------------------------
# get_dhcp_fingerprint tests
# ---------------------------------------------------------------------------

class TestGetDhcpFingerprint:
    def test_returns_fingerprint_string_from_bytes(self):
        """Option 55 as bytes should return comma-separated numbers."""
        pkt = _make_mock_packet(msg_type=1, fingerprint=b"\x01\x03\x06\x0f\x1c\x33\x3a\x3b")
        fp = get_dhcp_fingerprint(pkt)
        assert fp == "1,3,6,15,28,51,58,59"

    def test_returns_none_when_option_55_absent(self):
        """Packets without option 55 should return None."""
        pkt = _make_mock_packet(msg_type=1, fingerprint=None)
        fp = get_dhcp_fingerprint(pkt)
        assert fp is None

    def test_no_dhcp_layer_returns_none(self):
        """Non-DHCP packets should return None."""
        pkt = _make_mock_packet(has_dhcp=False)
        fp = get_dhcp_fingerprint(pkt)
        assert fp is None

    def test_exception_returns_none(self):
        """Exception in fingerprint extraction should return None."""
        bad_pkt = MagicMock()
        bad_pkt.haslayer = MagicMock(side_effect=RuntimeError("boom"))
        result = get_dhcp_fingerprint(bad_pkt)
        assert result is None

    def test_fingerprint_with_list_values(self):
        """Option 55 as a list of ints should return comma-separated string."""
        pkt = _make_mock_packet(msg_type=1)
        # Override to inject list fingerprint
        dhcp_layer = pkt.getlayer("DHCP")
        dhcp_layer.options = [
            ("message-type", 1),
            ("param_req_list", [1, 3, 6, 15]),
            "end",
        ]
        fp = get_dhcp_fingerprint(pkt)
        assert fp == "1,3,6,15"


# ---------------------------------------------------------------------------
# sniff_dhcp tests
# ---------------------------------------------------------------------------

class TestSniffDhcp:
    def test_sniff_with_mock_fn_returns_events(self):
        """sniff_dhcp should parse packets returned by _sniff_fn."""
        pkt1 = _make_mock_packet(msg_type=1)
        pkt2 = _make_mock_packet(msg_type=2, yiaddr="192.168.1.100", ip_src="192.168.1.1")

        def mock_sniff(filter, timeout, iface):
            return [pkt1, pkt2]

        events = sniff_dhcp(timeout=5.0, _sniff_fn=mock_sniff)
        assert len(events) == 2
        assert events[0].event_type == "discover"
        assert events[1].event_type == "offer"

    def test_sniff_filters_invalid_packets(self):
        """Non-DHCP packets returned by _sniff_fn should be filtered out."""
        valid = _make_mock_packet(msg_type=1)
        invalid = _make_mock_packet(has_dhcp=False)

        def mock_sniff(filter, timeout, iface):
            return [valid, invalid]

        events = sniff_dhcp(timeout=5.0, _sniff_fn=mock_sniff)
        assert len(events) == 1

    def test_sniff_empty_capture(self):
        """Empty packet list should return empty event list."""
        events = sniff_dhcp(timeout=1.0, _sniff_fn=lambda **kw: [])
        assert events == []

    def test_sniff_passes_interface(self):
        """Interface parameter should be passed to _sniff_fn."""
        calls = []

        def mock_sniff(filter, timeout, iface):
            calls.append(iface)
            return []

        sniff_dhcp(timeout=1.0, interface="eth0", _sniff_fn=mock_sniff)
        assert calls == ["eth0"]

    def test_sniff_passes_timeout(self):
        """Timeout parameter should be passed to _sniff_fn."""
        calls = []

        def mock_sniff(filter, timeout, iface):
            calls.append(timeout)
            return []

        sniff_dhcp(timeout=42.0, _sniff_fn=mock_sniff)
        assert calls == [42.0]


# ---------------------------------------------------------------------------
# monitor_dhcp tests
# ---------------------------------------------------------------------------

class TestMonitorDhcp:
    def test_monitor_returns_events_and_alerts(self):
        """monitor_dhcp should return events and any alerts."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="10.0.0.99",
            eth_src="de:ad:be:ef:00:01",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        events, alerts = monitor_dhcp(
            duration=5.0,
            expected_servers=["192.168.1.1"],
            _sniff_fn=mock_sniff,
        )
        assert len(events) == 1
        assert len(alerts) == 1
        assert alerts[0].alert_type == "rogue_server"

    def test_monitor_no_alerts_for_expected_server(self):
        """No alerts when all DHCP events come from an expected server."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="192.168.1.1",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        events, alerts = monitor_dhcp(
            duration=5.0,
            expected_servers=["192.168.1.1"],
            _sniff_fn=mock_sniff,
        )
        assert len(events) == 1
        assert alerts == []

    def test_monitor_empty_capture(self):
        """Empty capture should return empty events and alerts."""
        events, alerts = monitor_dhcp(
            duration=1.0,
            _sniff_fn=lambda **kw: [],
        )
        assert events == []
        assert alerts == []


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

runner = CliRunner()


class TestCli:
    def test_monitor_cmd_no_packets(self):
        """monitor command with no packets should indicate no events."""
        with patch("netglance.modules.dhcp._default_sniff_fn", return_value=[]):
            result = runner.invoke(app, ["monitor", "--duration", "1"])
        assert result.exit_code == 0
        assert "No DHCP events captured" in result.output

    def test_monitor_cmd_with_events(self):
        """monitor command should display event table when packets captured."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="192.168.1.1",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["monitor", "--duration", "1"])
        assert result.exit_code == 0
        assert "OFFER" in result.output

    def test_monitor_cmd_json_output(self):
        """monitor --json should output valid JSON."""
        import json

        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="192.168.1.1",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["monitor", "--duration", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "events" in data
        assert "alerts" in data

    def test_check_cmd_no_rogues(self):
        """check command with no rogues should exit 0 and print clean message."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="192.168.1.1",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["check", "--expected", "192.168.1.1"])
        assert result.exit_code == 0
        assert "No rogue DHCP servers detected" in result.output

    def test_check_cmd_rogue_detected_exits_1(self):
        """check command with rogue server should exit code 1."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="10.0.0.99",
            eth_src="de:ad:be:ef:00:01",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["check", "--expected", "192.168.1.1"])
        assert result.exit_code == 1
        assert "ALERT" in result.output

    def test_leases_cmd_no_events(self):
        """leases command with no packets should print no leases message."""
        with patch("netglance.modules.dhcp._default_sniff_fn", return_value=[]):
            result = runner.invoke(app, ["leases", "--duration", "1"])
        assert result.exit_code == 0
        assert "No DHCP leases observed" in result.output

    def test_leases_cmd_with_ack_event(self):
        """leases command should display ACK events as leases."""
        extra_opts = [
            ("router", ["192.168.1.1"]),
            ("name_server", ["8.8.8.8"]),
            ("lease_time", 3600),
        ]
        ack_pkt = _make_mock_packet(
            msg_type=5,
            yiaddr="192.168.1.50",
            ip_src="192.168.1.1",
            extra_options=extra_opts,
        )

        def mock_sniff(filter, timeout, iface):
            return [ack_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["leases", "--duration", "1"])
        assert result.exit_code == 0
        # Table should render with lease data (3600s lease time is distinctive)
        assert "3600s" in result.output

    def test_leases_cmd_json_output(self):
        """leases --json should output valid JSON array."""
        import json

        ack_pkt = _make_mock_packet(
            msg_type=5,
            yiaddr="192.168.1.50",
            ip_src="192.168.1.1",
        )

        def mock_sniff(filter, timeout, iface):
            return [ack_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(app, ["leases", "--duration", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["assigned_ip"] == "192.168.1.50"

    def test_monitor_rogue_alert_shown(self):
        """monitor command should display alert panel for rogue servers."""
        offer_pkt = _make_mock_packet(
            msg_type=2,
            yiaddr="192.168.1.100",
            ip_src="10.0.0.99",
            eth_src="de:ad:be:ef:00:01",
        )

        def mock_sniff(filter, timeout, iface):
            return [offer_pkt]

        with patch("netglance.modules.dhcp._default_sniff_fn", mock_sniff):
            result = runner.invoke(
                app,
                ["monitor", "--duration", "1", "--expected", "192.168.1.1"],
            )
        assert result.exit_code == 0
        assert "ALERT" in result.output
        assert "10.0.0.99" in result.output
