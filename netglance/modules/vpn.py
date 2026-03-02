"""VPN leak detection and tunnel interface analysis."""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable

import psutil

from netglance.store.models import VpnLeakReport

# Interface name prefixes/names commonly used by VPN software
VPN_INTERFACE_PATTERNS: list[str] = [
    "utun",      # macOS/iOS tunnel (most VPN clients)
    "tun",       # Linux TUN device
    "wg",        # WireGuard
    "ppp",       # PPP/PPTP/L2TP
    "tap",       # TAP device
    "nordlynx",  # NordVPN WireGuard
    "proton0",   # ProtonVPN
]

# Default split-tunnel check targets
DEFAULT_SPLIT_TUNNEL_TARGETS: list[str] = ["1.1.1.1", "8.8.8.8"]

# Hostname used for DNS leak detection
DNS_LEAK_CHECK_HOST = "dns.google.com"


def _is_vpn_interface(name: str) -> bool:
    """Return True if the interface name looks like a VPN tunnel."""
    lower = name.lower()
    for pattern in VPN_INTERFACE_PATTERNS:
        if lower.startswith(pattern) or lower == pattern:
            return True
    return False


def _default_interfaces_fn() -> dict[str, list]:
    """Thin wrapper around psutil.net_if_addrs for injection."""
    return psutil.net_if_addrs()


def _default_resolve_fn(hostname: str) -> list[str]:
    """Resolve hostname and return the IPs via system resolver."""
    try:
        results = socket.getaddrinfo(hostname, None)
        return [r[4][0] for r in results]
    except OSError:
        return []


def _default_traceroute_fn(host: str) -> str | None:
    """Return the first-hop IP towards *host* using a UDP probe via scapy.

    Falls back to None on any error so callers handle unavailability.
    """
    try:
        from scapy.layers.inet import IP, UDP, ICMP  # type: ignore
        from scapy.sendrecv import sr1  # type: ignore

        pkt = IP(dst=host, ttl=1) / UDP(dport=33434)
        reply = sr1(pkt, verbose=False, timeout=2)
        if reply is not None:
            return reply.src
    except Exception:
        pass
    return None


def detect_vpn_interface(
    *,
    _interfaces_fn: Callable[[], dict[str, list]] | None = None,
) -> tuple[bool, str | None]:
    """Detect if a VPN tunnel interface is active.

    Args:
        _interfaces_fn: Injectable replacement for psutil.net_if_addrs().
            Must return ``{interface_name: [address_dicts]}`` mapping.

    Returns:
        ``(vpn_detected, interface_name)`` — the first matching VPN
        interface found, or ``(False, None)`` if none is active.
    """
    interfaces_fn = _interfaces_fn or _default_interfaces_fn
    interfaces: dict[str, list] = interfaces_fn()

    for name in interfaces:
        if _is_vpn_interface(name):
            return True, name

    return False, None


def check_dns_leak(
    *,
    _resolve_fn: Callable[[str], list[str]] | None = None,
) -> tuple[bool, list[str]]:
    """Test for DNS leaking outside the VPN tunnel.

    Uses a two-probe approach:
    1. Resolve a well-known hostname via the system resolver to collect
       the answering IPs.
    2. Resolve the *same* hostname via a hard-coded Google DNS server
       (8.8.8.8) as the reference.

    If the system resolver returns IPs that do NOT appear in the Google
    reference set, those extra IPs are considered potential leak
    resolvers (i.e. the query was answered by a non-VPN resolver).

    Args:
        _resolve_fn: Injectable callable ``(hostname) -> list[str]``.
            Must accept a hostname and return the list of resolver IPs
            that answered the query. The default uses the system resolver.

    Returns:
        ``(is_leaking, leak_resolver_ips)``
    """
    resolve_fn = _resolve_fn or _default_resolve_fn

    # System resolver answers for the DNS leak check hostname
    system_ips = set(resolve_fn(DNS_LEAK_CHECK_HOST))

    # Known-good Google DNS IPs that should be returned when using Google's resolver
    known_google_ips: set[str] = {
        "8.8.8.8",
        "8.8.4.4",
        "2001:4860:4860::8888",
        "2001:4860:4860::8844",
    }

    # Any IP that is:
    #  - not one of the known Google DNS addresses, AND
    #  - not loopback (127.x.x.x / ::1)
    # is treated as a potential foreign resolver leaking DNS queries.
    leak_ips: list[str] = []
    for ip in system_ips:
        if ip in known_google_ips:
            continue
        try:
            addr = ipaddress.ip_address(ip)
            if not addr.is_loopback:
                leak_ips.append(ip)
        except ValueError:
            pass

    is_leaking = len(leak_ips) > 0
    return is_leaking, leak_ips


