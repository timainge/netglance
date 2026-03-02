"""Tests for the vpn module."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from netglance.cli.vpn import app
from netglance.modules.vpn import (
    VPN_INTERFACE_PATTERNS,
    check_dns_leak,
    check_ipv6_leak,
    check_split_tunnel,
    detect_vpn_interface,
    run_vpn_leak_check,
)
from netglance.store.models import VpnLeakReport

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_addr(family: int, address: str) -> SimpleNamespace:
    return SimpleNamespace(family=family, address=address)


AF_INET = socket.AF_INET
AF_INET6 = socket.AF_INET6


def _iface_map(**kwargs: list) -> dict[str, list]:
    """Convenience builder — keyword args become interface names."""
    return dict(kwargs)


# ---------------------------------------------------------------------------
# detect_vpn_interface
# ---------------------------------------------------------------------------

class TestDetectVpnInterface:
    def test_utun_detected(self):
        ifaces = _iface_map(utun0=[_make_addr(AF_INET, "10.8.0.2")], en0=[])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "utun0"

    def test_wg0_detected(self):
        ifaces = _iface_map(wg0=[_make_addr(AF_INET, "10.0.0.2")], eth0=[])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "wg0"

    def test_tun_detected(self):
        ifaces = _iface_map(tun0=[_make_addr(AF_INET, "172.16.0.1")])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "tun0"

    def test_ppp_detected(self):
        ifaces = _iface_map(ppp0=[_make_addr(AF_INET, "172.17.0.1")])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "ppp0"

    def test_nordlynx_detected(self):
        ifaces = _iface_map(nordlynx=[_make_addr(AF_INET, "10.5.0.2")])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "nordlynx"

    def test_proton0_detected(self):
        ifaces = _iface_map(proton0=[_make_addr(AF_INET, "10.2.0.1")])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "proton0"

    def test_no_vpn_interfaces(self):
        ifaces = _iface_map(en0=[_make_addr(AF_INET, "192.168.1.10")], lo0=[])
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is False
        assert name is None

    def test_multiple_vpn_interfaces_returns_first(self):
        # dict iteration order is insertion order in Python 3.7+
        ifaces = {"utun0": [], "wg0": [], "en0": []}
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: ifaces)
        assert vpn is True
        assert name == "utun0"

    def test_empty_interfaces(self):
        vpn, name = detect_vpn_interface(_interfaces_fn=lambda: {})
        assert vpn is False
        assert name is None


# ---------------------------------------------------------------------------
# check_dns_leak
# ---------------------------------------------------------------------------

class TestCheckDnsLeak:
    def test_no_leak_google_ips_only(self):
        # Returns only well-known Google DNS addresses → no leak
        def resolve(host: str) -> list[str]:
            return ["8.8.8.8", "8.8.4.4"]

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is False
        assert ips == []

    def test_leak_detected_unknown_public_ip(self):
        # Returns an unknown public IP alongside Google's → leak
        def resolve(host: str) -> list[str]:
            return ["8.8.8.8", "198.51.100.5"]  # 198.51.100.0/24 is TEST-NET-2 (public)

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is True
        assert "198.51.100.5" in ips

    def test_private_ip_flagged_as_leak(self):
        # Private/LAN resolver IPs (not loopback, not Google) are flagged
        def resolve(host: str) -> list[str]:
            return ["192.168.1.1"]  # private but not loopback → leak

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is True
        assert "192.168.1.1" in ips

    def test_loopback_not_flagged(self):
        def resolve(host: str) -> list[str]:
            return ["127.0.0.1"]

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is False

    def test_link_local_flagged_as_leak(self):
        # Link-local is not loopback and not Google → flagged
        def resolve(host: str) -> list[str]:
            return ["169.254.1.1"]

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is True

    def test_multiple_leak_ips(self):
        def resolve(host: str) -> list[str]:
            return ["203.0.113.1", "203.0.113.2"]  # TEST-NET-3

        leaking, ips = check_dns_leak(_resolve_fn=resolve)
        assert leaking is True
        assert len(ips) == 2


# ---------------------------------------------------------------------------
# check_ipv6_leak
# ---------------------------------------------------------------------------

class TestCheckIpv6Leak:
    def test_no_ipv6_addresses_no_leak(self):
        ifaces = _iface_map(utun0=[_make_addr(AF_INET, "10.8.0.2")],
                            en0=[_make_addr(AF_INET, "192.168.1.10")])
        leaking, addrs = check_ipv6_leak(_interfaces_fn=lambda: ifaces)
        assert leaking is False
        assert addrs == []

    def test_ipv6_only_on_vpn_interface_no_leak(self):
        ifaces = {
            "utun0": [_make_addr(AF_INET6, "2001:db8::1")],
            "en0": [_make_addr(AF_INET, "192.168.1.10")],
        }
        # The global IPv6 is on the VPN interface itself → not a leak
        leaking, addrs = check_ipv6_leak(_interfaces_fn=lambda: ifaces)
        assert leaking is False

    def test_global_ipv6_on_non_vpn_iface_is_leak(self):
        ifaces = {
            "utun0": [_make_addr(AF_INET, "10.8.0.2")],
            "en0": [_make_addr(AF_INET6, "2001:db8::5")],  # global IPv6
        }
        leaking, addrs = check_ipv6_leak(_interfaces_fn=lambda: ifaces)
        assert leaking is True
        assert "2001:db8::5" in addrs

    def test_link_local_ipv6_not_flagged(self):
        ifaces = {
            "utun0": [_make_addr(AF_INET, "10.8.0.2")],
            "en0": [_make_addr(AF_INET6, "fe80::1%en0")],  # link-local
        }
        leaking, addrs = check_ipv6_leak(_interfaces_fn=lambda: ifaces)
        assert leaking is False

    def test_no_vpn_detected_no_leak(self):
        # Without a VPN we don't flag a leak
        ifaces = _iface_map(en0=[_make_addr(AF_INET6, "2001:db8::1")])
        leaking, addrs = check_ipv6_leak(_interfaces_fn=lambda: ifaces)
        assert leaking is False


# ---------------------------------------------------------------------------
# check_split_tunnel
# ---------------------------------------------------------------------------

class TestCheckSplitTunnel:
    def test_same_first_hop_no_split_tunnel(self):
        def traceroute(host: str) -> str:
            return "10.8.0.1"  # same gateway for all targets

        result = check_split_tunnel(["1.1.1.1", "8.8.8.8"], _traceroute_fn=traceroute)
        assert result is False

    def test_different_first_hops_split_tunnel(self):
        hops = {"1.1.1.1": "10.8.0.1", "8.8.8.8": "192.168.1.1"}

        def traceroute(host: str) -> str:
            return hops[host]

        result = check_split_tunnel(["1.1.1.1", "8.8.8.8"], _traceroute_fn=traceroute)
        assert result is True

    def test_none_response_ignored(self):
        def traceroute(host: str) -> str | None:
            return None  # all probes fail

        result = check_split_tunnel(["1.1.1.1", "8.8.8.8"], _traceroute_fn=traceroute)
        assert result is False

    def test_single_target_no_split_tunnel(self):
        def traceroute(host: str) -> str:
            return "10.0.0.1"

        result = check_split_tunnel(["1.1.1.1"], _traceroute_fn=traceroute)
        assert result is False

    def test_default_targets_used_when_none(self):
        calls: list[str] = []

        def traceroute(host: str) -> str:
            calls.append(host)
            return "10.8.0.1"

        check_split_tunnel(None, _traceroute_fn=traceroute)
        assert "1.1.1.1" in calls
        assert "8.8.8.8" in calls


# ---------------------------------------------------------------------------
# run_vpn_leak_check (integration)
# ---------------------------------------------------------------------------

class TestRunVpnLeakCheck:
    def _no_vpn_ifaces(self):
        return _iface_map(en0=[_make_addr(AF_INET, "192.168.1.10")])

    def _vpn_ifaces(self):
        return {
            "utun0": [_make_addr(AF_INET, "10.8.0.2")],
            "en0": [_make_addr(AF_INET, "192.168.1.10")],
        }

    def test_no_vpn_no_leaks(self):
        report = run_vpn_leak_check(
            _interfaces_fn=self._no_vpn_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: "192.168.1.1",
        )
        assert isinstance(report, VpnLeakReport)
        assert report.vpn_detected is False
        assert report.dns_leak is False
        assert report.ipv6_leak is False
        assert report.split_tunnel is False

    def test_vpn_detected_no_leaks(self):
        report = run_vpn_leak_check(
            _interfaces_fn=self._vpn_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: "10.8.0.1",
        )
        assert report.vpn_detected is True
        assert report.vpn_interface == "utun0"
        assert report.dns_leak is False
        assert report.ipv6_leak is False
        assert report.split_tunnel is False

    def test_dns_leak_recorded_in_report(self):
        report = run_vpn_leak_check(
            _interfaces_fn=self._vpn_ifaces,
            _resolve_fn=lambda h: ["198.51.100.5"],
            _traceroute_fn=lambda h: "10.8.0.1",
        )
        assert report.dns_leak is True
        assert "198.51.100.5" in report.dns_leak_resolvers

    def test_ipv6_leak_recorded_in_report(self):
        def ipv6_ifaces():
            return {
                "utun0": [_make_addr(AF_INET, "10.8.0.2")],
                "en0": [_make_addr(AF_INET6, "2001:db8::5")],
            }

        report = run_vpn_leak_check(
            _interfaces_fn=ipv6_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: "10.8.0.1",
        )
        assert report.ipv6_leak is True
        assert "2001:db8::5" in report.ipv6_addresses

    def test_split_tunnel_recorded_in_report(self):
        hops = iter(["10.8.0.1", "192.168.1.1"])

        report = run_vpn_leak_check(
            _interfaces_fn=self._vpn_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: next(hops),
        )
        assert report.split_tunnel is True

    def test_details_populated(self):
        report = run_vpn_leak_check(
            _interfaces_fn=self._vpn_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: "10.8.0.1",
        )
        assert len(report.details) > 0

    def test_timestamp_set(self):
        from datetime import datetime

        report = run_vpn_leak_check(
            _interfaces_fn=self._no_vpn_ifaces,
            _resolve_fn=lambda h: ["8.8.8.8"],
            _traceroute_fn=lambda h: "192.168.1.1",
        )
        assert isinstance(report.timestamp, datetime)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestVpnCli:
    def test_check_command_success(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.run_vpn_leak_check",
            lambda: VpnLeakReport(
                vpn_detected=True,
                vpn_interface="utun0",
                dns_leak=False,
                dns_leak_resolvers=[],
                ipv6_leak=False,
                ipv6_addresses=[],
                split_tunnel=False,
                details=["VPN interface detected: utun0"],
            ),
        )
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 0
        assert "utun0" in result.output

    def test_check_command_json(self, monkeypatch):
        import json

        monkeypatch.setattr(
            "netglance.cli.vpn.run_vpn_leak_check",
            lambda: VpnLeakReport(
                vpn_detected=False,
                vpn_interface=None,
                dns_leak=False,
                details=[],
            ),
        )
        result = runner.invoke(app, ["check", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "vpn_detected" in data

    def test_dns_command_no_leak(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.check_dns_leak",
            lambda: (False, []),
        )
        result = runner.invoke(app, ["dns"])
        assert result.exit_code == 0
        assert "No DNS leak" in result.output

    def test_dns_command_leak(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.check_dns_leak",
            lambda: (True, ["198.51.100.5"]),
        )
        result = runner.invoke(app, ["dns"])
        assert result.exit_code == 0
        assert "leak" in result.output.lower()

    def test_dns_command_json(self, monkeypatch):
        import json

        monkeypatch.setattr(
            "netglance.cli.vpn.check_dns_leak",
            lambda: (True, ["198.51.100.5"]),
        )
        result = runner.invoke(app, ["dns", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dns_leak"] is True

    def test_ipv6_command_no_leak(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.check_ipv6_leak",
            lambda: (False, []),
        )
        result = runner.invoke(app, ["ipv6"])
        assert result.exit_code == 0
        assert "No IPv6 leak" in result.output

    def test_ipv6_command_leak(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.check_ipv6_leak",
            lambda: (True, ["2001:db8::5"]),
        )
        result = runner.invoke(app, ["ipv6"])
        assert result.exit_code == 0
        assert "leak" in result.output.lower()

    def test_status_command_vpn_active(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.detect_vpn_interface",
            lambda: (True, "utun0"),
        )
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "utun0" in result.output

    def test_status_command_no_vpn(self, monkeypatch):
        monkeypatch.setattr(
            "netglance.cli.vpn.detect_vpn_interface",
            lambda: (False, None),
        )
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No active VPN" in result.output

    def test_status_command_json(self, monkeypatch):
        import json

        monkeypatch.setattr(
            "netglance.cli.vpn.detect_vpn_interface",
            lambda: (True, "wg0"),
        )
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["vpn_detected"] is True
        assert data["vpn_interface"] == "wg0"
