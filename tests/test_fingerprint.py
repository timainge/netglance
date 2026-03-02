"""Tests for the fingerprint module."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.fingerprint import app
from netglance.modules.fingerprint import (
    classify_by_hostname,
    classify_by_ports,
    classify_device,
    detect_randomized_mac,
    fingerprint_all,
    fingerprint_device,
    fingerprint_mdns,
    fingerprint_upnp,
    label_device,
)
from netglance.store.models import Device, DeviceFingerprint, DeviceProfile

runner = CliRunner()


# ---------------------------------------------------------------------------
# detect_randomized_mac
# ---------------------------------------------------------------------------


def test_detect_randomized_mac_locally_administered():
    # 0x02 bit set in first octet = locally administered (randomized)
    assert detect_randomized_mac("02:ab:cd:ef:01:23") is True


def test_detect_randomized_mac_globally_administered():
    # Common globally administered OUIs — first octet is even and 0x02 not set
    assert detect_randomized_mac("00:1a:2b:3c:4d:5e") is False


def test_detect_randomized_mac_apple_oui():
    assert detect_randomized_mac("f8:ff:c2:11:22:33") is False


def test_detect_randomized_mac_random_bit_set():
    # 0x06 = 0b00000110 — both locally-administered and multicast bits set
    assert detect_randomized_mac("06:ab:cd:ef:01:23") is True


def test_detect_randomized_mac_invalid_mac():
    # Should not raise; just return False
    assert detect_randomized_mac("not-a-mac") is False


def test_detect_randomized_mac_dashes():
    # MAC with dashes
    assert detect_randomized_mac("02-ab-cd-ef-01-23") is True


def test_detect_randomized_mac_uppercase():
    assert detect_randomized_mac("00:1A:2B:3C:4D:5E") is False


# ---------------------------------------------------------------------------
# classify_by_hostname
# ---------------------------------------------------------------------------


def test_classify_hostname_iphone():
    device_type, conf = classify_by_hostname("iPhone-Tim")
    assert device_type == "smartphone"
    assert conf == pytest.approx(0.9)


def test_classify_hostname_ipad():
    device_type, conf = classify_by_hostname("iPad-Work")
    assert device_type == "tablet"
    assert conf == pytest.approx(0.9)


def test_classify_hostname_galaxy():
    device_type, conf = classify_by_hostname("Galaxy-S21")
    assert device_type == "smartphone"
    assert conf == pytest.approx(0.85)


def test_classify_hostname_sm_prefix():
    device_type, conf = classify_by_hostname("SM-G990B")
    assert device_type == "smartphone"
    assert conf == pytest.approx(0.85)


def test_classify_hostname_desktop():
    device_type, conf = classify_by_hostname("DESKTOP-ABC123")
    assert device_type == "desktop"
    assert conf == pytest.approx(0.8)


def test_classify_hostname_macbook():
    device_type, conf = classify_by_hostname("MacBook-Pro")
    assert device_type == "laptop"
    assert conf == pytest.approx(0.85)


def test_classify_hostname_printer_npi():
    device_type, conf = classify_by_hostname("NPIABCDEF")
    assert device_type == "printer"
    assert conf == pytest.approx(0.8)


def test_classify_hostname_esp_iot():
    device_type, conf = classify_by_hostname("ESP_1A2B3C")
    assert device_type == "iot"
    assert conf == pytest.approx(0.7)


def test_classify_hostname_raspberrypi():
    device_type, conf = classify_by_hostname("raspberrypi")
    assert device_type == "server"
    assert conf == pytest.approx(0.7)


def test_classify_hostname_no_match():
    device_type, conf = classify_by_hostname("unknown-device-xyz")
    assert device_type is None
    assert conf == 0.0


def test_classify_hostname_empty():
    device_type, conf = classify_by_hostname("")
    assert device_type is None
    assert conf == 0.0


# ---------------------------------------------------------------------------
# classify_by_ports
# ---------------------------------------------------------------------------

_SAMPLE_SIGNATURES = {
    "port_signatures": {
        "631": {"type": "printer", "confidence": 0.8},
        "9100": {"type": "printer", "confidence": 0.75},
        "9000,9080": {"type": "speaker", "subtype": "sonos", "confidence": 0.9},
        "8008,8443": {"type": "streaming-stick", "subtype": "chromecast", "confidence": 0.85},
        "62078": {"type": "smartphone", "subtype": "iphone", "confidence": 0.7},
        "32400": {"type": "media-server", "subtype": "plex", "confidence": 0.85},
    },
    "mdns_signatures": {},
    "hostname_patterns": [],
}


def _make_sigs_fn(sigs=None):
    data = sigs if sigs is not None else _SAMPLE_SIGNATURES
    return lambda: data


def test_classify_by_ports_single_port_printer():
    device_type, conf = classify_by_ports([631], _signatures_fn=_make_sigs_fn())
    assert device_type == "printer"
    assert conf == pytest.approx(0.8)


def test_classify_by_ports_multi_port_sonos():
    device_type, conf = classify_by_ports([9000, 9080, 443], _signatures_fn=_make_sigs_fn())
    assert device_type == "speaker"
    assert conf == pytest.approx(0.9)


def test_classify_by_ports_plex():
    device_type, conf = classify_by_ports([32400, 80], _signatures_fn=_make_sigs_fn())
    assert device_type == "media-server"
    assert conf == pytest.approx(0.85)


def test_classify_by_ports_unknown():
    device_type, conf = classify_by_ports([12345, 54321], _signatures_fn=_make_sigs_fn())
    assert device_type is None
    assert conf == 0.0


def test_classify_by_ports_empty_list():
    device_type, conf = classify_by_ports([], _signatures_fn=_make_sigs_fn())
    assert device_type is None
    assert conf == 0.0


def test_classify_by_ports_highest_confidence_wins():
    # Both 631 (0.8) and 9000+9080 (0.9) match — Sonos should win
    device_type, conf = classify_by_ports([631, 9000, 9080], _signatures_fn=_make_sigs_fn())
    assert device_type == "speaker"
    assert conf == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# fingerprint_mdns
# ---------------------------------------------------------------------------


def _make_mdns_browse(results_by_type: dict[str, list[dict]]):
    """Return a mock browse fn that returns results keyed by service type."""
    def browse(service_type: str, timeout: float) -> list[dict]:
        return results_by_type.get(service_type, [])
    return browse


def test_fingerprint_mdns_finds_service():
    browse_fn = _make_mdns_browse({
        "_airplay._tcp": [{"ip": "192.168.1.10", "txt_records": {"model": "AppleTV6,2"}}],
    })
    result = fingerprint_mdns("192.168.1.10", _browse_fn=browse_fn)
    assert "_airplay._tcp" in result["services"]
    assert result["txt_records"]["_airplay._tcp"]["model"] == "AppleTV6,2"


def test_fingerprint_mdns_ignores_other_ips():
    browse_fn = _make_mdns_browse({
        "_airplay._tcp": [{"ip": "192.168.1.99", "txt_records": {}}],
    })
    result = fingerprint_mdns("192.168.1.10", _browse_fn=browse_fn)
    assert result["services"] == []


def test_fingerprint_mdns_multiple_services():
    browse_fn = _make_mdns_browse({
        "_airplay._tcp": [{"ip": "192.168.1.10", "txt_records": {}}],
        "_raop._tcp": [{"ip": "192.168.1.10", "txt_records": {}}],
    })
    result = fingerprint_mdns("192.168.1.10", _browse_fn=browse_fn)
    assert "_airplay._tcp" in result["services"]
    assert "_raop._tcp" in result["services"]


def test_fingerprint_mdns_no_services():
    browse_fn = _make_mdns_browse({})
    result = fingerprint_mdns("192.168.1.10", _browse_fn=browse_fn)
    assert result["services"] == []
    assert result["txt_records"] == {}


def test_fingerprint_mdns_browse_fn_exception_handled():
    """A browse_fn that raises should not crash fingerprint_mdns."""
    def bad_browse(svc_type, timeout):
        raise RuntimeError("network error")

    result = fingerprint_mdns("192.168.1.10", _browse_fn=bad_browse)
    assert result["services"] == []


# ---------------------------------------------------------------------------
# fingerprint_upnp
# ---------------------------------------------------------------------------

_SAMPLE_UPNP_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>My Sonos Speaker</friendlyName>
    <manufacturer>Sonos, Inc.</manufacturer>
    <modelName>Sonos One</modelName>
    <modelNumber>S18</modelNumber>
    <deviceType>urn:schemas-upnp-org:device:ZonePlayer:1</deviceType>
  </device>
</root>"""


