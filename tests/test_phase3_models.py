"""Tests for Phase 3 shared types (DeviceFingerprint, DeviceProfile)."""

import pytest
from datetime import datetime
from netglance.store.models import DeviceFingerprint, DeviceProfile


class TestDeviceFingerprint:
    def test_basic_creation(self):
        fp = DeviceFingerprint(mac="aa:bb:cc:dd:ee:ff")
        assert fp.mac == "aa:bb:cc:dd:ee:ff"
        assert fp.mac_is_randomized is False
        assert fp.oui_vendor is None
        assert fp.hostname is None
        assert fp.mdns_services == []
        assert fp.mdns_txt_records == {}
        assert fp.open_ports == []
        assert fp.banners == {}

    def test_full_creation(self):
        fp = DeviceFingerprint(
            mac="aa:bb:cc:dd:ee:ff",
            mac_is_randomized=True,
            oui_vendor="Apple, Inc.",
            hostname="iPhone",
            mdns_services=["_airplay._tcp", "_companion-link._tcp"],
            mdns_txt_records={"_airplay._tcp": {"model": "AppleTV6,2"}},
            upnp_friendly_name="Living Room TV",
            upnp_manufacturer="Samsung",
            upnp_model_name="UN55NU8000",
            upnp_model_number="55",
            upnp_device_type="urn:schemas-upnp-org:device:MediaRenderer:1",
            open_ports=[80, 443, 8008],
            banners={80: "nginx/1.24", 443: ""},
        )
        assert fp.mac_is_randomized is True
        assert len(fp.mdns_services) == 2
        assert fp.upnp_friendly_name == "Living Room TV"
        assert 80 in fp.banners
        assert len(fp.open_ports) == 3

    def test_default_lists_independent(self):
        fp1 = DeviceFingerprint(mac="aa:bb:cc:dd:ee:01")
        fp2 = DeviceFingerprint(mac="aa:bb:cc:dd:ee:02")
        fp1.mdns_services.append("_http._tcp")
        assert fp2.mdns_services == []

    def test_default_dicts_independent(self):
        fp1 = DeviceFingerprint(mac="aa:bb:cc:dd:ee:01")
        fp2 = DeviceFingerprint(mac="aa:bb:cc:dd:ee:02")
        fp1.banners[80] = "test"
        assert fp2.banners == {}


class TestDeviceProfile:
    def test_basic_creation(self):
        dp = DeviceProfile(ip="192.168.1.50", mac="aa:bb:cc:dd:ee:ff")
        assert dp.ip == "192.168.1.50"
        assert dp.mac == "aa:bb:cc:dd:ee:ff"
        assert dp.device_type is None
        assert dp.confidence == 0.0
        assert dp.fingerprint is None
        assert dp.user_label is None
        assert dp.last_profiled is None

    def test_full_creation(self):
        fp = DeviceFingerprint(mac="aa:bb:cc:dd:ee:ff", oui_vendor="Sonos")
        dp = DeviceProfile(
            ip="192.168.1.50",
            mac="aa:bb:cc:dd:ee:ff",
            device_type="speaker",
            device_category="media",
            os="Linux",
            manufacturer="Sonos",
            model="One",
            friendly_name="Kitchen Speaker",
            confidence=0.95,
            classification_method="mdns+upnp",
            fingerprint=fp,
            user_label="Kitchen Sonos",
            last_profiled=datetime(2026, 1, 1),
        )
        assert dp.device_type == "speaker"
        assert dp.confidence == 0.95
        assert dp.fingerprint is not None
        assert dp.fingerprint.oui_vendor == "Sonos"
        assert dp.user_label == "Kitchen Sonos"
        assert dp.last_profiled == datetime(2026, 1, 1)

    def test_profile_without_fingerprint(self):
        dp = DeviceProfile(
            ip="192.168.1.1",
            mac="00:11:22:33:44:55",
            device_type="router",
            confidence=0.8,
        )
        assert dp.fingerprint is None
        assert dp.device_type == "router"

    def test_confidence_range(self):
        dp = DeviceProfile(ip="10.0.0.1", mac="ff:ff:ff:ff:ff:ff", confidence=1.0)
        assert dp.confidence == 1.0
        dp2 = DeviceProfile(ip="10.0.0.2", mac="00:00:00:00:00:00", confidence=0.0)
        assert dp2.confidence == 0.0
