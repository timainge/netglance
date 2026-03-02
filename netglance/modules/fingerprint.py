"""Device fingerprinting and classification engine.

Implements Layer 1 + Layer 2 fingerprinting via mDNS service browsing,
UPnP/SSDP discovery, hostname pattern matching, and port signature lookup.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

from netglance.store.models import Device, DeviceFingerprint, DeviceProfile


# ---------------------------------------------------------------------------
# Signature loading
# ---------------------------------------------------------------------------

def _load_signatures() -> dict:
    """Load device signatures from the bundled JSON data file."""
    data_path = files("netglance.data").joinpath("device_signatures.json")
    return json.loads(data_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# MAC address utilities
# ---------------------------------------------------------------------------

def detect_randomized_mac(mac: str) -> bool:
    """Check the locally-administered bit (second-least-significant bit of first octet).

    Returns True if the MAC is randomized (locally administered).
    A MAC is locally administered when bit 1 (0x02) of the first octet is set.
    """
    try:
        first_octet = int(mac.replace(":", "").replace("-", "")[:2], 16)
        return bool(first_octet & 0x02)
    except (ValueError, IndexError):
        return False


# ---------------------------------------------------------------------------
# mDNS fingerprinting
# ---------------------------------------------------------------------------

MDNS_SERVICE_TYPES = [
    "_airplay._tcp",
    "_raop._tcp",
    "_ipp._tcp",
    "_printer._tcp",
    "_scanner._tcp",
    "_smb._tcp",
    "_afpovertcp._tcp",
    "_sftp-ssh._tcp",
    "_googlecast._tcp",
    "_spotify-connect._tcp",
    "_homekit._tcp",
    "_hap._tcp",
    "_companion-link._tcp",
    "_sleep-proxy._udp",
    "_workstation._tcp",
    "_http._tcp",
    "_device-info._tcp",
]


def fingerprint_mdns(
    ip: str,
    timeout: float = 5.0,
    *,
    _browse_fn=None,
) -> dict:
    """Browse 15+ mDNS service types for a target IP.

    Args:
        ip: Target device IP address.
        timeout: Seconds to wait for responses per service type.
        _browse_fn: Injectable function(service_type, timeout) -> list of dicts
                    with service info including "ip", "txt_records" keys.

    Returns:
        {"services": [...found service types...], "txt_records": {svc: {k: v}}}
    """
    if _browse_fn is None:
        _browse_fn = _default_mdns_browse

    found_services: list[str] = []
    txt_records: dict[str, dict[str, str]] = {}

    for svc_type in MDNS_SERVICE_TYPES:
        try:
            results = _browse_fn(svc_type, timeout)
            for result in results:
                result_ip = result.get("ip", "")
                if result_ip == ip:
                    found_services.append(svc_type)
                    if "txt_records" in result and result["txt_records"]:
                        txt_records[svc_type] = result["txt_records"]
                    break
        except Exception:
            continue

    return {"services": found_services, "txt_records": txt_records}


def _default_mdns_browse(service_type: str, timeout: float) -> list[dict]:
    """Default mDNS browse implementation using zeroconf."""
    import socket
    import time

    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf  # type: ignore[import-untyped]
    except ImportError:
        return []

    results: list[dict] = []

    def _on_state_change(
        zc: "Zeroconf",
        svc_type: str,
        name: str,
        state_change: "ServiceStateChange",
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zc.get_service_info(svc_type, name)
        if info is None:
            return
        for addr_bytes in info.addresses:
            ip = socket.inet_ntoa(addr_bytes)
            txt: dict[str, str] = {}
            if info.properties:
                for k, v in info.properties.items():
                    key = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k)
                    val = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v) if v is not None else ""
                    txt[key] = val
            results.append({"ip": ip, "txt_records": txt})

    local_type = service_type + ".local." if not service_type.endswith(".") else service_type
    zc = Zeroconf()
    try:
        ServiceBrowser(zc, local_type, handlers=[_on_state_change])
        time.sleep(timeout)
    finally:
        zc.close()

    return results


# ---------------------------------------------------------------------------
# UPnP fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_upnp(
    ip: str,
    timeout: float = 5.0,
    *,
    _http_fn=None,
    _ssdp_fn=None,
) -> dict:
    """SSDP M-SEARCH + fetch XML device description.

    Args:
        ip: Target device IP address.
        timeout: Seconds to wait for SSDP responses.
        _ssdp_fn: Injectable function() -> list of {"location": url, "ip": ip}
        _http_fn: Injectable function(url) -> str (XML content)

    Returns:
        {"friendly_name": ..., "manufacturer": ..., "model_name": ...,
         "model_number": ..., "device_type": ...}
    """
    ssdp_fn = _ssdp_fn or _default_ssdp_search
    http_fn = _http_fn or _default_http_fetch

    result: dict[str, Any] = {
        "friendly_name": None,
        "manufacturer": None,
        "model_name": None,
        "model_number": None,
        "device_type": None,
    }

    try:
        devices = ssdp_fn()
    except Exception:
        return result

    location_url = None
    for device in devices:
        if device.get("ip") == ip:
            location_url = device.get("location")
            break

    if not location_url:
        return result

    try:
        xml_content = http_fn(location_url)
        result.update(_parse_upnp_xml(xml_content))
    except Exception:
        pass

    return result


def _parse_upnp_xml(xml_content: str) -> dict:
    """Extract device info from UPnP device description XML."""
    import xml.etree.ElementTree as ET

    result: dict[str, Any] = {}
    try:
        root = ET.fromstring(xml_content)
        # Handle namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        device = root.find(f"{ns}device")
        if device is None:
            # Try searching the whole tree
            for elem in root.iter():
                if elem.tag.endswith("device"):
                    device = elem
                    break

        if device is not None:
            def _find_text(tag: str) -> str | None:
                elem = device.find(f"{ns}{tag}")  # type: ignore[union-attr]
                if elem is None:
                    # Try without namespace
                    elem = device.find(tag)  # type: ignore[union-attr]
                return elem.text if elem is not None else None

            result["friendly_name"] = _find_text("friendlyName")
            result["manufacturer"] = _find_text("manufacturer")
            result["model_name"] = _find_text("modelName")
            result["model_number"] = _find_text("modelNumber")
            result["device_type"] = _find_text("deviceType")
    except ET.ParseError:
        pass

    return result


def _default_ssdp_search() -> list[dict]:
    """Send SSDP M-SEARCH and collect responses."""
    import socket
    import time

    SSDP_ADDR = "239.255.255.250"
    SSDP_PORT = 1900
    SSDP_MX = 3
    SSDP_ST = "ssdp:all"

    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        f"MAN: \"ssdp:discover\"\r\n"
        f"MX: {SSDP_MX}\r\n"
        f"ST: {SSDP_ST}\r\n"
        "\r\n"
    )

    results: list[dict] = []
    seen_locations: set[str] = set()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(SSDP_MX + 1)
        sock.sendto(msg.encode(), (SSDP_ADDR, SSDP_PORT))

        end_time = time.monotonic() + SSDP_MX + 1
        while time.monotonic() < end_time:
            try:
                data, addr = sock.recvfrom(65507)
                response = data.decode("utf-8", errors="replace")
                location = None
                for line in response.splitlines():
                    if line.lower().startswith("location:"):
                        location = line.split(":", 1)[1].strip()
                        break
                if location and location not in seen_locations:
                    seen_locations.add(location)
                    results.append({"location": location, "ip": addr[0]})
            except socket.timeout:
                break
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass

    return results


def _default_http_fetch(url: str) -> str:
    """Fetch URL content as string."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Hostname classification
