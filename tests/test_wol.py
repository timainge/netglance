"""Tests for Wake-on-LAN module and CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from netglance.cli.wol import app
from netglance.modules.wol import (
    _is_mac_address,
    _normalize_mac,
    build_magic_packet,
    send_wol,
    wake_device,
)
from netglance.store.models import WolResult


# ---------------------------------------------------------------------------
# build_magic_packet — structure tests
# ---------------------------------------------------------------------------


class TestBuildMagicPacket:
    def test_colon_format_produces_102_bytes(self):
        packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
        assert len(packet) == 102

    def test_dash_format_produces_102_bytes(self):
        packet = build_magic_packet("AA-BB-CC-DD-EE-FF")
        assert len(packet) == 102

    def test_plain_format_produces_102_bytes(self):
        packet = build_magic_packet("AABBCCDDEEFF")
        assert len(packet) == 102

    def test_starts_with_six_ff_bytes(self):
        packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
        assert packet[:6] == b"\xff\xff\xff\xff\xff\xff"

    def test_mac_repeated_16_times(self):
        packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
        mac_bytes = bytes.fromhex("AABBCCDDEEFF")
        # bytes 6..102 should be 16 copies of mac_bytes
        assert packet[6:] == mac_bytes * 16

    def test_lowercase_colon_mac(self):
        packet = build_magic_packet("aa:bb:cc:dd:ee:ff")
        assert len(packet) == 102
        assert packet[:6] == b"\xff" * 6

    def test_lowercase_dash_mac(self):
        packet = build_magic_packet("aa-bb-cc-dd-ee-ff")
        mac_bytes = bytes.fromhex("aabbccddeeff")
        assert packet[6:] == mac_bytes * 16

    def test_lowercase_plain_mac(self):
        packet = build_magic_packet("aabbccddeeff")
        assert len(packet) == 102

    def test_invalid_mac_raises_value_error(self):
        with pytest.raises(ValueError):
            build_magic_packet("ZZ:BB:CC:DD:EE:FF")

    def test_too_short_mac_raises_value_error(self):
        with pytest.raises(ValueError):
            build_magic_packet("AA:BB:CC")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            build_magic_packet("")

    def test_wrong_separator_raises_value_error(self):
        with pytest.raises(ValueError):
            build_magic_packet("AA.BB.CC.DD.EE.FF")

    def test_different_macs_produce_different_packets(self):
        p1 = build_magic_packet("AA:BB:CC:DD:EE:FF")
        p2 = build_magic_packet("11:22:33:44:55:66")
        assert p1 != p2
        # Both start with the same 6 FF bytes
        assert p1[:6] == p2[:6] == b"\xff" * 6

    def test_packet_payload_matches_expected_bytes(self):
        # Verify exact byte values for a known MAC
        mac = "01:23:45:67:89:AB"
        packet = build_magic_packet(mac)
        expected_mac_bytes = bytes([0x01, 0x23, 0x45, 0x67, 0x89, 0xAB])
        assert packet[6:12] == expected_mac_bytes
        assert packet[12:18] == expected_mac_bytes


# ---------------------------------------------------------------------------
# _normalize_mac / _is_mac_address helpers
# ---------------------------------------------------------------------------


class TestNormalizeMac:
    def test_colon_format_normalized(self):
        assert _normalize_mac("aa:bb:cc:dd:ee:ff") == "AABBCCDDEEFF"

    def test_dash_format_normalized(self):
        assert _normalize_mac("AA-BB-CC-DD-EE-FF") == "AABBCCDDEEFF"

    def test_plain_format_normalized(self):
        assert _normalize_mac("aAbBcCdDeEfF") == "AABBCCDDEEFF"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _normalize_mac("not-a-mac")


class TestIsMacAddress:
    def test_colon_mac_detected(self):
        assert _is_mac_address("AA:BB:CC:DD:EE:FF") is True

    def test_dash_mac_detected(self):
        assert _is_mac_address("AA-BB-CC-DD-EE-FF") is True

    def test_plain_mac_detected(self):
        assert _is_mac_address("AABBCCDDEEFF") is True

    def test_hostname_not_detected(self):
        assert _is_mac_address("my-nas") is False

    def test_ip_not_detected(self):
        assert _is_mac_address("192.168.1.1") is False


# ---------------------------------------------------------------------------
# send_wol — dependency injection tests
# ---------------------------------------------------------------------------


class TestSendWol:
    def test_calls_socket_fn_with_correct_args(self):
        sent_calls = []

        def fake_socket(packet, broadcast, port):
            sent_calls.append((packet, broadcast, port))

        result = send_wol("AA:BB:CC:DD:EE:FF", _socket_fn=fake_socket)
        assert len(sent_calls) == 1
        _, broadcast, port = sent_calls[0]
        assert broadcast == "255.255.255.255"
        assert port == 9

    def test_returns_wol_result_with_sent_true(self):
        result = send_wol("AA:BB:CC:DD:EE:FF", _socket_fn=lambda *a: None)
        assert isinstance(result, WolResult)
        assert result.sent is True

    def test_result_mac_matches_input(self):
        result = send_wol("AA:BB:CC:DD:EE:FF", _socket_fn=lambda *a: None)
        assert result.mac == "AA:BB:CC:DD:EE:FF"

    def test_custom_broadcast_passed_through(self):
        captured = {}

        def fake_socket(packet, broadcast, port):
            captured["broadcast"] = broadcast

        send_wol("AA:BB:CC:DD:EE:FF", broadcast="192.168.1.255", _socket_fn=fake_socket)
        assert captured["broadcast"] == "192.168.1.255"

    def test_custom_port_passed_through(self):
        captured = {}

        def fake_socket(packet, broadcast, port):
            captured["port"] = port

        send_wol("AA:BB:CC:DD:EE:FF", port=7, _socket_fn=fake_socket)
        assert captured["port"] == 7

    def test_socket_error_returns_sent_false(self):
        def bad_socket(packet, broadcast, port):
            raise OSError("network unreachable")

        result = send_wol("AA:BB:CC:DD:EE:FF", _socket_fn=bad_socket)
        assert result.sent is False

    def test_correct_packet_sent_to_socket(self):
        packets = []

        def fake_socket(packet, broadcast, port):
            packets.append(packet)

        send_wol("11:22:33:44:55:66", _socket_fn=fake_socket)
        expected = build_magic_packet("11:22:33:44:55:66")
        assert packets[0] == expected

    def test_result_broadcast_and_port_stored(self):
        result = send_wol(
            "AA:BB:CC:DD:EE:FF",
            broadcast="10.0.0.255",
            port=7,
            _socket_fn=lambda *a: None,
        )
        assert result.broadcast == "10.0.0.255"
        assert result.port == 7


# ---------------------------------------------------------------------------
# wake_device — inventory lookup tests
# ---------------------------------------------------------------------------


class TestWakeDevice:
    INVENTORY = [
        {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "NAS", "ip": "192.168.1.100"},
        {"mac": "11:22:33:44:55:66", "hostname": "printer", "ip": "192.168.1.101"},
    ]

    def test_mac_address_input_sends_directly(self):
        captured = {}

        def fake_socket(packet, broadcast, port):
            captured["called"] = True

        result = wake_device(
            "AA:BB:CC:DD:EE:FF",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=fake_socket,
        )
        assert result.sent is True
        assert captured.get("called") is True

    def test_device_name_found_in_inventory(self):
        macs_used = []

        def fake_socket(packet, broadcast, port):
            macs_used.append(packet)

        result = wake_device(
            "NAS",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=fake_socket,
        )
        assert result.sent is True
        expected_packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
        assert macs_used[0] == expected_packet

    def test_device_name_case_insensitive(self):
        result = wake_device(
            "nas",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=lambda *a: None,
        )
        assert result.sent is True

    def test_device_name_sets_device_name_field(self):
        result = wake_device(
            "NAS",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=lambda *a: None,
        )
        assert result.device_name == "NAS"

    def test_mac_input_does_not_set_device_name(self):
        result = wake_device(
            "AA:BB:CC:DD:EE:FF",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=lambda *a: None,
        )
        # When using a MAC directly, device_name remains None
        assert result.device_name is None

    def test_device_not_found_raises_value_error(self):
        with pytest.raises(ValueError, match="not found in inventory"):
            wake_device(
                "UnknownDevice",
                _store_fn=lambda: self.INVENTORY,
                _socket_fn=lambda *a: None,
            )

    def test_empty_inventory_raises_value_error(self):
        with pytest.raises(ValueError):
            wake_device(
                "NAS",
                _store_fn=lambda: [],
                _socket_fn=lambda *a: None,
            )

    def test_second_device_found(self):
        result = wake_device(
            "printer",
            _store_fn=lambda: self.INVENTORY,
            _socket_fn=lambda *a: None,
        )
        assert result.sent is True
        assert build_magic_packet("11:22:33:44:55:66") == build_magic_packet(result.mac)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


runner = CliRunner()


class TestWolCli:
    def test_send_subcommand_success(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "send_wol",
            lambda mac, broadcast, port: WolResult(
                mac=mac, broadcast=broadcast, port=port, sent=True
            ),
        )
        result = runner.invoke(app, ["send", "AA:BB:CC:DD:EE:FF"])
        assert result.exit_code == 0
        assert "AA:BB:CC:DD:EE:FF" in result.output

    def test_send_subcommand_json_output(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "send_wol",
            lambda mac, broadcast, port: WolResult(
                mac=mac, broadcast=broadcast, port=port, sent=True
            ),
        )
        result = runner.invoke(app, ["send", "AA:BB:CC:DD:EE:FF", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mac"] == "AA:BB:CC:DD:EE:FF"
        assert data["sent"] is True

    def test_send_subcommand_invalid_mac(self):
        result = runner.invoke(app, ["send", "NOT-A-MAC"])
        assert result.exit_code != 0

    def test_wake_subcommand_success(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "wake_device",
            lambda name, broadcast, port: WolResult(
                mac="AA:BB:CC:DD:EE:FF",
                broadcast=broadcast,
                port=port,
                sent=True,
                device_name=name,
            ),
        )
        result = runner.invoke(app, ["wake", "NAS"])
        assert result.exit_code == 0
        assert "NAS" in result.output or "AA:BB:CC:DD:EE:FF" in result.output

    def test_wake_subcommand_not_found(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        def raise_not_found(name, broadcast, port):
            raise ValueError(f"Device {name!r} not found in inventory.")

        monkeypatch.setattr(cli_wol, "wake_device", raise_not_found)
        result = runner.invoke(app, ["wake", "UnknownDevice"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "Error" in result.output

    def test_send_failure_exit_code_nonzero(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "send_wol",
            lambda mac, broadcast, port: WolResult(
                mac=mac, broadcast=broadcast, port=port, sent=False
            ),
        )
        result = runner.invoke(app, ["send", "AA:BB:CC:DD:EE:FF"])
        assert result.exit_code != 0

    def test_panel_shows_broadcast_address(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "send_wol",
            lambda mac, broadcast, port: WolResult(
                mac=mac, broadcast=broadcast, port=port, sent=True
            ),
        )
        result = runner.invoke(
            app, ["send", "AA:BB:CC:DD:EE:FF", "--broadcast", "192.168.1.255"]
        )
        assert result.exit_code == 0
        assert "192.168.1.255" in result.output

    def test_wake_json_output(self, monkeypatch):
        import netglance.cli.wol as cli_wol

        monkeypatch.setattr(
            cli_wol,
            "wake_device",
            lambda name, broadcast, port: WolResult(
                mac="AA:BB:CC:DD:EE:FF",
                broadcast=broadcast,
                port=port,
                sent=True,
                device_name=name,
            ),
        )
        result = runner.invoke(app, ["wake", "NAS", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["sent"] is True
        assert data["device_name"] == "NAS"