def test_fingerprint_upnp_parses_xml():
    ssdp_fn = lambda: [{"location": "http://192.168.1.10:1400/xml/device_description.xml", "ip": "192.168.1.10"}]
    http_fn = lambda url: _SAMPLE_UPNP_XML

    result = fingerprint_upnp("192.168.1.10", _ssdp_fn=ssdp_fn, _http_fn=http_fn)
    assert result["friendly_name"] == "My Sonos Speaker"
    assert result["manufacturer"] == "Sonos, Inc."
    assert result["model_name"] == "Sonos One"
    assert result["model_number"] == "S18"


def test_fingerprint_upnp_no_ssdp_match():
    ssdp_fn = lambda: [{"location": "http://192.168.1.99:1400/xml", "ip": "192.168.1.99"}]
    http_fn = lambda url: _SAMPLE_UPNP_XML

    result = fingerprint_upnp("192.168.1.10", _ssdp_fn=ssdp_fn, _http_fn=http_fn)
    assert result["friendly_name"] is None


def test_fingerprint_upnp_ssdp_returns_empty():
    ssdp_fn = lambda: []
    http_fn = lambda url: ""

    result = fingerprint_upnp("192.168.1.10", _ssdp_fn=ssdp_fn, _http_fn=http_fn)
    assert result["friendly_name"] is None
    assert result["manufacturer"] is None


