"""Tests for netglance.modules.iot and netglance.cli.iot."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.iot import app
from netglance.modules.iot import (
    _classify_by_ports,
    _mac_prefix,
    _match_mac_prefix,
    _vendor_is_iot,
    assess_device_risk,
    audit_network,
    classify_iot_device,
    format_risk_level,
    get_iot_signatures,
)
from netglance.store.models import (
    Device,
    DeviceProfile,
    HostScanResult,
    IoTAuditReport,
    IoTDevice,
    PortResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_SIGNATURES = {
    "mac_prefixes": {
        "B0:BE:76": {"type": "camera", "manufacturer": "Ring"},
        "68:37:E9": {"type": "speaker", "manufacturer": "Amazon", "model": "Echo"},
        "D0:73:D5": {"type": "hub", "manufacturer": "Philips", "model": "Hue Bridge"},
        "AC:84:C6": {"type": "thermostat", "manufacturer": "Nest"},
        "B4:E6:2D": {"type": "plug", "manufacturer": "TP-Link", "model": "Kasa"},
    },
    "risky_ports": {
        "23": {"severity": "critical", "service": "Telnet", "issue": "Unencrypted remote access"},
        "21": {"severity": "high", "service": "FTP", "issue": "Unencrypted file transfer"},
        "80": {"severity": "medium", "service": "HTTP", "issue": "Unencrypted web interface"},
        "1883": {"severity": "high", "service": "MQTT", "issue": "Unencrypted MQTT broker"},
        "5555": {"severity": "critical", "service": "ADB", "issue": "Android Debug Bridge exposed"},
        "8080": {"severity": "medium", "service": "HTTP-Alt", "issue": "Alternative web interface"},
        "8443": {"severity": "low", "service": "HTTPS-Alt", "issue": "Alternative HTTPS"},
        "1900": {"severity": "low", "service": "UPnP", "issue": "Universal Plug and Play"},
        "443": {"severity": "low", "service": "HTTPS", "issue": "HTTPS"},
    },
    "iot_indicators": {
        "port_patterns": {
            "camera": [554, 80, 8080, 443],
            "speaker": [1400, 8080, 7000],
            "thermostat": [80, 443],
            "plug": [80, 9999, 6668],
            "hub": [80, 443, 8080, 8443, 1900],
        },
        "vendor_keywords": [
            "espressif", "tuya", "shelly", "tasmota", "sonoff", "ring",
            "nest", "ecobee", "hue", "wyze", "arlo",
        ],
    },
}


@pytest.fixture
def sigs_fn():
    """Inject test signatures."""
    return lambda: MINIMAL_SIGNATURES


@pytest.fixture
def ring_device():
    return Device(ip="192.168.1.100", mac="B0:BE:76:12:34:56", vendor="Ring")


@pytest.fixture
def echo_device():
    return Device(ip="192.168.1.101", mac="68:37:E9:AB:CD:EF", vendor="Amazon")


@pytest.fixture
def hue_device():
    return Device(ip="192.168.1.102", mac="D0:73:D5:00:11:22", vendor="Philips")


@pytest.fixture
def nest_device():
    return Device(ip="192.168.1.103", mac="AC:84:C6:33:44:55", vendor="Nest")


@pytest.fixture
def kasa_device():
    return Device(ip="192.168.1.104", mac="B4:E6:2D:66:77:88", vendor="TP-Link")


@pytest.fixture
def laptop_device():
    """A regular laptop — should NOT be classified as IoT."""
    return Device(ip="192.168.1.50", mac="AA:BB:CC:DD:EE:FF", vendor="Apple")


@pytest.fixture
def espressif_device():
    """Espressif device — IoT via vendor keyword."""
    return Device(ip="192.168.1.200", mac="30:AE:A4:11:22:33", vendor="Espressif Inc")


@pytest.fixture
def telnet_scan():
    """Scan result with Telnet open."""
    return HostScanResult(
        host="192.168.1.100",
        ports=[PortResult(port=23, state="open", service="telnet")],
    )


@pytest.fixture
def http_scan():
    """Scan result with HTTP open but no HTTPS."""
    return HostScanResult(
        host="192.168.1.100",
        ports=[PortResult(port=80, state="open", service="http")],
    )


@pytest.fixture
def multi_port_scan():
    """Scan with multiple risky ports."""
    return HostScanResult(
        host="192.168.1.100",
        ports=[
            PortResult(port=23, state="open", service="telnet"),
            PortResult(port=80, state="open", service="http"),
            PortResult(port=1883, state="open", service="mqtt"),
        ],
    )


@pytest.fixture
def camera_port_scan():
    """Port pattern consistent with a camera."""
    return HostScanResult(
        host="192.168.1.50",
        ports=[
            PortResult(port=554, state="open", service="rtsp"),
            PortResult(port=80, state="open", service="http"),
            PortResult(port=8080, state="open", service="http-alt"),
        ],
    )


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Signature loading tests
# ---------------------------------------------------------------------------


class TestGetIotSignatures:
    def test_returns_dict(self, sigs_fn):
        result = get_iot_signatures(_load_fn=sigs_fn)
        assert isinstance(result, dict)

    def test_has_mac_prefixes(self, sigs_fn):
        result = get_iot_signatures(_load_fn=sigs_fn)
        assert "mac_prefixes" in result

    def test_has_risky_ports(self, sigs_fn):
        result = get_iot_signatures(_load_fn=sigs_fn)
        assert "risky_ports" in result

    def test_has_iot_indicators(self, sigs_fn):
        result = get_iot_signatures(_load_fn=sigs_fn)
        assert "iot_indicators" in result

    def test_real_signatures_load(self):
        """Test that the bundled signatures file loads without error."""
        result = get_iot_signatures()
        assert "mac_prefixes" in result
        assert len(result["mac_prefixes"]) >= 15
        assert len(result["risky_ports"]) >= 10


# ---------------------------------------------------------------------------
# MAC prefix helper tests
# ---------------------------------------------------------------------------


class TestMacPrefix:
    def test_3_octet_prefix(self):
        assert _mac_prefix("B0:BE:76:12:34:56") == "B0:BE:76"

    def test_lowercase_normalised(self):
        assert _mac_prefix("b0:be:76:12:34:56") == "B0:BE:76"

    def test_dash_separator_normalised(self):
        assert _mac_prefix("B0-BE-76-12-34-56") == "B0:BE:76"

    def test_match_ring(self):
        match = _match_mac_prefix("B0:BE:76:12:34:56", MINIMAL_SIGNATURES)
        assert match is not None
        assert match["type"] == "camera"
        assert match["manufacturer"] == "Ring"

    def test_no_match_unknown_prefix(self):
        match = _match_mac_prefix("AA:BB:CC:DD:EE:FF", MINIMAL_SIGNATURES)
        assert match is None


# ---------------------------------------------------------------------------
# Vendor keyword tests
# ---------------------------------------------------------------------------


class TestVendorIsIot:
    def test_espressif_is_iot(self):
        assert _vendor_is_iot("Espressif Inc", MINIMAL_SIGNATURES) is True

    def test_ring_is_iot(self):
        assert _vendor_is_iot("Ring LLC", MINIMAL_SIGNATURES) is True

    def test_tuya_is_iot(self):
        assert _vendor_is_iot("Tuya Inc", MINIMAL_SIGNATURES) is True

    def test_apple_is_not_iot(self):
        assert _vendor_is_iot("Apple Inc", MINIMAL_SIGNATURES) is False

    def test_none_vendor_is_not_iot(self):
        assert _vendor_is_iot(None, MINIMAL_SIGNATURES) is False

    def test_empty_vendor_is_not_iot(self):
        assert _vendor_is_iot("", MINIMAL_SIGNATURES) is False

    def test_case_insensitive(self):
        assert _vendor_is_iot("TUYA SMART", MINIMAL_SIGNATURES) is True


# ---------------------------------------------------------------------------
# Port pattern matching tests
# ---------------------------------------------------------------------------


class TestClassifyByPorts:
    def test_camera_ports(self):
        result = _classify_by_ports([554, 80, 8080], MINIMAL_SIGNATURES)
        assert result == "camera"

    def test_speaker_ports(self):
        result = _classify_by_ports([1400, 8080, 7000], MINIMAL_SIGNATURES)
        assert result == "speaker"

    def test_hub_ports(self):
        result = _classify_by_ports([80, 443, 8080, 8443, 1900], MINIMAL_SIGNATURES)
        assert result == "hub"

    def test_single_port_no_match(self):
        """Single matching port shouldn't classify (requires >=2 overlapping)."""
        result = _classify_by_ports([554], MINIMAL_SIGNATURES)
        assert result is None

    def test_empty_ports_no_match(self):
        result = _classify_by_ports([], MINIMAL_SIGNATURES)
        assert result is None

    def test_no_iot_ports(self):
        result = _classify_by_ports([22, 3389], MINIMAL_SIGNATURES)
        assert result is None