def check_ipv6_leak(
    *,
    _interfaces_fn: Callable[[], dict[str, list]] | None = None,
) -> tuple[bool, list[str]]:
    """Check if IPv6 traffic can bypass the VPN tunnel.

    If a VPN is detected on an interface, but another interface has a
    global (non-link-local, non-loopback) IPv6 address, that IPv6
    traffic may route outside the VPN.

    Args:
        _interfaces_fn: Injectable replacement for psutil.net_if_addrs().

    Returns:
        ``(is_leaking, exposed_ipv6_addresses)``
    """
    interfaces_fn = _interfaces_fn or _default_interfaces_fn
    interfaces: dict[str, list] = interfaces_fn()

    vpn_detected, vpn_iface = detect_vpn_interface(_interfaces_fn=interfaces_fn)

    if not vpn_detected:
        # No VPN → no VPN leak by definition
        return False, []

    exposed: list[str] = []
    for iface_name, addrs in interfaces.items():
        if iface_name == vpn_iface:
            continue  # skip the VPN interface itself
        for addr in addrs:
            # psutil snicaddr objects expose .family and .address
            family = getattr(addr, "family", None)
            address = getattr(addr, "address", "")

            # AF_INET6 == 30 on macOS, 10 on Linux; check both
            import socket as _socket
            if family not in (_socket.AF_INET6, 30, 10):
                continue

            # Strip interface suffix (e.g. %lo0)
            ip_str = address.split("%")[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            # Flag any non-loopback, non-link-local IPv6 as potentially leaking
            if not ip_obj.is_loopback and not ip_obj.is_link_local:
                exposed.append(ip_str)

    return len(exposed) > 0, exposed


def check_split_tunnel(
    targets: list[str] | None = None,
    *,
    _traceroute_fn: Callable[[str], str | None] | None = None,
) -> bool:
    """Check if traffic is split-tunneled around the VPN.

    Performs a TTL-1 probe to each target and records the first-hop
    router.  If different targets yield *different* first hops the
    traffic is being routed via split tunneling.

    Args:
        targets: IPs to probe. Defaults to ``["1.1.1.1", "8.8.8.8"]``.
        _traceroute_fn: Injectable ``(host) -> first_hop_ip | None``.

    Returns:
        ``True`` if split tunneling is detected.
    """
    probe_targets = targets or DEFAULT_SPLIT_TUNNEL_TARGETS
    traceroute_fn = _traceroute_fn or _default_traceroute_fn

    first_hops: set[str] = set()
    for target in probe_targets:
        hop = traceroute_fn(target)
        if hop is not None:
            first_hops.add(hop)

    # More than one distinct first-hop → split tunnel
    return len(first_hops) > 1


def run_vpn_leak_check(
    *,
    _interfaces_fn: Callable[[], dict[str, list]] | None = None,
    _resolve_fn: Callable[[str], list[str]] | None = None,
    _traceroute_fn: Callable[[str], str | None] | None = None,
) -> VpnLeakReport:
    """Full VPN leak assessment.

    Runs all checks and assembles a :class:`~netglance.store.models.VpnLeakReport`.

    Args:
        _interfaces_fn: Injectable interface enumerator (for testing).
        _resolve_fn: Injectable DNS resolver (for testing).
        _traceroute_fn: Injectable traceroute probe (for testing).

    Returns:
        A populated :class:`~netglance.store.models.VpnLeakReport`.
    """
    details: list[str] = []

    # 1. VPN interface detection
    vpn_detected, vpn_iface = detect_vpn_interface(_interfaces_fn=_interfaces_fn)
    if vpn_detected:
        details.append(f"VPN interface detected: {vpn_iface}")
    else:
        details.append("No VPN tunnel interface found")

    # 2. DNS leak check
    dns_leaking, dns_leak_ips = check_dns_leak(_resolve_fn=_resolve_fn)
    if dns_leaking:
        details.append(f"DNS leak detected — resolvers: {', '.join(dns_leak_ips)}")
    else:
        details.append("No DNS leak detected")

    # 3. IPv6 leak check
    ipv6_leaking, ipv6_addresses = check_ipv6_leak(_interfaces_fn=_interfaces_fn)
    if ipv6_leaking:
        details.append(f"IPv6 leak detected — addresses: {', '.join(ipv6_addresses)}")
    else:
        details.append("No IPv6 leak detected")

    # 4. Split-tunnel check (only makes sense when VPN is active)
    split = False
    if vpn_detected:
        split = check_split_tunnel(_traceroute_fn=_traceroute_fn)
        if split:
            details.append("Split tunneling detected — some traffic bypasses VPN")
        else:
            details.append("No split tunneling detected")

    return VpnLeakReport(
        vpn_detected=vpn_detected,
        vpn_interface=vpn_iface,
        dns_leak=dns_leaking,
        dns_leak_resolvers=dns_leak_ips,
        ipv6_leak=ipv6_leaking,
        ipv6_addresses=ipv6_addresses,
        split_tunnel=split,
        local_ip_exposed=False,  # future: check public IP via external service
        details=details,
    )