def test_fingerprint_upnp_http_exception_handled():
    ssdp_fn = lambda: [{"location": "http://192.168.1.10/xml", "ip": "192.168.1.10"}]
    def bad_http(url):
        raise ConnectionError("timed out")

    result = fingerprint_upnp("192.168.1.10", _ssdp_fn=ssdp_fn, _http_fn=bad_http)
    assert result["friendly_name"] is None


def test_fingerprint_upnp_ssdp_exception_handled():
    def bad_ssdp():
        raise OSError("network error")

    result = fingerprint_upnp("192.168.1.10", _ssdp_fn=bad_ssdp, _http_fn=lambda u: "")
    assert result["friendly_name"] is None


# ---------------------------------------------------------------------------
# fingerprint_device
# ---------------------------------------------------------------------------


def test_fingerprint_device_assembles_correctly():
    browse_fn = _make_mdns_browse({
        "_airplay._tcp": [{"ip": "192.168.1.10", "txt_records": {"model": "AppleTV"}}],
    })
    ssdp_fn = lambda: []
    http_fn = lambda url: ""

    fp = fingerprint_device(
        ip="192.168.1.10",
        mac="00:1a:2b:3c:4d:5e",
        hostname="AppleTV-Living",
        open_ports=[7000, 49152],
        _browse_fn=browse_fn,
        _ssdp_fn=ssdp_fn,
        _http_fn=http_fn,
    )

    assert fp.mac == "00:1a:2b:3c:4d:5e"
    assert fp.hostname == "AppleTV-Living"
    assert fp.mac_is_randomized is False
    assert "_airplay._tcp" in fp.mdns_services
    assert fp.open_ports == [7000, 49152]


def test_fingerprint_device_randomized_mac():
    browse_fn = _make_mdns_browse({})
    ssdp_fn = lambda: []
    fp = fingerprint_device(
        ip="192.168.1.50",
        mac="02:aa:bb:cc:dd:ee",
        _browse_fn=browse_fn,
        _ssdp_fn=ssdp_fn,
        _http_fn=lambda u: "",
    )
    assert fp.mac_is_randomized is True


def test_fingerprint_device_no_ports():
    browse_fn = _make_mdns_browse({})
    fp = fingerprint_device(
        ip="10.0.0.1",
        mac="aa:bb:cc:dd:ee:ff",
        _browse_fn=browse_fn,
        _ssdp_fn=lambda: [],
        _http_fn=lambda u: "",
    )
    assert fp.open_ports == []


