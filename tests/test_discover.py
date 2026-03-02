"""Tests for the discover module -- fully mocked, no real network access."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.main import app
from netglance.modules.discover import (
    arp_scan,
    dicts_to_devices,
    devices_to_dicts,
    diff_devices,
    discover_all,
    mdns_scan,
)
from netglance.store.db import Store
from netglance.store.models import Device

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers / fake data
# ---------------------------------------------------------------------------

NOW = datetime(2026, 1, 15, 12, 0, 0)


def _fake_arping(subnet: str, interface: str | None, timeout: float) -> list[tuple[str, str]]:
    """Return deterministic ARP responses."""
    return [
        ("192.168.1.1", "aa:bb:cc:dd:ee:01"),
        ("192.168.1.100", "aa:bb:cc:dd:ee:02"),
        ("192.168.1.200", "aa:bb:cc:dd:ee:03"),
    ]


def _fake_hostname(ip: str) -> str | None:
    mapping = {
        "192.168.1.1": "router.local",
        "192.168.1.100": "desktop.local",
    }
    return mapping.get(ip)


def _fake_vendor(mac: str) -> str | None:
    mapping = {
        "aa:bb:cc:dd:ee:01": "Cisco Systems",
        "aa:bb:cc:dd:ee:02": "Apple, Inc.",
    }
    return mapping.get(mac)


def _fake_mdns(timeout: float) -> list[tuple[str, str, str | None]]:
    """Return deterministic mDNS entries (ip, mac, hostname)."""
    return [
        ("192.168.1.1", "", "router.local"),
        ("192.168.1.50", "", "printer.local"),
    ]


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


# ---------------------------------------------------------------------------
# Unit tests: arp_scan
# ---------------------------------------------------------------------------


class TestArpScan:
    def test_returns_device_list(self) -> None:
        devices = arp_scan(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=_fake_hostname,
            _vendor_fn=_fake_vendor,
        )
        assert len(devices) == 3
        assert all(isinstance(d, Device) for d in devices)

    def test_device_fields_populated(self) -> None:
        devices = arp_scan(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=_fake_hostname,
            _vendor_fn=_fake_vendor,
        )
        router = next(d for d in devices if d.ip == "192.168.1.1")
        assert router.mac == "aa:bb:cc:dd:ee:01"
        assert router.hostname == "router.local"
        assert router.vendor == "Cisco Systems"
        assert router.discovery_method == "arp"

    def test_missing_hostname_and_vendor(self) -> None:
        devices = arp_scan(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=_fake_hostname,
            _vendor_fn=_fake_vendor,
        )
        dev200 = next(d for d in devices if d.ip == "192.168.1.200")
        assert dev200.hostname is None
        assert dev200.vendor is None

    def test_mac_normalized_to_lowercase(self) -> None:
        def upper_arping(s, i, t):
            return [("10.0.0.1", "AA:BB:CC:DD:EE:FF")]

        devices = arp_scan(
            "10.0.0.0/24",
            _arping_fn=upper_arping,
            _hostname_fn=lambda _: None,
            _vendor_fn=lambda _: None,
        )
        assert devices[0].mac == "aa:bb:cc:dd:ee:ff"

    def test_interface_passed_through(self) -> None:
        calls: list = []

        def tracking_arping(subnet, interface, timeout):
            calls.append((subnet, interface, timeout))
            return []

        arp_scan(
            "10.0.0.0/24",
            interface="en0",
            _arping_fn=tracking_arping,
            _hostname_fn=lambda _: None,
            _vendor_fn=lambda _: None,
        )
        assert calls[0][1] == "en0"


# ---------------------------------------------------------------------------
# Unit tests: mdns_scan
# ---------------------------------------------------------------------------


class TestMdnsScan:
    def test_returns_device_list(self) -> None:
        devices = mdns_scan(
            _mdns_fn=_fake_mdns,
            _vendor_fn=_fake_vendor,
        )
        assert len(devices) == 2
        assert all(isinstance(d, Device) for d in devices)

    def test_device_fields(self) -> None:
        devices = mdns_scan(
            _mdns_fn=_fake_mdns,
            _vendor_fn=_fake_vendor,
        )
        printer = next(d for d in devices if d.ip == "192.168.1.50")
        assert printer.hostname == "printer.local"
        assert printer.discovery_method == "mdns"
        # mDNS fake has empty MAC, so vendor should be None
        assert printer.vendor is None

    def test_empty_mac_handled(self) -> None:
        devices = mdns_scan(
            _mdns_fn=_fake_mdns,
            _vendor_fn=_fake_vendor,
        )
        for d in devices:
            assert d.mac == ""


# ---------------------------------------------------------------------------
# Unit tests: discover_all (merge)
# ---------------------------------------------------------------------------


class TestDiscoverAll:
    def test_merge_arp_and_mdns(self) -> None:
        """ARP device whose IP matches mDNS gets merged; mDNS-only device kept."""
        devices = discover_all(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=lambda _: None,  # no rDNS
            _vendor_fn=_fake_vendor,
            _mdns_fn=_fake_mdns,
        )

        ips = {d.ip for d in devices}
        # 3 from ARP + 1 mDNS-only (printer)
        assert "192.168.1.1" in ips
        assert "192.168.1.100" in ips
        assert "192.168.1.200" in ips
        assert "192.168.1.50" in ips

    def test_merge_preserves_mdns_hostname(self) -> None:
        """When ARP has no hostname and mDNS does, the mDNS hostname is used."""
        devices = discover_all(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=lambda _: None,
            _vendor_fn=_fake_vendor,
            _mdns_fn=_fake_mdns,
        )
        router = next(d for d in devices if d.ip == "192.168.1.1")
        assert router.hostname == "router.local"
        assert router.discovery_method == "arp+mdns"

    def test_arp_hostname_not_overwritten(self) -> None:
        """When ARP already has a hostname, mDNS does not overwrite it."""
        devices = discover_all(
            "192.168.1.0/24",
            _arping_fn=_fake_arping,
            _hostname_fn=_fake_hostname,  # returns hostnames for .1 and .100
            _vendor_fn=_fake_vendor,
            _mdns_fn=_fake_mdns,
        )
        router = next(d for d in devices if d.ip == "192.168.1.1")
        # ARP already supplied "router.local", so it stays
        assert router.hostname == "router.local"


# ---------------------------------------------------------------------------
# Unit tests: diff_devices
# ---------------------------------------------------------------------------


class TestDiffDevices:
    def test_identical_lists(self) -> None:
        baseline = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        current = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        result = diff_devices(current, baseline)
        assert result["new"] == []
        assert result["missing"] == []
        assert result["changed"] == []

    def test_new_device(self) -> None:
        baseline = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        current = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_device("192.168.1.99", "aa:bb:cc:dd:ee:99"),
        ]
        result = diff_devices(current, baseline)
        assert len(result["new"]) == 1
        assert result["new"][0].mac == "aa:bb:cc:dd:ee:99"

    def test_missing_device(self) -> None:
        baseline = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_device("192.168.1.2", "aa:bb:cc:dd:ee:02"),
        ]
        current = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        result = diff_devices(current, baseline)
        assert len(result["missing"]) == 1
        assert result["missing"][0].mac == "aa:bb:cc:dd:ee:02"

    def test_changed_ip(self) -> None:
        baseline = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01")]
        current = [_make_device("192.168.1.99", "aa:bb:cc:dd:ee:01")]
        result = diff_devices(current, baseline)
        assert len(result["changed"]) == 1
        assert result["changed"][0].ip == "192.168.1.99"

    def test_changed_hostname(self) -> None:
        baseline = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="old.local")]
        current = [_make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="new.local")]
        result = diff_devices(current, baseline)
        assert len(result["changed"]) == 1

    def test_empty_lists(self) -> None:
        result = diff_devices([], [])
        assert result == {"new": [], "missing": [], "changed": []}

    def test_complex_scenario(self) -> None:
        baseline = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="router"),
            _make_device("192.168.1.2", "aa:bb:cc:dd:ee:02", hostname="desktop"),
            _make_device("192.168.1.3", "aa:bb:cc:dd:ee:03", hostname="laptop"),
        ]
        current = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", hostname="router"),  # same
            _make_device("192.168.1.20", "aa:bb:cc:dd:ee:02", hostname="desktop"),  # IP changed
            # .3 missing
            _make_device("192.168.1.4", "aa:bb:cc:dd:ee:04", hostname="phone"),  # new
        ]
        result = diff_devices(current, baseline)
        assert len(result["new"]) == 1
        assert result["new"][0].mac == "aa:bb:cc:dd:ee:04"
        assert len(result["missing"]) == 1
        assert result["missing"][0].mac == "aa:bb:cc:dd:ee:03"
        assert len(result["changed"]) == 1
        assert result["changed"][0].mac == "aa:bb:cc:dd:ee:02"


# ---------------------------------------------------------------------------
# Unit tests: serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip(self) -> None:
        original = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", "host.local", "Cisco"),
        ]
        dicts = devices_to_dicts(original)
        restored = dicts_to_devices(dicts)
        assert len(restored) == 1
        assert restored[0].ip == original[0].ip
        assert restored[0].mac == original[0].mac
        assert restored[0].hostname == original[0].hostname
        assert restored[0].vendor == original[0].vendor
        assert restored[0].first_seen == original[0].first_seen

    def test_dicts_are_json_serialisable(self) -> None:
        devices = [_make_device("10.0.0.1", "00:11:22:33:44:55")]
        dicts = devices_to_dicts(devices)
        # Should not raise
        text = json.dumps(dicts)
        parsed = json.loads(text)
        assert parsed[0]["ip"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestDiscoverCLI:
    """Test the ``netglance discover`` command using CliRunner."""

    def _run(self, args: list[str], **kwargs):
        """Helper: invoke the CLI with mocked network functions."""
        return runner.invoke(app, ["discover"] + args, **kwargs)

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_default_discover_prints_table(self) -> None:
        result = self._run([])
        assert result.exit_code == 0
        assert "Discovered Devices" in result.output
        assert "192.168.1.1" in result.output

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    def test_method_arp(self) -> None:
        result = self._run(["--method", "arp"])
        assert result.exit_code == 0
        assert "192.168.1.1" in result.output
        # printer is mDNS-only, should NOT appear
        assert "192.168.1.50" not in result.output

    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    def test_method_mdns(self) -> None:
        result = self._run(["--method", "mdns"])
        assert result.exit_code == 0
        assert "printer.local" in result.output

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_json_output(self) -> None:
        result = self._run(["--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "devices" in data
        assert len(data["devices"]) >= 3

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_save_persists_to_db(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        result = self._run(["--save", "--db", str(db_file)])
        assert result.exit_code == 0

        # Verify data was saved
        store = Store(db_path=db_file)
        results = store.get_results("discover", limit=1)
        assert len(results) == 1
        assert "devices" in results[0]
        store.close()

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_save_creates_baseline(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        result = self._run(["--save", "--db", str(db_file)])
        assert result.exit_code == 0

        store = Store(db_path=db_file)
        store.init_db()
        baseline = store.get_latest_baseline()
        assert baseline is not None
        assert "devices" in baseline
        store.close()

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_diff_against_baseline(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"

        # First run: save baseline
        result = self._run(["--save", "--db", str(db_file)])
        assert result.exit_code == 0

        # Second run: diff against that baseline (same data => no new/missing)
        result = self._run(["--diff", "--db", str(db_file)])
        assert result.exit_code == 0
        assert "Discovered Devices" in result.output

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_diff_json_includes_diff_key(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"

        # Save baseline
        self._run(["--save", "--db", str(db_file)])

        # Diff + JSON
        result = self._run(["--diff", "--json", "--db", str(db_file)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "diff" in data
        assert "new" in data["diff"]
        assert "missing" in data["diff"]
        assert "changed" in data["diff"]

    @patch("netglance.modules.discover._scapy_arping", new=_fake_arping)
    @patch("netglance.modules.discover._resolve_hostname", new=_fake_hostname)
    @patch("netglance.modules.discover._lookup_vendor", new=_fake_vendor)
    @patch("netglance.modules.discover._mdns_browse", new=_fake_mdns)
    def test_diff_detects_new_device(self, tmp_path: Path) -> None:
        """Save a minimal baseline, then scan with more devices -> diff shows new."""
        db_file = tmp_path / "test.db"

        # Manually create a baseline with only one device
        store = Store(db_path=db_file)
        store.init_db()
        baseline_device = _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", "router.local")
        store.save_baseline({"devices": devices_to_dicts([baseline_device])}, label="discover")
        store.close()

        # Now run discover --diff --json; the scan returns 3+ devices
        result = self._run(["--diff", "--json", "--db", str(db_file)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        new_macs = {d["mac"] for d in data["diff"]["new"]}
        # Devices ee:02, ee:03 are new compared to the single-device baseline
        assert "aa:bb:cc:dd:ee:02" in new_macs
        assert "aa:bb:cc:dd:ee:03" in new_macs


# ---------------------------------------------------------------------------
# Store integration tests (with tmp_db fixture from conftest)
# ---------------------------------------------------------------------------


class TestStoreIntegration:
    def test_save_and_retrieve_discover_results(self, tmp_db: Store) -> None:
        devices = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01", "router", "Cisco"),
        ]
        tmp_db.save_result("discover", {"devices": devices_to_dicts(devices)})
        results = tmp_db.get_results("discover", limit=1)
        assert len(results) == 1
        restored = dicts_to_devices(results[0]["devices"])
        assert restored[0].ip == "192.168.1.1"

    def test_baseline_save_and_load(self, tmp_db: Store) -> None:
        devices = [
            _make_device("192.168.1.1", "aa:bb:cc:dd:ee:01"),
            _make_device("192.168.1.2", "aa:bb:cc:dd:ee:02"),
        ]
        tmp_db.save_baseline({"devices": devices_to_dicts(devices)}, label="discover")
        baseline = tmp_db.get_latest_baseline()
        assert baseline is not None
        restored = dicts_to_devices(baseline["devices"])
        assert len(restored) == 2
