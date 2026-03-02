"""IPv6 network audit: NDP neighbor discovery, privacy extensions, DNS leak detection."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

import psutil

from netglance.store.models import IPv6AuditResult, IPv6Neighbor


def classify_ipv6_address(address: str) -> str:
    """Classify an IPv6 address by type.

    Returns one of:
    - 'loopback'      if ::1
    - 'link-local'    if fe80::/10
    - 'multicast'     if ff00::/8
    - 'unique-local'  if fc00::/7
    - 'eui64'         if global unicast with ff:fe in interface ID (EUI-64 derived)
    - 'temporary'     if global unicast without EUI-64 pattern
    - 'global'        for other global unicast (2000::/3) addresses
    - 'unknown'       otherwise
    """
    try:
        addr = ipaddress.IPv6Address(address)
    except ValueError:
        return "unknown"

    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link-local"
    if addr.is_multicast:
        return "multicast"

    # fc00::/7 — unique local
    packed = addr.packed
    if (packed[0] & 0xFE) == 0xFC:
        return "unique-local"

    # Global unicast (2000::/3)
    if (packed[0] & 0xE0) == 0x20:
        # EUI-64: bytes 11-12 of the 128-bit address are 0xFF 0xFE
        if packed[11] == 0xFF and packed[12] == 0xFE:
            return "eui64"
        return "temporary"

    return "global"


def _default_send_fn(interface: str | None, timeout: float) -> list[tuple[str, str]]:
    """Send ICMPv6 Neighbor Solicitation to ff02::1 and collect advertisements."""
    try:
        from scapy.layers.inet6 import (
            ICMPv6ND_NA,
            ICMPv6ND_NS,
            IPv6,
        )
        from scapy.sendrecv import srp1, srp

        iface = interface  # may be None → scapy picks default
        dst = "ff02::1"

        pkts, _ = srp(
            IPv6(dst=dst) / ICMPv6ND_NS(tgt=dst),
            iface=iface,
            timeout=timeout,
            verbose=False,
        )

        results: list[tuple[str, str]] = []
        for _, pkt in pkts:
            if pkt.haslayer(ICMPv6ND_NA):
                src_ip = pkt[IPv6].src
                # MAC is in Ethernet layer
                src_mac = pkt.src if hasattr(pkt, "src") else ""
                results.append((src_ip, src_mac))
        return results
    except Exception:
        return []


def discover_ipv6_neighbors(
    interface: str | None = None,
    timeout: float = 5.0,
    *,
    _send_fn=None,
) -> list[IPv6Neighbor]:
    """Discover IPv6 neighbors via NDP (ICMPv6 Neighbor Solicitation).

    Args:
        interface: Network interface to use. None uses the default.
        timeout: Seconds to wait for responses.
        _send_fn: Injectable function(interface, timeout) -> list[(ipv6, mac)].
                  Defaults to scapy-based NDP discovery (requires root).

    Returns:
        List of IPv6Neighbor objects discovered on the link.
    """
    send_fn = _send_fn if _send_fn is not None else _default_send_fn
    raw = send_fn(interface, timeout)

    neighbors: list[IPv6Neighbor] = []
    for ipv6_address, mac in raw:
        addr_type = classify_ipv6_address(ipv6_address)
        neighbors.append(
            IPv6Neighbor(
                ipv6_address=ipv6_address,
                mac=mac,
                address_type=addr_type,
                interface=interface or "",
            )
        )
    return neighbors


def _default_interfaces_fn() -> dict[str, list[dict[str, Any]]]:
    """Return psutil interface addresses as {iface: [address_dicts]}."""
    result: dict[str, list[dict[str, Any]]] = {}
    for iface, addrs in psutil.net_if_addrs().items():
        iface_list: list[dict[str, Any]] = []
        for addr in addrs:
            iface_list.append(
                {
                    "family": addr.family,
                    "address": addr.address,
                    "netmask": addr.netmask,
                }
            )
        result[iface] = iface_list
    return result


def check_privacy_extensions(
    *,
    _interfaces_fn=None,
) -> tuple[bool, bool]:
    """Detect IPv6 privacy extensions (RFC 4941) and EUI-64 address exposure.

    Args:
        _interfaces_fn: Injectable function() -> {iface: [addr_dicts]}.
                        Defaults to psutil.net_if_addrs().

    Returns:
        (has_privacy_extensions, has_eui64_exposure)
        has_privacy_extensions: True if any temporary global address exists.
        has_eui64_exposure: True if any EUI-64 global address exists.
    """
    import socket

    interfaces_fn = _interfaces_fn if _interfaces_fn is not None else _default_interfaces_fn
    ifaces = interfaces_fn()

    has_privacy = False
    has_eui64 = False

    for _iface, addrs in ifaces.items():
        for addr_info in addrs:
            family = addr_info.get("family")
            address = addr_info.get("address", "")

            # AF_INET6 = 10 on Linux, 30 on macOS; use socket.AF_INET6
            if family != socket.AF_INET6:
                continue

            # Strip interface suffix (e.g. fe80::1%en0)
            clean_addr = address.split("%")[0]

            addr_type = classify_ipv6_address(clean_addr)
            if addr_type == "temporary":
                has_privacy = True
            elif addr_type == "eui64":
                has_eui64 = True

    return has_privacy, has_eui64


def _default_resolve_fn(hostname: str, rdtype: str) -> list[str]:
    """Resolve hostname using dnspython."""
    import dns.resolver

    try:
        answers = dns.resolver.resolve(hostname, rdtype)
        return [str(r) for r in answers]
    except Exception:
        return []


def _detect_vpn_interface() -> bool:
    """Return True if any VPN-like interface is active."""
    vpn_prefixes = ("tun", "tap", "utun", "wg", "ppp", "vpn")
    for iface in psutil.net_if_addrs():
        lower = iface.lower()
        if any(lower.startswith(p) for p in vpn_prefixes):
            return True
    return False


def check_ipv6_dns_leak(
    *,
    _resolve_fn=None,
    _vpn_detect_fn=None,
) -> bool | None:
    """Check if IPv6 DNS queries could bypass VPN tunnel.

    Queries a known dual-stack hostname. If a VPN is detected and IPv6
    AAAA records resolve to public addresses, a potential DNS leak exists.

    Args:
        _resolve_fn: Injectable function(hostname, rdtype) -> list[str].
        _vpn_detect_fn: Injectable function() -> bool (True if VPN active).

    Returns:
        None  — no VPN detected, check not applicable.
        True  — VPN present and IPv6 DNS leak detected.
        False — VPN present but no IPv6 leak detected.
    """
    vpn_detect = _vpn_detect_fn if _vpn_detect_fn is not None else _detect_vpn_interface
    resolve_fn = _resolve_fn if _resolve_fn is not None else _default_resolve_fn

    if not vpn_detect():
        return None

    # Try resolving a well-known dual-stack hostname
    test_hosts = ["ipv6.google.com", "cloudflare.com"]
    for host in test_hosts:
        answers = resolve_fn(host, "AAAA")
        for answer in answers:
            try:
                addr = ipaddress.IPv6Address(answer)
                # If we get a global unicast back, IPv6 DNS is reachable outside VPN
                if addr.is_global:
                    return True
            except ValueError:
                continue

    return False


def run_ipv6_audit(
    interface: str | None = None,
    *,
    _send_fn=None,
    _interfaces_fn=None,
    _resolve_fn=None,
    _vpn_detect_fn=None,
) -> IPv6AuditResult:
    """Full IPv6 network audit.

    Discovers NDP neighbors, inspects local addresses for privacy extension
    status, and checks for IPv6 DNS leaks when a VPN is present.

    Args:
        interface: Interface to use for NDP discovery.
        _send_fn: Injectable NDP send function.
        _interfaces_fn: Injectable interface listing function.
        _resolve_fn: Injectable DNS resolution function.
        _vpn_detect_fn: Injectable VPN detection function.

    Returns:
        IPv6AuditResult with all findings.
    """
    import socket

    # Discover neighbors
    neighbors = discover_ipv6_neighbors(interface=interface, _send_fn=_send_fn)

    # Gather local IPv6 addresses
    interfaces_fn = _interfaces_fn if _interfaces_fn is not None else _default_interfaces_fn
    ifaces = interfaces_fn()

    local_addresses: list[dict] = []
    has_global_ipv4 = False
    has_global_ipv6 = False

    for iface, addrs in ifaces.items():
        for addr_info in addrs:
            family = addr_info.get("family")
            address = addr_info.get("address", "")

            if family == socket.AF_INET6:
                clean_addr = address.split("%")[0]
                addr_type = classify_ipv6_address(clean_addr)
                local_addresses.append(
                    {
                        "interface": iface,
                        "address": clean_addr,
                        "type": addr_type,
                    }
                )
                try:
                    a = ipaddress.IPv6Address(clean_addr)
                    if a.is_global:
                        has_global_ipv6 = True
                except ValueError:
                    pass

            elif family == socket.AF_INET:
                try:
                    a = ipaddress.IPv4Address(address)
                    if a.is_global:
                        has_global_ipv4 = True
                except ValueError:
                    pass

    privacy_ext, eui64_exposed = check_privacy_extensions(_interfaces_fn=_interfaces_fn)
    dns_leak = check_ipv6_dns_leak(
        _resolve_fn=_resolve_fn,
        _vpn_detect_fn=_vpn_detect_fn,
    )
    dual_stack = has_global_ipv4 and has_global_ipv6

    return IPv6AuditResult(
        neighbors=neighbors,
        local_addresses=local_addresses,
        privacy_extensions=privacy_ext,
        eui64_exposed=eui64_exposed,
        dual_stack=dual_stack,
        ipv6_dns_leak=dns_leak,
    )