# ---------------------------------------------------------------------------
# classify_device
# ---------------------------------------------------------------------------


def _make_fp(**kwargs) -> DeviceFingerprint:
    defaults = {
        "mac": "00:11:22:33:44:55",
        "mac_is_randomized": False,
        "oui_vendor": None,
        "hostname": None,
        "mdns_services": [],
        "mdns_txt_records": {},
        "upnp_friendly_name": None,
        "upnp_manufacturer": None,
        "upnp_model_name": None,
        "upnp_model_number": None,
        "upnp_device_type": None,
        "open_ports": [],
        "banners": {},
    }
    defaults.update(kwargs)
    return DeviceFingerprint(**defaults)


def test_classify_device_upnp_takes_priority():
    fp = _make_fp(
        upnp_friendly_name="My Printer",
        upnp_manufacturer="HP",
        upnp_device_type="urn:schemas-upnp-org:device:Printer:1",
        hostname="iPhone-Tim",  # would classify as smartphone but upnp wins
    )
    profile = classify_device(fp)
    assert profile.classification_method == "upnp"
    assert profile.manufacturer == "HP"
    assert profile.friendly_name == "My Printer"


def test_classify_device_mdns_over_ports():
    fp = _make_fp(
        mdns_services=["_googlecast._tcp"],  # conf 0.9
        open_ports=[631],  # conf 0.8 printer — mdns wins
    )
    profile = classify_device(fp)
    assert profile.classification_method == "mdns"
    assert profile.device_type == "streaming-stick"
    assert profile.confidence == pytest.approx(0.9)


def test_classify_device_ports_over_hostname():
    fp = _make_fp(
        open_ports=[32400],  # plex, conf 0.85
        hostname="DESKTOP-XYZ",  # conf 0.8
    )
    profile = classify_device(fp)
    assert profile.classification_method == "ports"
    assert profile.device_type == "media-server"


def test_classify_device_hostname_fallback():
    fp = _make_fp(hostname="iPhone-Tim")
    profile = classify_device(fp)
    assert profile.classification_method == "hostname"
    assert profile.device_type == "smartphone"
    assert profile.confidence == pytest.approx(0.9)


def test_classify_device_unknown():
    fp = _make_fp()
    profile = classify_device(fp)
    assert profile.device_type is None
    assert profile.confidence == 0.0


def test_classify_device_returns_device_profile():
    fp = _make_fp(hostname="raspberrypi")
    profile = classify_device(fp)
    assert isinstance(profile, DeviceProfile)
    assert profile.fingerprint is fp


# ---------------------------------------------------------------------------
# fingerprint_all
# ---------------------------------------------------------------------------


def test_fingerprint_all_processes_devices():
    devices = [
        Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01", hostname="iPhone-Tim", vendor="Apple"),
        Device(ip="192.168.1.2", mac="aa:bb:cc:dd:ee:02", hostname="DESKTOP-PC", vendor="Dell"),
    ]
    browse_fn = _make_mdns_browse({})
    ssdp_fn = lambda: []
    http_fn = lambda u: ""

    profiles = fingerprint_all(
        devices,
        _browse_fn=browse_fn,
        _ssdp_fn=ssdp_fn,
        _http_fn=http_fn,
    )

    assert len(profiles) == 2
    assert profiles[0].ip == "192.168.1.1"
    assert profiles[0].mac == "aa:bb:cc:dd:ee:01"
    assert profiles[0].device_type == "smartphone"
    assert profiles[1].ip == "192.168.1.2"
    assert profiles[1].device_type == "desktop"


def test_fingerprint_all_empty_list():
    profiles = fingerprint_all(
        [],
        _browse_fn=_make_mdns_browse({}),
        _ssdp_fn=lambda: [],
        _http_fn=lambda u: "",
    )
    assert profiles == []


