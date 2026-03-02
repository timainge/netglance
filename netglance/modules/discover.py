"""Device discovery module: ARP scanning, mDNS browsing, and vendor lookup."""

from __future__ import annotations

import socket
from dataclasses import asdict
from datetime import datetime
from typing import Any

from netglance.store.models import Device


# ---------------------------------------------------------------------------
# Thin wrappers around network I/O -- easy to mock in tests
# ---------------------------------------------------------------------------

def _scapy_arping(subnet: str, interface: str | None, timeout: float) -> list[tuple[str, str]]:
    """Send ARP requests via scapy and return (ip, mac) pairs."""
    from scapy.all import ARP, Ether, srp  # type: ignore[import-untyped]

    pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet)
    kwargs: dict[str, Any] = {"timeout": timeout, "verbose": 0}
    if interface:
        kwargs["iface"] = interface
    answered, _ = srp(pkt, **kwargs)
    results: list[tuple[str, str]] = []
    for _, rcv in answered:
        results.append((rcv.psrc, rcv.hwsrc))
    return results


def _resolve_hostname(ip: str) -> str | None:
    """Reverse-DNS lookup for an IP address."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        return None


def _lookup_vendor(mac: str) -> str | None:
    """Resolve MAC address to vendor name via OUI database."""
    from mac_vendor_lookup import MacLookup  # type: ignore[import-untyped]

    try:
        return MacLookup().lookup(mac)
    except Exception:
        return None


def _mdns_browse(timeout: float) -> list[tuple[str, str, str | None]]:
    """Browse for mDNS services.  Returns list of (ip, mac, hostname)."""
    import time

    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf  # type: ignore[import-untyped]

    results: list[tuple[str, str, str | None]] = []
    seen_ips: set[str] = set()

    def _on_state_change(
        zc: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zc.get_service_info(service_type, name)
        if info is None:
            return
        for addr_bytes in info.addresses:
            ip = socket.inet_ntoa(addr_bytes)
            if ip in seen_ips:
                continue
            seen_ips.add(ip)
            hostname = info.server.rstrip(".") if info.server else None
            # mDNS does not inherently provide MAC; use empty placeholder
            results.append((ip, "", hostname))

    zc = Zeroconf()
    services = ["_http._tcp.local.", "_workstation._tcp.local."]
    browsers = [ServiceBrowser(zc, svc, handlers=[_on_state_change]) for svc in services]
    time.sleep(timeout)
    zc.close()
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def arp_scan(
    subnet: str,
    interface: str | None = None,
    timeout: float = 3.0,
    *,
    _arping_fn: Any = None,
    _hostname_fn: Any = None,
    _vendor_fn: Any = None,
) -> list[Device]:
    """Discover devices on *subnet* via ARP requests.

    Dependency-injection parameters ``_arping_fn``, ``_hostname_fn``, and
    ``_vendor_fn`` exist for testability.  When ``None`` (the default),
    the module-level wrappers are resolved at call time so that
    ``unittest.mock.patch`` works transparently.
    """
    if _arping_fn is None:
        _arping_fn = _scapy_arping
    if _hostname_fn is None:
        _hostname_fn = _resolve_hostname
    if _vendor_fn is None:
        _vendor_fn = _lookup_vendor
    pairs = _arping_fn(subnet, interface, timeout)
    now = datetime.now()
    devices: list[Device] = []
    for ip, mac in pairs:
        mac = mac.lower()
        devices.append(
            Device(
                ip=ip,
                mac=mac,
                hostname=_hostname_fn(ip),
                vendor=_vendor_fn(mac),
                discovery_method="arp",
                first_seen=now,
                last_seen=now,
            )
        )
    return devices


def mdns_scan(
    timeout: float = 5.0,
    *,
    _mdns_fn: Any = None,
    _vendor_fn: Any = None,
) -> list[Device]:
    """Discover devices via mDNS/Bonjour service browsing.

    Dependency-injection parameters exist for testability.  When ``None``,
    the module-level wrappers are resolved at call time.
    """
    if _mdns_fn is None:
        _mdns_fn = _mdns_browse
    if _vendor_fn is None:
        _vendor_fn = _lookup_vendor
    entries = _mdns_fn(timeout)
    now = datetime.now()
    devices: list[Device] = []
    for ip, mac, hostname in entries:
        mac = mac.lower() if mac else ""
        devices.append(
            Device(
                ip=ip,
                mac=mac,
                hostname=hostname,
                vendor=_vendor_fn(mac) if mac else None,
                discovery_method="mdns",
                first_seen=now,
                last_seen=now,
            )
        )
    return devices


def discover_all(
    subnet: str,
    interface: str | None = None,
    *,
    _arping_fn: Any = None,
    _hostname_fn: Any = None,
    _vendor_fn: Any = None,
    _mdns_fn: Any = None,
) -> list[Device]:
    """Run both ARP and mDNS discovery, merging results by MAC address.

    When a device is found by both methods, ARP data (which always has a MAC)
    takes precedence; the hostname from mDNS is kept if the ARP result lacked
    one.
    """
    arp_devices = arp_scan(
        subnet,
        interface,
        _arping_fn=_arping_fn,
        _hostname_fn=_hostname_fn,
        _vendor_fn=_vendor_fn,
    )
    mdns_devices = mdns_scan(
        _mdns_fn=_mdns_fn,
        _vendor_fn=_vendor_fn,
    )

    # Index ARP results by MAC for merging
    by_mac: dict[str, Device] = {}
    for dev in arp_devices:
        by_mac[dev.mac] = dev

    # Index mDNS results by IP (mDNS may not have MAC)
    by_ip: dict[str, Device] = {dev.ip: dev for dev in mdns_devices}

    # Merge mDNS info into ARP entries
    for mac, dev in by_mac.items():
        mdns_match = by_ip.pop(dev.ip, None)
        if mdns_match:
            if not dev.hostname and mdns_match.hostname:
                dev.hostname = mdns_match.hostname
            dev.discovery_method = "arp+mdns"

    # Add mDNS-only entries (those not matched to any ARP result)
    merged = list(by_mac.values())
    for dev in by_ip.values():
        merged.append(dev)

    return merged


def diff_devices(
    current: list[Device], baseline: list[Device]
) -> dict[str, list[Device]]:
    """Compare *current* devices against a *baseline* snapshot.

    Returns a dict with keys ``new``, ``missing``, and ``changed``.
    A device is identified by its MAC address.  ``changed`` means the
    same MAC now has a different IP or hostname.
    """
    current_by_mac = {d.mac: d for d in current if d.mac}
    baseline_by_mac = {d.mac: d for d in baseline if d.mac}

    current_macs = set(current_by_mac)
    baseline_macs = set(baseline_by_mac)

    new = [current_by_mac[m] for m in current_macs - baseline_macs]
    missing = [baseline_by_mac[m] for m in baseline_macs - current_macs]

    changed: list[Device] = []
    for m in current_macs & baseline_macs:
        cur = current_by_mac[m]
        base = baseline_by_mac[m]
        if cur.ip != base.ip or cur.hostname != base.hostname:
            changed.append(cur)

    return {"new": new, "missing": missing, "changed": changed}


# ---------------------------------------------------------------------------
# Serialisation helpers (for store / JSON output)
# ---------------------------------------------------------------------------

def devices_to_dicts(devices: list[Device]) -> list[dict[str, Any]]:
    """Convert a list of devices to serialisable dicts."""
    out: list[dict[str, Any]] = []
    for d in devices:
        row = asdict(d)
        row["first_seen"] = d.first_seen.isoformat()
        row["last_seen"] = d.last_seen.isoformat()
        out.append(row)
    return out


def dicts_to_devices(rows: list[dict[str, Any]]) -> list[Device]:
    """Reconstruct Device objects from serialised dicts."""
    devices: list[Device] = []
    for row in rows:
        row = dict(row)  # shallow copy
        row["first_seen"] = datetime.fromisoformat(row["first_seen"])
        row["last_seen"] = datetime.fromisoformat(row["last_seen"])
        devices.append(Device(**row))
    return devices