# ---------------------------------------------------------------------------

_HOSTNAME_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"^iPhone"), "smartphone", 0.9),
    (re.compile(r"^iPad"), "tablet", 0.9),
    (re.compile(r"^Galaxy|^SM-"), "smartphone", 0.85),
    (re.compile(r"^DESKTOP-"), "desktop", 0.8),
    (re.compile(r"^MacBook"), "laptop", 0.85),
    (re.compile(r"(?i)^NPI[A-F0-9]"), "printer", 0.8),
    (re.compile(r"^ESP_"), "iot", 0.7),
    (re.compile(r"(?i)^raspberrypi"), "server", 0.7),
]


def classify_by_hostname(hostname: str) -> tuple[str | None, float]:
    """Regex-based device type guess from hostname.

    Args:
        hostname: Device hostname string.

    Returns:
        (device_type | None, confidence) tuple.
    """
    for pattern, device_type, confidence in _HOSTNAME_PATTERNS:
        if pattern.search(hostname):
            return device_type, confidence
    return None, 0.0


# ---------------------------------------------------------------------------
# Port-based classification
# ---------------------------------------------------------------------------

def classify_by_ports(
    open_ports: list[int],
    *,
    _signatures_fn=None,
) -> tuple[str | None, float]:
    """Port signature lookup from device_signatures.json.

    Args:
        open_ports: List of open port numbers.
        _signatures_fn: Injectable fn() -> dict (the signatures data).

    Returns:
        (device_type | None, confidence) tuple with the highest confidence match.
    """
    signatures_fn = _signatures_fn or _load_signatures
    signatures = signatures_fn()
    port_sigs = signatures.get("port_signatures", {})

    if not open_ports:
        return None, 0.0

    port_set = set(open_ports)
    best_type: str | None = None
    best_conf = 0.0

    for key, sig in port_sigs.items():
        # Key can be a single port or comma-separated ports
        required_ports = {int(p.strip()) for p in key.split(",")}
        if required_ports.issubset(port_set):
            conf = sig.get("confidence", 0.0)
            if conf > best_conf:
                best_conf = conf
                best_type = sig.get("type")

    return best_type, best_conf