def test_fingerprint_all_sets_vendor_as_manufacturer():
    devices = [
        Device(ip="10.0.0.1", mac="00:11:22:33:44:55", hostname=None, vendor="Sonos, Inc."),
    ]
    profiles = fingerprint_all(
        devices,
        _browse_fn=_make_mdns_browse({}),
        _ssdp_fn=lambda: [],
        _http_fn=lambda u: "",
    )
    assert profiles[0].manufacturer == "Sonos, Inc."


# ---------------------------------------------------------------------------
# label_device
# ---------------------------------------------------------------------------


def test_label_device_basic():
    result = label_device(mac="aa:bb:cc:dd:ee:ff", label="Living Room TV")
    assert result["mac"] == "aa:bb:cc:dd:ee:ff"
    assert result["label"] == "Living Room TV"
    assert result["device_type"] is None


def test_label_device_with_type():
    result = label_device(mac="aa:bb:cc:dd:ee:ff", label="TV", device_type="smart-tv")
    assert result["device_type"] == "smart-tv"


def test_label_device_returns_dict():
    result = label_device(mac="00:11:22:33:44:55", label="My Device")
    assert isinstance(result, dict)
    assert set(result.keys()) == {"mac", "label", "device_type"}


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_label_ip(monkeypatch):
    result = runner.invoke(app, ["--label", "My TV", "192.168.1.10"])
    assert result.exit_code == 0
    assert "My TV" in result.output or "Labeled" in result.output


def test_cli_label_json(monkeypatch):
    result = runner.invoke(app, ["--label", "My TV", "--json", "192.168.1.10"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["label"] == "My TV"


def test_cli_single_ip(monkeypatch):
    """Single IP fingerprint with mocked network calls."""
    browse_fn = _make_mdns_browse({})

    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_mdns_browse",
        lambda svc, timeout: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_ssdp_search",
        lambda: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_http_fetch",
        lambda url: "",
    )

    result = runner.invoke(app, ["192.168.1.10"])
    assert result.exit_code == 0


def test_cli_all_devices_no_devices(monkeypatch):
    """All-devices mode when ARP scan returns nothing."""
    monkeypatch.setattr(
        "netglance.cli.fingerprint.arp_scan",
        lambda subnet, **kwargs: [],
    )
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "No devices" in result.output


def test_cli_all_devices_with_results(monkeypatch):
    """All-devices mode with one discovered device."""
    device = Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01", hostname="iPhone-Tim")

    monkeypatch.setattr(
        "netglance.cli.fingerprint.arp_scan",
        lambda subnet, **kwargs: [device],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_mdns_browse",
        lambda svc, timeout: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_ssdp_search",
        lambda: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_http_fetch",
        lambda url: "",
    )

    result = runner.invoke(app, [])
    assert result.exit_code == 0
    # Rich may truncate in narrow terminals; check for any device identifier
    assert "192.168.1" in result.output or "smartphone" in result.output or "hostname" in result.output


def test_cli_unknown_filter(monkeypatch):
    """--unknown filter shows only unclassified devices."""
    device = Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01", hostname=None)

    monkeypatch.setattr(
        "netglance.cli.fingerprint.arp_scan",
        lambda subnet, **kwargs: [device],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_mdns_browse",
        lambda svc, timeout: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_ssdp_search",
        lambda: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_http_fetch",
        lambda url: "",
    )

    result = runner.invoke(app, ["--unknown"])
    assert result.exit_code == 0


def test_cli_json_output(monkeypatch):
    """--json flag produces valid JSON."""
    device = Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01", hostname="iPhone-Tim")

    monkeypatch.setattr(
        "netglance.cli.fingerprint.arp_scan",
        lambda subnet, **kwargs: [device],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_mdns_browse",
        lambda svc, timeout: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_ssdp_search",
        lambda: [],
    )
    monkeypatch.setattr(
        "netglance.modules.fingerprint._default_http_fetch",
        lambda url: "",
    )

    result = runner.invoke(app, ["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["ip"] == "192.168.1.1"


def test_cli_arp_scan_error(monkeypatch):
    """CLI exits with code 1 if discovery fails."""
    def bad_arp(subnet, **kwargs):
        raise RuntimeError("permission denied")

    monkeypatch.setattr("netglance.cli.fingerprint.arp_scan", bad_arp)
    result = runner.invoke(app, [])
    assert result.exit_code == 1
