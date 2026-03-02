"""IoT device detection and security audit module.

Identifies IoT devices on the network using MAC prefix matching, vendor
keyword detection, and port pattern analysis. Assesses security risk based
on open risky ports and device characteristics.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from netglance.store.models import (
    Device,
    DeviceProfile,
    HostScanResult,
    IoTAuditReport,
    IoTDevice,
)

# Cache for loaded signatures
_SIGNATURES_CACHE: dict | None = None


# ---------------------------------------------------------------------------
# Signature loading
# ---------------------------------------------------------------------------


def _load_iot_signatures() -> dict:
    """Load IoT device signatures from the bundled JSON data file."""
    data_path = files("netglance.data").joinpath("iot_signatures.json")
    return json.loads(data_path.read_text(encoding="utf-8"))


def get_iot_signatures(*, _load_fn=None) -> dict:
    """Return the IoT signature database, loading and caching on first call.

    Args:
        _load_fn: Injectable loader function () -> dict. Defaults to the
                  bundled JSON loader. Pass a custom function in tests.

    Returns:
        The full signatures dict with keys: mac_prefixes, risky_ports,
        iot_indicators.
    """
    global _SIGNATURES_CACHE
    if _load_fn is not None:
        # In tests we always use the injected function (no caching side-effects)
        return _load_fn()
    if _SIGNATURES_CACHE is None:
        _SIGNATURES_CACHE = _load_iot_signatures()
    return _SIGNATURES_CACHE


# ---------------------------------------------------------------------------
# Risk level helpers
# ---------------------------------------------------------------------------


def format_risk_level(score: int) -> str:
    """Convert a numeric risk score to a human-readable risk level label.

    Args:
        score: Integer risk score, 0–100.

    Returns:
        One of: "critical", "high", "medium", "low", "minimal".
    """
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "minimal"


# ---------------------------------------------------------------------------
# MAC prefix matching
# ---------------------------------------------------------------------------


def _normalise_mac(mac: str) -> str:
    """Uppercase and colon-separate a MAC address."""
    cleaned = mac.replace("-", ":").upper()
    return cleaned


def _mac_prefix(mac: str, octets: int = 3) -> str:
    """Return the first *octets* octets of *mac* as an uppercase colon string."""
    parts = _normalise_mac(mac).split(":")
    return ":".join(parts[:octets])


def _match_mac_prefix(mac: str, signatures: dict) -> dict | None:
    """Look up a MAC address in the signatures mac_prefixes table.

    Tries 3-octet OUI prefix first, then 4-octet if 3 misses.

    Returns:
        Matching signature dict or None.
    """
    mac_prefixes: dict[str, dict] = signatures.get("mac_prefixes", {})

    # 3-octet OUI
    prefix3 = _mac_prefix(mac, 3)
    if prefix3 in mac_prefixes:
        return mac_prefixes[prefix3]

    # 4-octet extended OUI
    prefix4 = _mac_prefix(mac, 4)
    if prefix4 in mac_prefixes:
        return mac_prefixes[prefix4]

    return None


# ---------------------------------------------------------------------------
# Vendor keyword matching
# ---------------------------------------------------------------------------


def _vendor_is_iot(vendor: str | None, signatures: dict) -> bool:
    """Return True if the vendor name contains an IoT-related keyword."""
    if not vendor:
        return False
    vendor_lower = vendor.lower()
    keywords: list[str] = (
        signatures.get("iot_indicators", {}).get("vendor_keywords", [])
    )
    return any(kw in vendor_lower for kw in keywords)


# ---------------------------------------------------------------------------
# Port pattern matching
# ---------------------------------------------------------------------------


def _classify_by_ports(
    open_ports: list[int],
    signatures: dict,
) -> str | None:
    """Match a device type from its open ports using IoT port patterns.

    Args:
        open_ports: List of open port numbers.
        signatures: Full IoT signatures dict.

    Returns:
        Device type string or None if no pattern matches.
    """
    if not open_ports:
        return None

    port_patterns: dict[str, list[int]] = (
        signatures.get("iot_indicators", {}).get("port_patterns", {})
    )
    port_set = set(open_ports)

    best_type: str | None = None
    best_overlap = 0

    for device_type, pattern_ports in port_patterns.items():
        overlap = len(port_set & set(pattern_ports))
        if overlap > best_overlap:
            best_overlap = overlap
            best_type = device_type

    # Require at least 2 ports to match (reduces false positives)
    if best_overlap >= 2:
        return best_type
    return None


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------


def classify_iot_device(
    device: Device,
    scan: HostScanResult | None = None,
    profile: DeviceProfile | None = None,
    *,
    _signatures_fn=None,
) -> IoTDevice | None:
    """Determine whether a device is an IoT device and return its classification.

    Uses three signals (in priority order):
      1. MAC prefix match against known IoT OUI database.
      2. Vendor name keyword match against IoT vendor list.
      3. Open port pattern match against known IoT port patterns.
      4. DeviceProfile device_type / classification_method hints.

    Args:
        device: Device object from discovery (must have .ip, .mac, .vendor).
        scan: Optional HostScanResult providing open ports.
        profile: Optional DeviceProfile from the fingerprint module.
        _signatures_fn: Injectable function () -> dict for testing.

    Returns:
        IoTDevice if classified as IoT, otherwise None.
    """
    signatures = get_iot_signatures(_load_fn=_signatures_fn)

    device_type: str | None = None
    manufacturer: str | None = getattr(device, "vendor", None)
    model: str | None = None

    # 1. MAC prefix match (highest confidence)
    mac_match = _match_mac_prefix(device.mac, signatures)
    if mac_match:
        device_type = mac_match.get("type")
        manufacturer = mac_match.get("manufacturer", manufacturer)
        model = mac_match.get("model")

    # 2. Vendor keyword match
    if device_type is None and _vendor_is_iot(getattr(device, "vendor", None), signatures):
        device_type = "unknown"

    # 3. Port pattern match
    if device_type is None and scan is not None:
        open_ports = [pr.port for pr in scan.ports]
        device_type = _classify_by_ports(open_ports, signatures)

    # 4. DeviceProfile hints
    if device_type is None and profile is not None:
        profile_type = getattr(profile, "device_type", None)
        iot_types = {"camera", "speaker", "thermostat", "plug", "hub", "iot"}
        if profile_type and profile_type.lower() in iot_types:
            device_type = profile_type.lower()
        # Check classification method (mDNS / UPnP with known IoT service)
        if device_type is None and getattr(profile, "manufacturer", None):
            if _vendor_is_iot(profile.manufacturer, signatures):
                device_type = "unknown"

    if device_type is None:
        return None

    return IoTDevice(
        ip=device.ip,
        mac=device.mac,
        device_type=device_type,
        manufacturer=manufacturer,
        model=model,
    )


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


def assess_device_risk(
    iot_device: IoTDevice,
    scan: HostScanResult | None = None,
    *,
    _signatures_fn=None,
) -> IoTDevice:
    """Assess security risk for an IoT device based on its open ports.

    Scoring (cumulative, capped at 100):
      - Critical port (e.g. Telnet, ADB): +30 per port
      - High severity port (e.g. MQTT, FTP): +20 per port
      - Medium severity port (e.g. HTTP): +10 per port
      - HTTP open but HTTPS closed: +15
      - Unknown manufacturer: +10

    Populates iot_device.risky_ports, .issues, .recommendations, .risk_score
    in-place and also returns the modified object.

    Args:
        iot_device: IoTDevice to assess (modified in place).
        scan: HostScanResult with open ports for this device.
        _signatures_fn: Injectable function () -> dict for testing.

    Returns:
        The same IoTDevice with risk fields populated.
    """
    signatures = get_iot_signatures(_load_fn=_signatures_fn)
    risky_port_defs: dict[str, dict] = signatures.get("risky_ports", {})

    score = 0
    risky_ports: list[int] = []
    issues: list[str] = []
    recommendations: list[str] = []

    # Unknown manufacturer penalty
    if not iot_device.manufacturer:
        score += 10
        issues.append("Unknown manufacturer — cannot assess supply-chain risk")
        recommendations.append("Investigate this device and identify its manufacturer")

    open_port_nums: set[int] = set()
    if scan is not None:
        open_port_nums = {pr.port for pr in scan.ports}

    # Score risky open ports
    severity_score = {"critical": 30, "high": 20, "medium": 10, "low": 0}
    has_http = False
    has_https = False

    for port_num in sorted(open_port_nums):
        port_str = str(port_num)
        if port_str in risky_port_defs:
            port_def = risky_port_defs[port_str]
            severity = port_def.get("severity", "low")
            pts = severity_score.get(severity, 0)
            service = port_def.get("service", f"port {port_num}")
            issue_text = port_def.get("issue", f"{service} exposed")

            if pts > 0:
                score += pts
                risky_ports.append(port_num)
                issues.append(f"Port {port_num} ({service}): {issue_text}")

                # Per-port recommendations
                if severity == "critical":
                    recommendations.append(
                        f"Immediately disable {service} (port {port_num}) — "
                        "this poses a critical security risk"
                    )
                elif severity == "high":
                    recommendations.append(
                        f"Disable or restrict {service} (port {port_num}) — "
                        "use an encrypted alternative"
                    )
                elif severity == "medium":
                    recommendations.append(
                        f"Consider disabling {service} (port {port_num}) or "
                        "restrict access via firewall"
                    )

        if port_num == 80:
            has_http = True
        if port_num in (443, 8443):
            has_https = True

    # HTTP without HTTPS
    if has_http and not has_https:
        score += 15
        issues.append("Device exposes HTTP but not HTTPS — management traffic unencrypted")
        recommendations.append(
            "Enable HTTPS on the device management interface and disable plain HTTP"
        )

    # Cap at 100
    iot_device.risk_score = min(score, 100)
    iot_device.risky_ports = risky_ports
    iot_device.issues = issues
    iot_device.recommendations = recommendations

    return iot_device


# ---------------------------------------------------------------------------
# Full network audit
# ---------------------------------------------------------------------------


def audit_network(
    devices: list[Device],
    scans: dict[str, HostScanResult] | None = None,
    profiles: list[DeviceProfile] | None = None,
    *,
    _signatures_fn=None,
    _discover_fn=None,
    _scan_fn=None,
    _fingerprint_fn=None,
) -> IoTAuditReport:
    """Run a full IoT security audit across all provided devices.

    Classifies each device, assesses risk for IoT devices, and generates an
    aggregate report with overall recommendations.

    If scans/profiles are not provided but _scan_fn/_fingerprint_fn are given,
    they will be called to gather live data for each device.

    Args:
        devices: List of Device objects to audit.
        scans: Optional mapping of IP -> HostScanResult.
        profiles: Optional list of DeviceProfile objects.
        _signatures_fn: Injectable IoT signatures loader.
        _discover_fn: Injectable discovery function (unused if devices provided).
        _scan_fn: Injectable scan function (ip: str) -> HostScanResult.
        _fingerprint_fn: Injectable fingerprint function.

    Returns:
        IoTAuditReport with all classified devices and summary statistics.
    """
    from datetime import datetime

    if scans is None:
        scans = {}

    # Build profile lookup by IP
    profiles_by_ip: dict[str, DeviceProfile] = {}
    if profiles:
        for prof in profiles:
            profiles_by_ip[prof.ip] = prof

    iot_devices: list[IoTDevice] = []

    for device in devices:
        scan = scans.get(device.ip)

        # Gather scan data if not provided and _scan_fn is available
        if scan is None and _scan_fn is not None:
            try:
                scan = _scan_fn(device.ip)
            except Exception:
                scan = None

        profile = profiles_by_ip.get(device.ip)

        # Gather fingerprint data if not provided and _fingerprint_fn is available
        if profile is None and _fingerprint_fn is not None:
            try:
                profile = _fingerprint_fn(device)
            except Exception:
                profile = None

        iot_device = classify_iot_device(
            device, scan=scan, profile=profile, _signatures_fn=_signatures_fn
        )
        if iot_device is None:
            continue

        iot_device = assess_device_risk(
            iot_device, scan=scan, _signatures_fn=_signatures_fn
        )
        iot_devices.append(iot_device)

    # Aggregate statistics
    high_risk_count = sum(1 for d in iot_devices if d.risk_score >= 60)
    total_issues = sum(len(d.issues) for d in iot_devices)

    # Overall recommendations
    overall_recs: list[str] = []

    if high_risk_count > 0:
        overall_recs.append(
            f"Address {high_risk_count} high-risk IoT device(s) immediately"
        )
    if iot_devices:
        overall_recs.append(
            "Segment IoT devices onto a dedicated VLAN to limit lateral movement"
        )
        overall_recs.append(
            "Ensure all IoT device firmware is kept up to date"
        )
        critical_ports = {
            ip
            for d in iot_devices
            for p in d.risky_ports
            if str(p) in _get_critical_ports(_signatures_fn)
            for ip in [d.ip]
        }
        if critical_ports:
            overall_recs.append(
                "Block Telnet (23) and ADB (5555) at the network perimeter"
            )

    if not iot_devices:
        overall_recs.append("No IoT devices detected on this network")

    return IoTAuditReport(
        devices=iot_devices,
        high_risk_count=high_risk_count,
        total_issues=total_issues,
        recommendations=overall_recs,
        timestamp=datetime.now(),
    )


def _get_critical_ports(signatures_fn=None) -> set[str]:
    """Return port numbers (as strings) with critical severity."""
    signatures = get_iot_signatures(_load_fn=signatures_fn)
    risky_ports = signatures.get("risky_ports", {})
    return {p for p, info in risky_ports.items() if info.get("severity") == "critical"}