# ---------------------------------------------------------------------------
# Full device fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_device(
    ip: str,
    mac: str,
    hostname: str | None = None,
    open_ports: list[int] | None = None,
    *,
    _browse_fn=None,
    _http_fn=None,
    _ssdp_fn=None,
) -> DeviceFingerprint:
    """Collect all fingerprint signals for a device.

    Args:
        ip: Device IP address.
        mac: Device MAC address.
        hostname: Optional hostname.
        open_ports: Optional list of known open ports.
        _browse_fn: Injectable mDNS browse function.
        _http_fn: Injectable HTTP fetch function.
        _ssdp_fn: Injectable SSDP search function.

    Returns:
        DeviceFingerprint with all collected signals.
    """
    is_randomized = detect_randomized_mac(mac)

    mdns_data = fingerprint_mdns(ip, _browse_fn=_browse_fn)
    upnp_data = fingerprint_upnp(ip, _http_fn=_http_fn, _ssdp_fn=_ssdp_fn)

    return DeviceFingerprint(
        mac=mac,
        mac_is_randomized=is_randomized,
        oui_vendor=None,  # caller can populate from ARP/discover data
        hostname=hostname,
        mdns_services=mdns_data["services"],
        mdns_txt_records=mdns_data["txt_records"],
        upnp_friendly_name=upnp_data.get("friendly_name"),
        upnp_manufacturer=upnp_data.get("manufacturer"),
        upnp_model_name=upnp_data.get("model_name"),
        upnp_model_number=upnp_data.get("model_number"),
        upnp_device_type=upnp_data.get("device_type"),
        open_ports=list(open_ports) if open_ports else [],
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_device(fingerprint: DeviceFingerprint) -> DeviceProfile:
    """Apply classification rules to fingerprint signals.

    Priority: upnp > mdns > ports > hostname > mac vendor.

    Args:
        fingerprint: DeviceFingerprint with collected signals.

    Returns:
        DeviceProfile with the highest confidence match.
    """
    from datetime import datetime

    signatures = _load_signatures()
    mdns_sigs = signatures.get("mdns_signatures", {})

    best_type: str | None = None
    best_conf = 0.0
    best_method = ""
    manufacturer: str | None = None
    model: str | None = None
    friendly_name: str | None = None

    # 1. UPnP (highest priority — if present, only mDNS at higher confidence can override)
    if fingerprint.upnp_friendly_name or fingerprint.upnp_manufacturer:
        # UPnP gives us rich info — use device_type from UPnP if present
        upnp_type_raw = fingerprint.upnp_device_type or ""
        upnp_type = _parse_upnp_device_type(upnp_type_raw)
        best_type = upnp_type
        best_conf = 0.95  # use high sentinel so lower-priority signals don't override
        best_method = "upnp"
        manufacturer = fingerprint.upnp_manufacturer
        model = fingerprint.upnp_model_name
        friendly_name = fingerprint.upnp_friendly_name

    # 2. mDNS — only check if UPnP didn't already match
    if not best_method and fingerprint.mdns_services:
        for svc in fingerprint.mdns_services:
            sig = mdns_sigs.get(svc)
            if sig:
                conf = sig.get("confidence", 0.0)
                if conf > best_conf:
                    best_conf = conf
                    best_type = sig.get("type")
                    best_method = "mdns"

    # 3. Port signatures — only check if no higher-priority signal matched
    if not best_method and fingerprint.open_ports:
        port_type, port_conf = classify_by_ports(fingerprint.open_ports)
        if port_conf > best_conf:
            best_conf = port_conf
            best_type = port_type
            best_method = "ports"

    # 4. Hostname — only check if no higher-priority signal matched
    if not best_method and fingerprint.hostname:
        host_type, host_conf = classify_by_hostname(fingerprint.hostname)
        if host_conf > best_conf:
            best_conf = host_conf
            best_type = host_type
            best_method = "hostname"

    # 5. MAC vendor (lowest priority / fallback)
    if not best_method and fingerprint.oui_vendor:
        best_type = None  # vendor doesn't tell us device type directly
        best_method = "mac_vendor"

    # Infer IP from fingerprint (not stored, caller must supply it)
    # We'll use an empty string as placeholder — fingerprint_all will set it
    return DeviceProfile(
        ip="",
        mac=fingerprint.mac,
        device_type=best_type,
        manufacturer=manufacturer or fingerprint.upnp_manufacturer or fingerprint.oui_vendor,
        model=model,
        friendly_name=friendly_name or fingerprint.upnp_friendly_name or fingerprint.hostname,
        confidence=best_conf,
        classification_method=best_method,
        fingerprint=fingerprint,
        last_profiled=datetime.now(),
    )


def _parse_upnp_device_type(raw_type: str) -> str | None:
    """Extract a simple device type category from a UPnP device type URN."""
    if not raw_type:
        return None
    # e.g. "urn:schemas-upnp-org:device:MediaRenderer:1" -> "media-renderer"
    # "urn:schemas-upnp-org:device:BasicDevice:1" -> "basic-device"
    lower = raw_type.lower()
    if "mediarenderer" in lower or "media-renderer" in lower:
        return "media"
    if "mediaserver" in lower or "media-server" in lower:
        return "media-server"
    if "printer" in lower:
        return "printer"
    if "gateway" in lower or "router" in lower:
        return "router"
    if "switch" in lower:
        return "switch"
    if "light" in lower or "lamp" in lower:
        return "iot"
    if "camera" in lower:
        return "camera"
    # Extract the device type segment from URN
    parts = raw_type.split(":")
    for i, part in enumerate(parts):
        if part.lower() == "device" and i + 1 < len(parts):
            raw = parts[i + 1]
            # Convert CamelCase to kebab-case
            result = re.sub(r"([a-z])([A-Z])", r"\1-\2", raw).lower()
            return result
    return None


# ---------------------------------------------------------------------------
# Batch fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_all(
    devices: list,
    *,
    _browse_fn=None,
    _http_fn=None,
    _ssdp_fn=None,
) -> list[DeviceProfile]:
    """Fingerprint and classify a list of Device objects.

    Args:
        devices: List of Device objects (or any objects with ip, mac, hostname attrs).
        _browse_fn: Injectable mDNS browse function.
        _http_fn: Injectable HTTP fetch function.
        _ssdp_fn: Injectable SSDP search function.

    Returns:
        List of DeviceProfile, one per device.
    """
    profiles: list[DeviceProfile] = []
    for device in devices:
        ip = getattr(device, "ip", "")
        mac = getattr(device, "mac", "")
        hostname = getattr(device, "hostname", None)
        vendor = getattr(device, "vendor", None)

        fp = fingerprint_device(
            ip=ip,
            mac=mac,
            hostname=hostname,
            _browse_fn=_browse_fn,
            _http_fn=_http_fn,
            _ssdp_fn=_ssdp_fn,
        )
        fp.oui_vendor = vendor

        profile = classify_device(fp)
        profile.ip = ip
        if not profile.manufacturer and vendor:
            profile.manufacturer = vendor

        profiles.append(profile)
    return profiles


# ---------------------------------------------------------------------------
# Device labeling
# ---------------------------------------------------------------------------

def label_device(mac: str, label: str, device_type: str | None = None) -> dict:
    """Create a labeling record.

    Args:
        mac: Device MAC address.
        label: User-assigned label/name for the device.
        device_type: Optional device type override.

    Returns:
        {"mac": ..., "label": ..., "device_type": ...}
    """
    return {
        "mac": mac,
        "label": label,
        "device_type": device_type,
    }
