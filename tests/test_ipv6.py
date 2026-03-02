"""Tests for the IPv6 module."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from netglance.modules.ipv6 import (
    check_ipv6_dns_leak,
    check_privacy_extensions,
    classify_ipv6_address,
    discover_ipv6_neighbors,
    run_ipv6_audit,
)
from netglance.store.models import IPv6AuditResult, IPv6Neighbor


# ---------------------------------------------------------------------------
# classify_ipv6_address
# ---------------------------------------------------------------------------


class TestClassifyIPv6Address:
    def test_loopback(self):
        assert classify_ipv6_address("::1") == "loopback"

    def test_link_local(self):
        assert classify_ipv6_address("fe80::1") == "link-local"

    def test_link_local_full(self):
        assert classify_ipv6_address("fe80::aabb:ccdd:eeff:1234") == "link-local"

    def test_multicast_all_nodes(self):
        assert classify_ipv6_address("ff02::1") == "multicast"

    def test_multicast_all_routers(self):
        assert classify_ipv6_address("ff02::2") == "multicast"

    def test_eui64_global(self):
        # ff:fe bytes at positions 11-12 indicate EUI-64 derivation
        assert classify_ipv6_address("2001:db8::aabb:ccff:fedd:eeff") == "eui64"

    def test_global_non_eui64(self):
        assert classify_ipv6_address("2001:db8::1") == "temporary"

    def test_unique_local_fc(self):
        assert classify_ipv6_address("fc00::1") == "unique-local"

    def test_unique_local_fd(self):
        assert classify_ipv6_address("fd00::1") == "unique-local"

    def test_invalid_address(self):
        assert classify_ipv6_address("not-an-address") == "unknown"

    def test_another_temporary_global(self):
        # Random-looking global with no ff:fe pattern
        assert classify_ipv6_address("2600:1700:1234:5678::1") == "temporary"

    def test_global_2000(self):
        # 2000:: itself has no interface ID — positions 11-12 are both 0
        assert classify_ipv6_address("2000::1") == "temporary"


# ---------------------------------------------------------------------------
# discover_ipv6_neighbors
# ---------------------------------------------------------------------------


class TestDiscoverIPv6Neighbors:
    def test_returns_neighbors_from_mock(self):
        mock_send = MagicMock(
            return_value=[
                ("fe80::1", "aa:bb:cc:dd:ee:ff"),
                ("2001:db8::aabb:ccff:fedd:1234", "11:22:33:44:55:66"),
            ]
        )
        result = discover_ipv6_neighbors(_send_fn=mock_send)

        assert len(result) == 2
        assert isinstance(result[0], IPv6Neighbor)
        assert result[0].ipv6_address == "fe80::1"
        assert result[0].mac == "aa:bb:cc:dd:ee:ff"
        assert result[0].address_type == "link-local"

    def test_eui64_neighbor_classified(self):
        mock_send = MagicMock(
            return_value=[("2001:db8::aabb:ccff:fedd:eeff", "aa:bb:cc:dd:ee:ff")]
        )
        result = discover_ipv6_neighbors(_send_fn=mock_send)
        assert result[0].address_type == "eui64"

    def test_empty_result(self):
        mock_send = MagicMock(return_value=[])
        result = discover_ipv6_neighbors(_send_fn=mock_send)
        assert result == []

    def test_interface_passed_to_send_fn(self):
        mock_send = MagicMock(return_value=[])
        discover_ipv6_neighbors(interface="en0", timeout=3.0, _send_fn=mock_send)
        mock_send.assert_called_once_with("en0", 3.0)

    def test_interface_stored_on_neighbor(self):
        mock_send = MagicMock(return_value=[("fe80::1", "aa:bb:cc:dd:ee:ff")])
        result = discover_ipv6_neighbors(interface="eth0", _send_fn=mock_send)
        assert result[0].interface == "eth0"

    def test_none_interface_stored_as_empty(self):
        mock_send = MagicMock(return_value=[("fe80::1", "aa:bb:cc:dd:ee:ff")])
        result = discover_ipv6_neighbors(interface=None, _send_fn=mock_send)
        assert result[0].interface == ""


# ---------------------------------------------------------------------------
# check_privacy_extensions
# ---------------------------------------------------------------------------


AF6 = socket.AF_INET6
AF4 = socket.AF_INET


def _make_ifaces(**kwargs) -> dict:
    """Helper: build interface dict with IPv6 entries."""
    return kwargs


class TestCheckPrivacyExtensions:
    def test_only_eui64_addresses(self):
        ifaces = {
            "en0": [
                {"family": AF6, "address": "2001:db8::aabb:ccff:fedd:eeff", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is False
        assert has_eui64 is True

    def test_only_temporary_addresses(self):
        ifaces = {
            "en0": [
                {"family": AF6, "address": "2001:db8::1234:5678", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is True
        assert has_eui64 is False

    def test_both_eui64_and_temporary(self):
        ifaces = {
            "en0": [
                {"family": AF6, "address": "2001:db8::aabb:ccff:fedd:eeff", "netmask": None},
                {"family": AF6, "address": "2001:db8::1234:5678", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is True
        assert has_eui64 is True

    def test_no_ipv6_addresses(self):
        ifaces = {
            "en0": [
                {"family": AF4, "address": "192.168.1.1", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is False
        assert has_eui64 is False

    def test_link_local_only_not_counted(self):
        ifaces = {
            "en0": [
                {"family": AF6, "address": "fe80::1", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is False
        assert has_eui64 is False

    def test_address_with_interface_suffix_stripped(self):
        ifaces = {
            "en0": [
                # macOS appends %en0 to link-local
                {"family": AF6, "address": "2001:db8::1234:5678%en0", "netmask": None},
            ]
        }
        has_privacy, has_eui64 = check_privacy_extensions(_interfaces_fn=lambda: ifaces)
        assert has_privacy is True


# ---------------------------------------------------------------------------
# check_ipv6_dns_leak
# ---------------------------------------------------------------------------


class TestCheckIPv6DnsLeak:
    def test_no_vpn_returns_none(self):
        result = check_ipv6_dns_leak(
            _vpn_detect_fn=lambda: False,
            _resolve_fn=lambda h, t: [],
        )
        assert result is None

    def test_vpn_with_global_ipv6_returns_true(self):
        result = check_ipv6_dns_leak(
            _vpn_detect_fn=lambda: True,
            _resolve_fn=lambda h, t: ["2001:4860:4860::8888"],
        )
        assert result is True

    def test_vpn_no_ipv6_answers_returns_false(self):
        result = check_ipv6_dns_leak(
            _vpn_detect_fn=lambda: True,
            _resolve_fn=lambda h, t: [],
        )
        assert result is False

    def test_vpn_only_link_local_returns_false(self):
        result = check_ipv6_dns_leak(
            _vpn_detect_fn=lambda: True,
            _resolve_fn=lambda h, t: ["fe80::1"],
        )
        assert result is False

    def test_vpn_with_invalid_address_skips(self):
        result = check_ipv6_dns_leak(
            _vpn_detect_fn=lambda: True,
            _resolve_fn=lambda h, t: ["not-an-ip"],
        )
        assert result is False


# ---------------------------------------------------------------------------
# run_ipv6_audit
# ---------------------------------------------------------------------------


class TestRunIPv6Audit:
    def _make_interfaces(self, include_global_v4=True, include_global_v6=True):
        ifaces = {}
        addrs = []
        if include_global_v4:
            addrs.append({"family": AF4, "address": "8.8.8.8", "netmask": None})
        if include_global_v6:
            addrs.append({"family": AF6, "address": "2600:1700:1::1234:5678", "netmask": None})
        ifaces["en0"] = addrs
        return ifaces

    def test_returns_ipv6_audit_result(self):
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: {},
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert isinstance(result, IPv6AuditResult)

    def test_dual_stack_detected(self):
        ifaces = self._make_interfaces(include_global_v4=True, include_global_v6=True)
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: ifaces,
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert result.dual_stack is True

    def test_not_dual_stack_without_global_ipv6(self):
        ifaces = self._make_interfaces(include_global_v4=True, include_global_v6=False)
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: ifaces,
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert result.dual_stack is False

    def test_neighbors_included(self):
        mock_send = MagicMock(return_value=[("fe80::1", "aa:bb:cc:dd:ee:ff")])
        result = run_ipv6_audit(
            _send_fn=mock_send,
            _interfaces_fn=lambda: {},
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert len(result.neighbors) == 1
        assert result.neighbors[0].ipv6_address == "fe80::1"

    def test_local_addresses_populated(self):
        ifaces = {"en0": [{"family": AF6, "address": "fe80::1", "netmask": None}]}
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: ifaces,
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert len(result.local_addresses) == 1
        assert result.local_addresses[0]["address"] == "fe80::1"

    def test_privacy_extensions_reflected(self):
        ifaces = {
            "en0": [
                {"family": AF6, "address": "2001:db8::1234:5678", "netmask": None},
            ]
        }
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: ifaces,
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert result.privacy_extensions is True
        assert result.eui64_exposed is False

    def test_dns_leak_none_when_no_vpn(self):
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: {},
            _resolve_fn=lambda h, t: [],
            _vpn_detect_fn=lambda: False,
        )
        assert result.ipv6_dns_leak is None

    def test_dns_leak_true_when_vpn_and_global_answer(self):
        result = run_ipv6_audit(
            _send_fn=lambda i, t: [],
            _interfaces_fn=lambda: {},
            _resolve_fn=lambda h, t: ["2001:4860:4860::8888"],
            _vpn_detect_fn=lambda: True,
        )
        assert result.ipv6_dns_leak is True


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_audit_json_output(self):
        from typer.testing import CliRunner
        from netglance.cli.ipv6 import app

        runner = CliRunner()

        with (
            patch("netglance.modules.ipv6._default_send_fn", return_value=[]),
            patch(
                "netglance.modules.ipv6._default_interfaces_fn",
                return_value={},
            ),
            patch("netglance.modules.ipv6._default_resolve_fn", return_value=[]),
            patch("netglance.modules.ipv6._detect_vpn_interface", return_value=False),
        ):
            result = runner.invoke(app, ["audit", "--json"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "neighbors" in data
        assert "dual_stack" in data

    def test_neighbors_no_results(self):
        from typer.testing import CliRunner
        from netglance.cli.ipv6 import app

        runner = CliRunner()

        with patch("netglance.modules.ipv6._default_send_fn", return_value=[]):
            result = runner.invoke(app, ["neighbors"])

        assert result.exit_code == 0
        assert "No IPv6 neighbors" in result.output

    def test_addresses_command(self):
        from typer.testing import CliRunner
        from netglance.cli.ipv6 import app

        runner = CliRunner()

        mock_ifaces = {
            "lo0": [{"family": socket.AF_INET6, "address": "::1", "netmask": None}]
        }

        with patch("netglance.modules.ipv6._default_interfaces_fn", return_value=mock_ifaces):
            result = runner.invoke(app, ["addresses"])

        assert result.exit_code == 0

    def test_audit_table_output(self):
        from typer.testing import CliRunner
        from netglance.cli.ipv6 import app

        runner = CliRunner()

        with (
            patch("netglance.modules.ipv6._default_send_fn", return_value=[]),
            patch(
                "netglance.modules.ipv6._default_interfaces_fn",
                return_value={
                    "en0": [{"family": socket.AF_INET6, "address": "fe80::1", "netmask": None}]
                },
            ),
            patch("netglance.modules.ipv6._default_resolve_fn", return_value=[]),
            patch("netglance.modules.ipv6._detect_vpn_interface", return_value=False),
        ):
            result = runner.invoke(app, ["audit"])

        assert result.exit_code == 0
        assert "IPv6 Audit Summary" in result.output
