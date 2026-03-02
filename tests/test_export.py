"""Tests for netglance.modules.export and netglance.cli.export."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netglance.cli.export import app
from netglance.modules.export import (
    export_baseline_json,
    export_devices_csv,
    export_devices_html,
    export_devices_json,
)
from netglance.store.models import Device, HostScanResult, PortResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_DT = datetime(2024, 1, 15, 12, 0, 0)


def make_device(
    ip: str = "192.168.1.1",
    mac: str = "aa:bb:cc:dd:ee:ff",
    hostname: str | None = "router.local",
    vendor: str | None = "Acme Corp",
) -> Device:
    return Device(
        ip=ip,
        mac=mac,
        hostname=hostname,
        vendor=vendor,
        discovery_method="arp",
        first_seen=FIXED_DT,
        last_seen=FIXED_DT,
    )


def make_scan(host: str = "192.168.1.1", ports: list[tuple[int, str]] | None = None) -> HostScanResult:
    port_list = ports or [(80, "http"), (443, "https")]
    return HostScanResult(
        host=host,
        ports=[
            PortResult(port=p, state="open", service=svc) for p, svc in port_list
        ],
        scan_time=FIXED_DT,
        scan_duration_s=1.5,
    )


# ---------------------------------------------------------------------------
# export_devices_json
# ---------------------------------------------------------------------------

class TestExportDevicesJson:
    def test_empty_list_returns_valid_json_array(self):
        result = export_devices_json([])
        parsed = json.loads(result)
        assert parsed == []

    def test_single_device_no_scans(self):
        device = make_device()
        result = export_devices_json([device])
        parsed = json.loads(result)
        assert len(parsed) == 1
        d = parsed[0]
        assert d["ip"] == "192.168.1.1"
        assert d["mac"] == "aa:bb:cc:dd:ee:ff"
        assert d["hostname"] == "router.local"
        assert d["vendor"] == "Acme Corp"
        assert d["discovery_method"] == "arp"
        assert d["open_ports"] == []

    def test_device_with_scans_includes_port_info(self):
        device = make_device()
        scan = make_scan()
        result = export_devices_json([device], scans={"192.168.1.1": scan})
        parsed = json.loads(result)
        d = parsed[0]
        assert len(d["open_ports"]) == 2
        ports = {p["port"] for p in d["open_ports"]}
        assert 80 in ports
        assert 443 in ports

    def test_device_with_closed_ports_excluded(self):
        device = make_device()
        scan = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=80, state="open"),
                PortResult(port=8080, state="closed"),
                PortResult(port=22, state="filtered"),
            ],
            scan_time=FIXED_DT,
        )
        result = export_devices_json([device], scans={"192.168.1.1": scan})
        parsed = json.loads(result)
        assert len(parsed[0]["open_ports"]) == 1
        assert parsed[0]["open_ports"][0]["port"] == 80

    def test_multiple_devices(self):
        devices = [make_device(ip=f"192.168.1.{i}") for i in range(1, 4)]
        result = export_devices_json(devices)
        parsed = json.loads(result)
        assert len(parsed) == 3

    def test_output_to_file(self, tmp_path):
        device = make_device()
        out = tmp_path / "devices.json"
        content = export_devices_json([device], output=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == content
        parsed = json.loads(out.read_text())
        assert len(parsed) == 1

    def test_device_none_fields(self):
        device = make_device(hostname=None, vendor=None)
        result = export_devices_json([device])
        parsed = json.loads(result)
        assert parsed[0]["hostname"] is None
        assert parsed[0]["vendor"] is None

    def test_scan_for_different_host_not_included(self):
        device = make_device(ip="192.168.1.1")
        scan = make_scan(host="192.168.1.2")
        result = export_devices_json([device], scans={"192.168.1.2": scan})
        parsed = json.loads(result)
        assert parsed[0]["open_ports"] == []


# ---------------------------------------------------------------------------
# export_devices_csv
# ---------------------------------------------------------------------------

class TestExportDevicesCsv:
    def test_empty_list_returns_header_only(self):
        result = export_devices_csv([])
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows == []
        assert "ip" in reader.fieldnames
        assert "open_ports" in reader.fieldnames

    def test_single_device_no_scans(self):
        device = make_device()
        result = export_devices_csv([device])
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["ip"] == "192.168.1.1"
        assert rows[0]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert rows[0]["open_ports"] == ""

    def test_device_with_scans(self):
        device = make_device()
        scan = make_scan()
        result = export_devices_csv([device], scans={"192.168.1.1": scan})
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        ports = rows[0]["open_ports"].split(",")
        assert "80" in ports
        assert "443" in ports

    def test_csv_is_parseable_with_standard_library(self):
        devices = [make_device(ip=f"10.0.0.{i}") for i in range(5)]
        result = export_devices_csv(devices)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 5

    def test_output_to_file(self, tmp_path):
        device = make_device()
        out = tmp_path / "devices.csv"
        content = export_devices_csv([device], output=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == content

    def test_none_fields_become_empty_string(self):
        device = make_device(hostname=None, vendor=None)
        result = export_devices_csv([device])
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["hostname"] == ""
        assert rows[0]["vendor"] == ""

    def test_closed_ports_not_in_csv(self):
        device = make_device()
        scan = HostScanResult(
            host="192.168.1.1",
            ports=[
                PortResult(port=22, state="open"),
                PortResult(port=8080, state="closed"),
            ],
            scan_time=FIXED_DT,
        )
        result = export_devices_csv([device], scans={"192.168.1.1": scan})
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["open_ports"] == "22"


# ---------------------------------------------------------------------------
# export_devices_html
# ---------------------------------------------------------------------------

class TestExportDevicesHtml:
    def test_returns_valid_html_structure(self):
        result = export_devices_html([])
        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "</html>" in result
        assert "<table" in result
        assert "</table>" in result

    def test_contains_header_columns(self):
        result = export_devices_html([])
        assert "<th>IP</th>" in result
        assert "<th>MAC</th>" in result
        assert "<th>Hostname</th>" in result
        assert "<th>Open Ports</th>" in result

    def test_device_data_in_table_rows(self):
        device = make_device()
        result = export_devices_html([device])
        assert "192.168.1.1" in result
        assert "aa:bb:cc:dd:ee:ff" in result
        assert "router.local" in result
        assert "Acme Corp" in result

    def test_xss_escaping(self):
        device = make_device(hostname="<script>alert(1)</script>", vendor='"evil"')
        result = export_devices_html([device])
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_device_count_in_meta(self):
        devices = [make_device(ip=f"10.0.0.{i}") for i in range(3)]
        result = export_devices_html(devices)
        assert "3 device(s)" in result

    def test_open_ports_displayed(self):
        device = make_device()
        scan = make_scan()
        result = export_devices_html([device], scans={"192.168.1.1": scan})
        assert "80" in result
        assert "443" in result

    def test_output_to_file(self, tmp_path):
        device = make_device()
        out = tmp_path / "inventory.html"
        content = export_devices_html([device], output=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == content

    def test_empty_device_list_no_crash(self):
        result = export_devices_html([])
        assert "No devices found." in result


# ---------------------------------------------------------------------------
# export_baseline_json
# ---------------------------------------------------------------------------

class TestExportBaselineJson:
    def test_roundtrip_dict(self):
        baseline = {"devices": [{"ip": "10.0.0.1", "mac": "00:11:22:33:44:55"}], "label": "test"}
        result = export_baseline_json(baseline)
        parsed = json.loads(result)
        assert parsed == baseline

    def test_nested_structure_preserved(self):
        baseline = {
            "timestamp": "2024-01-01T00:00:00",
            "devices": [],
            "open_ports": {"10.0.0.1": [{"port": 80, "state": "open"}]},
            "label": None,
        }
        result = export_baseline_json(baseline)
        parsed = json.loads(result)
        assert parsed["open_ports"]["10.0.0.1"][0]["port"] == 80

    def test_output_to_file(self, tmp_path):
        baseline = {"key": "value", "number": 42}
        out = tmp_path / "baseline.json"
        content = export_baseline_json(baseline, output=out)
        assert out.exists()
        assert json.loads(out.read_text()) == baseline
        assert content == out.read_text()

    def test_pretty_printed(self):
        baseline = {"a": 1}
        result = export_baseline_json(baseline)
        assert "\n" in result  # indented JSON has newlines


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

runner = CliRunner()


def _make_db_with_baseline(tmp_path: Path, baseline: dict, label: str | None = None) -> Path:
    """Create a temporary SQLite DB with one baseline row."""
    from netglance.store.db import Store

    db_path = tmp_path / "test.db"
    store = Store(db_path=db_path)
    store.init_db()
    store.save_baseline(baseline, label=label)
    return db_path


def _minimal_baseline() -> dict:
    return {
        "timestamp": FIXED_DT.isoformat(),
        "devices": [
            {
                "ip": "192.168.1.1",
                "mac": "aa:bb:cc:dd:ee:ff",
                "hostname": "router.local",
                "vendor": "ASUS",
                "discovery_method": "arp",
                "first_seen": FIXED_DT.isoformat(),
                "last_seen": FIXED_DT.isoformat(),
            }
        ],
        "open_ports": {
            "192.168.1.1": [{"port": 80, "state": "open", "service": "http"}]
        },
        "arp_table": [],
        "dns_results": [],
        "gateway_mac": None,
        "label": None,
    }


class TestCliDevices:
    def test_devices_json_stdout(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        result = runner.invoke(app, ["devices", "--db", str(db)])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["ip"] == "192.168.1.1"

    def test_devices_csv_stdout(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        result = runner.invoke(app, ["devices", "--format", "csv", "--db", str(db)])
        assert result.exit_code == 0
        reader = csv.DictReader(io.StringIO(result.stdout))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["ip"] == "192.168.1.1"

    def test_devices_html_stdout(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        result = runner.invoke(app, ["devices", "--format", "html", "--db", str(db)])
        assert result.exit_code == 0
        assert "<!DOCTYPE html>" in result.stdout
        assert "192.168.1.1" in result.stdout

    def test_devices_output_to_file(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        out = tmp_path / "out.json"
        result = runner.invoke(app, ["devices", "--output", str(out), "--db", str(db)])
        assert result.exit_code == 0
        assert out.exists()
        parsed = json.loads(out.read_text())
        assert len(parsed) == 1

    def test_devices_html_to_file(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        out = tmp_path / "inventory.html"
        result = runner.invoke(app, ["devices", "--format", "html", "-o", str(out), "--db", str(db)])
        assert result.exit_code == 0
        assert out.exists()
        assert "<!DOCTYPE html>" in out.read_text()

    def test_devices_no_baseline_exits_nonzero(self, tmp_path):
        from netglance.store.db import Store
        db = tmp_path / "empty.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["devices", "--db", str(db)])
        assert result.exit_code != 0

    def test_devices_unknown_format_exits_nonzero(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        result = runner.invoke(app, ["devices", "--format", "xml", "--db", str(db)])
        assert result.exit_code != 0


class TestCliBaseline:
    def test_baseline_json_stdout(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        result = runner.invoke(app, ["baseline", "--db", str(db)])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "devices" in parsed

    def test_baseline_output_to_file(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline())
        out = tmp_path / "baseline.json"
        result = runner.invoke(app, ["baseline", "--output", str(out), "--db", str(db)])
        assert result.exit_code == 0
        assert out.exists()
        parsed = json.loads(out.read_text())
        assert "devices" in parsed

    def test_baseline_by_label(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline(), label="initial")
        result = runner.invoke(app, ["baseline", "--label", "initial", "--db", str(db)])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "devices" in parsed

    def test_baseline_missing_label_exits_nonzero(self, tmp_path):
        db = _make_db_with_baseline(tmp_path, _minimal_baseline(), label="initial")
        result = runner.invoke(app, ["baseline", "--label", "nonexistent", "--db", str(db)])
        assert result.exit_code != 0

    def test_baseline_no_data_exits_nonzero(self, tmp_path):
        from netglance.store.db import Store
        db = tmp_path / "empty.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["baseline", "--db", str(db)])
        assert result.exit_code != 0
