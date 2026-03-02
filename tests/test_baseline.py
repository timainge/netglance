"""Tests for the baseline module -- fully mocked, no real network access."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netglance.cli.main import app
from netglance.modules.baseline import (
    NetworkBaseline,
    baseline_to_dict,
    capture_baseline,
    dict_to_baseline,
    diff_baselines,
    load_baseline,
    save_baseline,
)
from netglance.store.db import Store
from netglance.store.models import (
    ArpEntry,
    Device,
    DnsResolverResult,
    HostScanResult,
    PortResult,
)
from netglance.modules.dns import DnsHealthReport

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers / fake data
# ---------------------------------------------------------------------------

NOW = datetime(2026, 1, 15, 12, 0, 0)
SUBNET = "192.168.1.0/24"


def _make_device(
    ip: str,
    mac: str,
    hostname: str | None = None,
    vendor: str | None = None,
    method: str = "arp",
) -> Device:
    return Device(
        ip=ip,
        mac=mac,
        hostname=hostname,
        vendor=vendor,
        discovery_method=method,
        first_seen=NOW,
        last_seen=NOW,
    )


def _make_arp_entry(ip: str, mac: str, interface: str = "en0") -> ArpEntry:
    return ArpEntry(ip=ip, mac=mac, interface=interface, timestamp=NOW)


def _make_dns_result(
    resolver: str, resolver_name: str, answers: list[str] | None = None, error: str | None = None
) -> DnsResolverResult:
    return DnsResolverResult(
        resolver=resolver,
        resolver_name=resolver_name,
        query="example.com",
        answers=answers or ["93.184.216.34"],
        response_time_ms=10.0,
        error=error,
    )


def _make_port(port: int, state: str = "open", service: str | None = None) -> PortResult:
    return PortResult(port=port, state=state, service=service)


# Standard fakes used across tests

FAKE_DEVICES = [
    _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", "router.local", "Cisco"),
    _make_device("192.168.1.100", "aa:bb:cc:dd:ee:02", "desktop.local", "Apple"),
]

FAKE_ARP_TABLE = [
    _make_arp_entry("192.168.1.1", "aa:bb:cc:dd:ee:01"),
    _make_arp_entry("192.168.1.100", "aa:bb:cc:dd:ee:02"),
]

FAKE_DNS_REPORT = DnsHealthReport(
    resolvers_checked=3,
    consistent=True,
    fastest_resolver="Cloudflare (1.1.1.1)",
    dnssec_supported=False,
    potential_hijack=False,
    details=[
        _make_dns_result("1.1.1.1", "Cloudflare"),
        _make_dns_result("8.8.8.8", "Google"),
        _make_dns_result("9.9.9.9", "Quad9"),
    ],
)

FAKE_GATEWAY_ENTRY = _make_arp_entry("192.168.1.1", "aa:bb:cc:dd:ee:01")

FAKE_SCAN_RESULTS: dict[str, HostScanResult] = {
    "192.168.1.1": HostScanResult(
        host="192.168.1.1",
        ports=[_make_port(80, "open", "http"), _make_port(443, "open", "https")],
    ),
    "192.168.1.100": HostScanResult(
        host="192.168.1.100",
        ports=[_make_port(22, "open", "ssh")],
    ),
}


def _fake_discover(subnet: str, interface: str | None = None) -> list[Device]:
    return list(FAKE_DEVICES)


def _fake_arp() -> list[ArpEntry]:
    return list(FAKE_ARP_TABLE)


def _fake_dns(domain: str) -> DnsHealthReport:
    return FAKE_DNS_REPORT


def _fake_scan(host: str) -> HostScanResult:
    return FAKE_SCAN_RESULTS.get(host, HostScanResult(host=host, ports=[]))


def _fake_gateway(interface: str | None = None) -> ArpEntry | None:
    return FAKE_GATEWAY_ENTRY


# ---------------------------------------------------------------------------
# Unit tests: capture_baseline
# ---------------------------------------------------------------------------


class TestCaptureBaseline:
    def test_returns_network_baseline(self) -> None:
        result = capture_baseline(
            SUBNET,
            label="test",
            _discover_fn=_fake_discover,
            _arp_fn=_fake_arp,
            _dns_fn=_fake_dns,
            _scan_fn=_fake_scan,
            _gateway_fn=_fake_gateway,
        )
        assert isinstance(result, NetworkBaseline)

    def test_all_fields_populated(self) -> None:
        result = capture_baseline(
            SUBNET,
            label="test",
            _discover_fn=_fake_discover,
            _arp_fn=_fake_arp,
            _dns_fn=_fake_dns,
            _scan_fn=_fake_scan,
            _gateway_fn=_fake_gateway,
        )
        assert len(result.devices) == 2
        assert len(result.arp_table) == 2
        assert len(result.dns_results) == 3
        assert "192.168.1.1" in result.open_ports
        assert "192.168.1.100" in result.open_ports
        assert result.gateway_mac == "aa:bb:cc:dd:ee:01"
        assert result.label == "test"
        assert result.timestamp is not None

    def test_scans_only_discovered_ips(self) -> None:
        scanned_hosts: list[str] = []

        def tracking_scan(host: str) -> HostScanResult:
            scanned_hosts.append(host)
            return HostScanResult(host=host, ports=[])

        capture_baseline(
            SUBNET,
            _discover_fn=_fake_discover,
            _arp_fn=_fake_arp,
            _dns_fn=_fake_dns,
            _scan_fn=tracking_scan,
            _gateway_fn=_fake_gateway,
        )
        assert set(scanned_hosts) == {"192.168.1.1", "192.168.1.100"}

    def test_gateway_none_when_not_found(self) -> None:
        result = capture_baseline(
            SUBNET,
            _discover_fn=_fake_discover,
            _arp_fn=_fake_arp,
            _dns_fn=_fake_dns,
            _scan_fn=_fake_scan,
            _gateway_fn=lambda iface=None: None,
        )
        assert result.gateway_mac is None

    def test_empty_ports_when_no_open(self) -> None:
        def no_ports_scan(host: str) -> HostScanResult:
            return HostScanResult(host=host, ports=[])

        result = capture_baseline(
            SUBNET,
            _discover_fn=_fake_discover,
            _arp_fn=_fake_arp,
            _dns_fn=_fake_dns,
            _scan_fn=no_ports_scan,
            _gateway_fn=_fake_gateway,
        )
        assert result.open_ports == {}


# ---------------------------------------------------------------------------
# Unit tests: diff_baselines
# ---------------------------------------------------------------------------


def _make_baseline(
    devices: list[Device] | None = None,
    arp_table: list[ArpEntry] | None = None,
    dns_results: list[DnsResolverResult] | None = None,
    open_ports: dict[str, list[PortResult]] | None = None,
    gateway_mac: str | None = "aa:bb:cc:dd:ee:01",
) -> NetworkBaseline:
    return NetworkBaseline(
        timestamp=NOW,
        devices=devices if devices is not None else list(FAKE_DEVICES),
        arp_table=arp_table if arp_table is not None else list(FAKE_ARP_TABLE),
        dns_results=dns_results if dns_results is not None else list(FAKE_DNS_REPORT.details),
        open_ports=open_ports if open_ports is not None else {},
        gateway_mac=gateway_mac,
    )


class TestDiffBaselines:
    def test_identical_baselines_no_changes(self) -> None:
        baseline = _make_baseline()
        changes = diff_baselines(baseline, baseline)
        assert changes["new_devices"] == []
        assert changes["missing_devices"] == []
        assert changes["changed_devices"] == []
        assert changes["arp_alerts"] == []
        assert changes["dns_changes"] == []
        assert changes["port_changes"] == {}

    def test_new_device_detected(self) -> None:
        previous = _make_baseline(devices=[FAKE_DEVICES[0]])
        current = _make_baseline(devices=list(FAKE_DEVICES))
        changes = diff_baselines(current, previous)
        assert len(changes["new_devices"]) == 1
        assert changes["new_devices"][0].mac == "aa:bb:cc:dd:ee:02"

    def test_missing_device_detected(self) -> None:
        previous = _make_baseline(devices=list(FAKE_DEVICES))
        current = _make_baseline(devices=[FAKE_DEVICES[0]])
        changes = diff_baselines(current, previous)
        assert len(changes["missing_devices"]) == 1
        assert changes["missing_devices"][0].mac == "aa:bb:cc:dd:ee:02"

    def test_changed_device_detected(self) -> None:
        previous = _make_baseline(
            devices=[_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="old")]
        )
        current = _make_baseline(
            devices=[_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="new")]
        )
        changes = diff_baselines(current, previous)
        assert len(changes["changed_devices"]) == 1

    def test_arp_mac_change_alert(self) -> None:
        prev_arp = [_make_arp_entry("192.168.1.100", "aa:bb:cc:dd:ee:02")]
        cur_arp = [_make_arp_entry("192.168.1.100", "ff:ff:ff:ff:ff:ff")]
        previous = _make_baseline(arp_table=prev_arp, gateway_mac=None)
        current = _make_baseline(arp_table=cur_arp, gateway_mac=None)
        changes = diff_baselines(current, previous)
        assert len(changes["arp_alerts"]) >= 1
        types = {a.alert_type for a in changes["arp_alerts"]}
        assert "mac_changed" in types

    def test_dns_answers_changed(self) -> None:
        prev_dns = [_make_dns_result("1.1.1.1", "Cloudflare", answers=["93.184.216.34"])]
        cur_dns = [_make_dns_result("1.1.1.1", "Cloudflare", answers=["1.2.3.4"])]
        previous = _make_baseline(dns_results=prev_dns)
        current = _make_baseline(dns_results=cur_dns)
        changes = diff_baselines(current, previous)
        assert len(changes["dns_changes"]) == 1
        assert changes["dns_changes"][0]["change"] == "answers_changed"

    def test_dns_no_change(self) -> None:
        dns = [_make_dns_result("1.1.1.1", "Cloudflare")]
        previous = _make_baseline(dns_results=dns)
        current = _make_baseline(dns_results=dns)
        changes = diff_baselines(current, previous)
        assert changes["dns_changes"] == []

    def test_port_new_port_detected(self) -> None:
        prev_ports = {"192.168.1.1": [_make_port(80, "open", "http")]}
        cur_ports = {
            "192.168.1.1": [_make_port(80, "open", "http"), _make_port(443, "open", "https")]
        }
        previous = _make_baseline(open_ports=prev_ports)
        current = _make_baseline(open_ports=cur_ports)
        changes = diff_baselines(current, previous)
        assert "192.168.1.1" in changes["port_changes"]
        assert len(changes["port_changes"]["192.168.1.1"]["new_ports"]) == 1
        assert changes["port_changes"]["192.168.1.1"]["new_ports"][0]["port"] == 443

    def test_port_closed_detected(self) -> None:
        prev_ports = {
            "192.168.1.1": [_make_port(80, "open", "http"), _make_port(443, "open", "https")]
        }
        cur_ports = {"192.168.1.1": [_make_port(80, "open", "http")]}
        previous = _make_baseline(open_ports=prev_ports)
        current = _make_baseline(open_ports=cur_ports)
        changes = diff_baselines(current, previous)
        assert "192.168.1.1" in changes["port_changes"]
        assert len(changes["port_changes"]["192.168.1.1"]["closed_ports"]) == 1

    def test_port_no_changes(self) -> None:
        ports = {"192.168.1.1": [_make_port(80, "open", "http")]}
        previous = _make_baseline(open_ports=ports)
        current = _make_baseline(open_ports=ports)
        changes = diff_baselines(current, previous)
        assert changes["port_changes"] == {}


# ---------------------------------------------------------------------------
# Unit tests: serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisation:
    def _make_full_baseline(self) -> NetworkBaseline:
        return NetworkBaseline(
            timestamp=NOW,
            devices=list(FAKE_DEVICES),
            arp_table=list(FAKE_ARP_TABLE),
            dns_results=list(FAKE_DNS_REPORT.details),
            open_ports={
                "192.168.1.1": [_make_port(80, "open", "http")],
                "192.168.1.100": [_make_port(22, "open", "ssh")],
            },
            gateway_mac="aa:bb:cc:dd:ee:01",
            label="test-roundtrip",
        )

    def test_round_trip(self) -> None:
        original = self._make_full_baseline()
        data = baseline_to_dict(original)
        restored = dict_to_baseline(data)

        # Top-level fields
        assert restored.timestamp == original.timestamp
        assert restored.label == original.label
        assert restored.gateway_mac == original.gateway_mac

        # Devices
        assert len(restored.devices) == len(original.devices)
        for orig, rest in zip(original.devices, restored.devices):
            assert rest.ip == orig.ip
            assert rest.mac == orig.mac
            assert rest.hostname == orig.hostname
            assert rest.vendor == orig.vendor
            assert rest.first_seen == orig.first_seen
            assert rest.last_seen == orig.last_seen

        # ARP table
        assert len(restored.arp_table) == len(original.arp_table)
        for orig, rest in zip(original.arp_table, restored.arp_table):
            assert rest.ip == orig.ip
            assert rest.mac == orig.mac
            assert rest.interface == orig.interface

        # DNS results
        assert len(restored.dns_results) == len(original.dns_results)
        for orig, rest in zip(original.dns_results, restored.dns_results):
            assert rest.resolver == orig.resolver
            assert rest.answers == orig.answers

        # Open ports
        assert set(restored.open_ports.keys()) == set(original.open_ports.keys())
        for host in original.open_ports:
            assert len(restored.open_ports[host]) == len(original.open_ports[host])
            for orig_p, rest_p in zip(original.open_ports[host], restored.open_ports[host]):
                assert rest_p.port == orig_p.port
                assert rest_p.state == orig_p.state
                assert rest_p.service == orig_p.service

    def test_dict_is_json_serialisable(self) -> None:
        import json

        original = self._make_full_baseline()
        data = baseline_to_dict(original)
        # Should not raise
        text = json.dumps(data)
        parsed = json.loads(text)
        assert parsed["label"] == "test-roundtrip"
        assert len(parsed["devices"]) == 2


# ---------------------------------------------------------------------------
# Unit tests: save / load via store
# ---------------------------------------------------------------------------


class TestStoreIntegration:
    def test_save_and_load_latest(self, tmp_db: Store) -> None:
        baseline = NetworkBaseline(
            timestamp=NOW,
            devices=list(FAKE_DEVICES),
            arp_table=list(FAKE_ARP_TABLE),
            dns_results=list(FAKE_DNS_REPORT.details),
            open_ports={"192.168.1.1": [_make_port(80, "open", "http")]},
            gateway_mac="aa:bb:cc:dd:ee:01",
            label="integration-test",
        )
        baseline_id = save_baseline(baseline, tmp_db)
        assert isinstance(baseline_id, int)
        assert baseline_id > 0

        loaded = load_baseline(tmp_db)
        assert loaded is not None
        assert loaded.label == "integration-test"
        assert len(loaded.devices) == 2
        assert loaded.gateway_mac == "aa:bb:cc:dd:ee:01"

    def test_save_and_load_by_id(self, tmp_db: Store) -> None:
        b1 = _make_baseline()
        b1.label = "first"
        id1 = save_baseline(b1, tmp_db)

        b2 = _make_baseline()
        b2.label = "second"
        id2 = save_baseline(b2, tmp_db)

        loaded1 = load_baseline(tmp_db, baseline_id=id1)
        assert loaded1 is not None
        assert loaded1.label == "first"

        loaded2 = load_baseline(tmp_db, baseline_id=id2)
        assert loaded2 is not None
        assert loaded2.label == "second"

    def test_load_returns_none_when_empty(self, tmp_db: Store) -> None:
        assert load_baseline(tmp_db) is None

    def test_load_by_nonexistent_id(self, tmp_db: Store) -> None:
        assert load_baseline(tmp_db, baseline_id=999) is None

    def test_list_baselines(self, tmp_db: Store) -> None:
        b1 = _make_baseline()
        b1.label = "alpha"
        save_baseline(b1, tmp_db)

        b2 = _make_baseline()
        b2.label = "beta"
        save_baseline(b2, tmp_db)

        entries = tmp_db.list_baselines()
        assert len(entries) == 2
        labels = {e["label"] for e in entries}
        assert "alpha" in labels
        assert "beta" in labels


# ---------------------------------------------------------------------------
# CLI tests via CliRunner
# ---------------------------------------------------------------------------


class TestBaselineCLI:
    def test_baseline_help(self) -> None:
        result = runner.invoke(app, ["baseline", "--help"])
        assert result.exit_code == 0
        assert "baseline" in result.output.lower()

    def test_capture_with_mocked_modules(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        from unittest.mock import patch

        with (
            patch(
                "netglance.modules.baseline.discover_all",
                side_effect=_fake_discover,
            ),
            patch(
                "netglance.modules.baseline.get_arp_table",
                side_effect=_fake_arp,
            ),
            patch(
                "netglance.modules.baseline.check_consistency",
                side_effect=_fake_dns,
            ),
            patch(
                "netglance.modules.baseline.quick_scan",
                side_effect=_fake_scan,
            ),
            patch(
                "netglance.modules.baseline.get_gateway_mac",
                side_effect=_fake_gateway,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "baseline",
                    "capture",
                    "--subnet",
                    SUBNET,
                    "--label",
                    "test-capture",
                    "--db",
                    db,
                ],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "saved" in result.output.lower()
        assert "Devices" in result.output

    def test_list_with_no_baselines(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        # Ensure the DB is created
        store = Store(db_path=db)
        store.init_db()
        store.close()

        result = runner.invoke(app, ["baseline", "list", "--db", db])
        assert result.exit_code == 0
        assert "No baselines" in result.output

    def test_list_after_capture(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        from unittest.mock import patch

        with (
            patch("netglance.modules.baseline.discover_all", side_effect=_fake_discover),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            runner.invoke(
                app,
                ["baseline", "capture", "--subnet", SUBNET, "--label", "my-label", "--db", db],
                catch_exceptions=False,
            )

        result = runner.invoke(app, ["baseline", "list", "--db", db])
        assert result.exit_code == 0
        assert "my-label" in result.output

    def test_show_baseline(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        from unittest.mock import patch

        with (
            patch("netglance.modules.baseline.discover_all", side_effect=_fake_discover),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            runner.invoke(
                app,
                ["baseline", "capture", "--subnet", SUBNET, "--label", "show-test", "--db", db],
                catch_exceptions=False,
            )

        result = runner.invoke(app, ["baseline", "show", "1", "--db", db])
        assert result.exit_code == 0
        assert "show-test" in result.output
        assert "192.168.1.1" in result.output

    def test_show_nonexistent_baseline(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        store = Store(db_path=db)
        store.init_db()
        store.close()

        result = runner.invoke(app, ["baseline", "show", "999", "--db", db])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_diff_no_baseline(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        store = Store(db_path=db)
        store.init_db()
        store.close()

        from unittest.mock import patch

        with (
            patch("netglance.modules.baseline.discover_all", side_effect=_fake_discover),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            result = runner.invoke(
                app, ["baseline", "diff", "--subnet", SUBNET, "--db", db]
            )
        assert result.exit_code == 1
        assert "No saved baseline" in result.output

    def test_diff_no_changes(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        from unittest.mock import patch

        with (
            patch("netglance.modules.baseline.discover_all", side_effect=_fake_discover),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            # First capture
            runner.invoke(
                app,
                ["baseline", "capture", "--subnet", SUBNET, "--db", db],
                catch_exceptions=False,
            )
            # Then diff (same fake data)
            result = runner.invoke(
                app,
                ["baseline", "diff", "--subnet", SUBNET, "--db", db],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "No changes" in result.output

    def test_diff_detects_new_device(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        from unittest.mock import patch

        # Save a baseline with one device
        single_device = [FAKE_DEVICES[0]]

        def discover_single(subnet, interface=None):
            return list(single_device)

        with (
            patch("netglance.modules.baseline.discover_all", side_effect=discover_single),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            runner.invoke(
                app,
                ["baseline", "capture", "--subnet", SUBNET, "--db", db],
                catch_exceptions=False,
            )

        # Now diff with two devices
        with (
            patch("netglance.modules.baseline.discover_all", side_effect=_fake_discover),
            patch("netglance.modules.baseline.get_arp_table", side_effect=_fake_arp),
            patch("netglance.modules.baseline.check_consistency", side_effect=_fake_dns),
            patch("netglance.modules.baseline.quick_scan", side_effect=_fake_scan),
            patch("netglance.modules.baseline.get_gateway_mac", side_effect=_fake_gateway),
        ):
            result = runner.invoke(
                app,
                ["baseline", "diff", "--subnet", SUBNET, "--db", db],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "New devices" in result.output
        assert "aa:bb:cc:dd:ee:02" in result.output