# ---------------------------------------------------------------------------
# IoT device classification tests
# ---------------------------------------------------------------------------


class TestClassifyIotDevice:
    def test_mac_prefix_ring_camera(self, ring_device, sigs_fn):
        result = classify_iot_device(ring_device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "camera"
        assert result.manufacturer == "Ring"
        assert result.ip == "192.168.1.100"

    def test_mac_prefix_echo_speaker(self, echo_device, sigs_fn):
        result = classify_iot_device(echo_device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "speaker"
        assert result.manufacturer == "Amazon"
        assert result.model == "Echo"

    def test_mac_prefix_hue_hub(self, hue_device, sigs_fn):
        result = classify_iot_device(hue_device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "hub"

    def test_mac_prefix_nest_thermostat(self, nest_device, sigs_fn):
        result = classify_iot_device(nest_device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "thermostat"

    def test_mac_prefix_kasa_plug(self, kasa_device, sigs_fn):
        result = classify_iot_device(kasa_device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "plug"

    def test_vendor_keyword_espressif(self, sigs_fn):
        device = Device(ip="192.168.1.200", mac="AA:BB:CC:DD:EE:FF", vendor="Espressif Systems")
        result = classify_iot_device(device, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "unknown"

    def test_vendor_keyword_tuya(self, sigs_fn):
        device = Device(ip="192.168.1.201", mac="AA:BB:CC:11:22:33", vendor="Tuya Global")
        result = classify_iot_device(device, _signatures_fn=sigs_fn)
        assert result is not None

    def test_port_pattern_camera(self, laptop_device, camera_port_scan, sigs_fn):
        result = classify_iot_device(laptop_device, scan=camera_port_scan, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "camera"

    def test_non_iot_device_returns_none(self, laptop_device, sigs_fn):
        result = classify_iot_device(laptop_device, _signatures_fn=sigs_fn)
        assert result is None

    def test_non_iot_with_non_iot_ports_returns_none(self, laptop_device, sigs_fn):
        scan = HostScanResult(
            host="192.168.1.50",
            ports=[PortResult(port=22, state="open"), PortResult(port=3389, state="open")],
        )
        result = classify_iot_device(laptop_device, scan=scan, _signatures_fn=sigs_fn)
        assert result is None

    def test_profile_hint_camera_type(self, laptop_device, sigs_fn):
        profile = DeviceProfile(
            ip="192.168.1.50",
            mac="AA:BB:CC:DD:EE:FF",
            device_type="camera",
        )
        result = classify_iot_device(laptop_device, profile=profile, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.device_type == "camera"

    def test_profile_hint_iot_manufacturer(self, laptop_device, sigs_fn):
        profile = DeviceProfile(
            ip="192.168.1.50",
            mac="AA:BB:CC:DD:EE:FF",
            device_type="desktop",
            manufacturer="Wyze Labs",
        )
        result = classify_iot_device(laptop_device, profile=profile, _signatures_fn=sigs_fn)
        assert result is not None

    def test_mac_overrides_port_pattern(self, ring_device, camera_port_scan, sigs_fn):
        """MAC match should always set type regardless of ports."""
        result = classify_iot_device(ring_device, scan=camera_port_scan, _signatures_fn=sigs_fn)
        assert result is not None
        assert result.manufacturer == "Ring"


# ---------------------------------------------------------------------------
# Risk assessment tests
# ---------------------------------------------------------------------------


class TestAssessDeviceRisk:
    def _make_iot(self, ip="192.168.1.100", mac="B0:BE:76:11:22:33",
                  device_type="camera", manufacturer="Ring") -> IoTDevice:
        return IoTDevice(ip=ip, mac=mac, device_type=device_type, manufacturer=manufacturer)

    def test_no_scan_no_risky_ports(self, sigs_fn):
        iot = self._make_iot()
        result = assess_device_risk(iot, scan=None, _signatures_fn=sigs_fn)
        assert result.risk_score == 0
        assert result.risky_ports == []
        assert result.issues == []

    def test_telnet_adds_30(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=23, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 30
        assert 23 in result.risky_ports

    def test_adb_adds_30(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=5555, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 30
        assert 5555 in result.risky_ports

    def test_ftp_adds_20(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=21, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 20
        assert 21 in result.risky_ports

    def test_mqtt_adds_20(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=1883, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 20
        assert 1883 in result.risky_ports

    def test_http_adds_10(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[
                PortResult(port=80, state="open"),
                PortResult(port=443, state="open"),
            ],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 10
        assert 80 in result.risky_ports

    def test_http_without_https_adds_15_penalty(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=80, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        # HTTP = 10, HTTP-without-HTTPS = +15 → total 25
        assert result.risk_score == 25

    def test_multiple_risky_ports_accumulate(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[
                PortResult(port=23, state="open"),   # +30 critical
                PortResult(port=1883, state="open"),  # +20 high
                PortResult(port=80, state="open"),    # +10 medium + 15 http-no-https
            ],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        # 30 + 20 + 10 + 15 = 75
        assert result.risk_score == 75

    def test_risk_score_capped_at_100(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[
                PortResult(port=23, state="open"),    # +30
                PortResult(port=5555, state="open"),  # +30
                PortResult(port=21, state="open"),    # +20
                PortResult(port=1883, state="open"),  # +20
                PortResult(port=80, state="open"),    # +10 + 15
            ],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert result.risk_score == 100

    def test_unknown_manufacturer_adds_10(self, sigs_fn):
        iot = IoTDevice(ip="192.168.1.100", mac="AA:BB:CC:DD:EE:FF",
                        device_type="plug", manufacturer=None)
        result = assess_device_risk(iot, scan=None, _signatures_fn=sigs_fn)
        assert result.risk_score == 10

    def test_issues_populated_for_risky_ports(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=23, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert any("Telnet" in issue for issue in result.issues)

    def test_recommendations_populated(self, sigs_fn):
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=23, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert len(result.recommendations) > 0

    def test_low_severity_port_no_score(self, sigs_fn):
        """Low severity ports (score 0) should not appear in risky_ports."""
        iot = self._make_iot()
        scan = HostScanResult(
            host="192.168.1.100",
            ports=[PortResult(port=1900, state="open")],
        )
        result = assess_device_risk(iot, scan=scan, _signatures_fn=sigs_fn)
        assert 1900 not in result.risky_ports
        assert result.risk_score == 0


# ---------------------------------------------------------------------------
# Format risk level tests
# ---------------------------------------------------------------------------


class TestFormatRiskLevel:
    def test_critical_at_80(self):
        assert format_risk_level(80) == "critical"

    def test_critical_at_100(self):
        assert format_risk_level(100) == "critical"

    def test_high_at_60(self):
        assert format_risk_level(60) == "high"

    def test_high_at_79(self):
        assert format_risk_level(79) == "high"

    def test_medium_at_40(self):
        assert format_risk_level(40) == "medium"

    def test_low_at_20(self):
        assert format_risk_level(20) == "low"

    def test_minimal_at_0(self):
        assert format_risk_level(0) == "minimal"

    def test_minimal_at_19(self):
        assert format_risk_level(19) == "minimal"


# ---------------------------------------------------------------------------
# Full audit pipeline tests
# ---------------------------------------------------------------------------


class TestAuditNetwork:
    def test_empty_network(self, sigs_fn):
        report = audit_network([], _signatures_fn=sigs_fn)
        assert isinstance(report, IoTAuditReport)
        assert report.devices == []
        assert report.high_risk_count == 0
        assert report.total_issues == 0

    def test_no_iot_devices(self, laptop_device, sigs_fn):
        report = audit_network([laptop_device], _signatures_fn=sigs_fn)
        assert report.devices == []
        assert report.high_risk_count == 0

    def test_iot_devices_classified(self, ring_device, echo_device, sigs_fn):
        report = audit_network([ring_device, echo_device], _signatures_fn=sigs_fn)
        assert len(report.devices) == 2
        ips = {d.ip for d in report.devices}
        assert ring_device.ip in ips
        assert echo_device.ip in ips

    def test_high_risk_counted(self, ring_device, sigs_fn):
        scans = {
            ring_device.ip: HostScanResult(
                host=ring_device.ip,
                ports=[
                    PortResult(port=23, state="open"),   # +30
                    PortResult(port=5555, state="open"),  # +30 → 60 = high
                ],
            )
        }
        report = audit_network([ring_device], scans=scans, _signatures_fn=sigs_fn)
        assert report.high_risk_count == 1

    def test_total_issues_counted(self, ring_device, sigs_fn):
        scans = {
            ring_device.ip: HostScanResult(
                host=ring_device.ip,
                ports=[PortResult(port=23, state="open")],
            )
        }
        report = audit_network([ring_device], scans=scans, _signatures_fn=sigs_fn)
        assert report.total_issues > 0

    def test_recommendations_generated(self, ring_device, sigs_fn):
        report = audit_network([ring_device], _signatures_fn=sigs_fn)
        assert len(report.recommendations) > 0

    def test_mixed_devices(self, ring_device, laptop_device, sigs_fn):
        report = audit_network([ring_device, laptop_device], _signatures_fn=sigs_fn)
        assert len(report.devices) == 1
        assert report.devices[0].ip == ring_device.ip

    def test_scan_fn_called_when_no_scans(self, ring_device, sigs_fn):
        mock_scan = MagicMock(return_value=HostScanResult(host=ring_device.ip, ports=[]))
        report = audit_network([ring_device], _signatures_fn=sigs_fn, _scan_fn=mock_scan)
        mock_scan.assert_called_once_with(ring_device.ip)

    def test_scan_fn_not_called_when_scans_provided(self, ring_device, sigs_fn):
        mock_scan = MagicMock()
        scans = {ring_device.ip: HostScanResult(host=ring_device.ip, ports=[])}
        audit_network([ring_device], scans=scans, _signatures_fn=sigs_fn, _scan_fn=mock_scan)
        mock_scan.assert_not_called()

    def test_report_timestamp(self, ring_device, sigs_fn):
        before = datetime.now()
        report = audit_network([ring_device], _signatures_fn=sigs_fn)
        after = datetime.now()
        assert before <= report.timestamp <= after


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCliAudit:
    def test_audit_no_devices(self, runner, sigs_fn):
        with patch("netglance.cli.iot.arp_scan", return_value=[]):
            result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "No devices found" in result.output

    def test_audit_with_iot_devices(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=ring_device.ip, ports=[])):
            result = runner.invoke(app, ["audit", "--subnet", "192.168.1.0/24"])
        assert result.exit_code == 0

    def test_audit_json_output(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=ring_device.ip, ports=[])):
            result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "devices" in data
        assert "high_risk_count" in data

    def test_audit_skip_scan(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]):
            result = runner.invoke(app, ["audit", "--skip-scan"])
        assert result.exit_code == 0

    def test_audit_discovery_failure(self, runner):
        with patch("netglance.cli.iot.arp_scan", side_effect=Exception("network down")):
            result = runner.invoke(app, ["audit"])
        assert result.exit_code == 1
        assert "Discovery failed" in result.output

    def test_check_non_iot_device(self, runner, laptop_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[laptop_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=laptop_device.ip, ports=[])):
            result = runner.invoke(app, ["check", "192.168.1.50"])
        assert result.exit_code == 0
        assert "does not appear to be an IoT device" in result.output

    def test_check_iot_device(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=ring_device.ip, ports=[])):
            result = runner.invoke(app, ["check", "192.168.1.100"])
        assert result.exit_code == 0

    def test_check_json_output(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=ring_device.ip, ports=[])):
            result = runner.invoke(app, ["check", "192.168.1.100", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "device_type" in data
        assert "risk_score" in data

    def test_check_non_iot_json_output(self, runner, laptop_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[laptop_device]), \
             patch("netglance.cli.iot.quick_scan",
                   return_value=HostScanResult(host=laptop_device.ip, ports=[])):
            result = runner.invoke(app, ["check", "192.168.1.50", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["is_iot"] is False

    def test_list_command(self, runner, ring_device):
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_no_devices(self, runner):
        with patch("netglance.cli.iot.arp_scan", return_value=[]):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No IoT devices found" in result.output

    def test_audit_high_risk_shown_in_details(self, runner, ring_device):
        telnet_scan = HostScanResult(
            host=ring_device.ip,
            ports=[
                PortResult(port=23, state="open"),
                PortResult(port=5555, state="open"),
            ],
        )
        with patch("netglance.cli.iot.arp_scan", return_value=[ring_device]), \
             patch("netglance.cli.iot.quick_scan", return_value=telnet_scan):
            result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "High-Risk" in result.output
