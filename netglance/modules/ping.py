"""Connectivity and latency monitoring via ICMP ping."""

from __future__ import annotations

import ipaddress
import socket
from typing import Sequence

import icmplib
import psutil

from netglance.store.models import PingResult

# Default internet connectivity check endpoints
DEFAULT_INTERNET_ENDPOINTS: list[str] = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]


def _icmplib_host_to_result(host: str, resp: icmplib.Host) -> PingResult:
    """Convert an icmplib Host response into our PingResult dataclass."""
    return PingResult(
        host=host,
        is_alive=resp.is_alive,
        avg_latency_ms=resp.avg_rtt if resp.is_alive else None,
        min_latency_ms=resp.min_rtt if resp.is_alive else None,
        max_latency_ms=resp.max_rtt if resp.is_alive else None,
        packet_loss=resp.packet_loss,
    )


def ping_host(
    host: str,
    count: int = 4,
    timeout: float = 2.0,
    *,
    _ping_fn=None,
) -> PingResult:
    """Ping a single host and return structured results.

    Args:
        host: IP address or hostname to ping.
        count: Number of ICMP echo requests to send.
        timeout: Seconds to wait for each reply.
        _ping_fn: Injectable replacement for icmplib.ping (for testing).

    Returns:
        PingResult with latency statistics and reachability.
    """
    ping_fn = _ping_fn or icmplib.ping
    resp = ping_fn(host, count=count, timeout=timeout, privileged=False)
    return _icmplib_host_to_result(host, resp)


def ping_sweep(
    subnet: str,
    timeout: float = 1.0,
    *,
    _multiping_fn=None,
) -> list[PingResult]:
    """Ping all hosts in a subnet and return results for each.

    Args:
        subnet: CIDR notation subnet (e.g. "192.168.1.0/24").
        timeout: Seconds to wait for each reply.
        _multiping_fn: Injectable replacement for icmplib.multiping (for testing).

    Returns:
        List of PingResult, one per host address in the subnet.
    """
    network = ipaddress.ip_network(subnet, strict=False)
    addresses = [str(addr) for addr in network.hosts()]

    multiping_fn = _multiping_fn or icmplib.multiping
    responses = multiping_fn(addresses, count=1, timeout=timeout, privileged=False)

    return [
        _icmplib_host_to_result(addr, resp)
        for addr, resp in zip(addresses, responses)
    ]


def check_internet(
    endpoints: Sequence[str] | None = None,
    count: int = 4,
    timeout: float = 2.0,
    *,
    _ping_fn=None,
) -> list[PingResult]:
    """Check internet connectivity by pinging well-known public DNS servers.

    Args:
        endpoints: List of IPs to ping. Defaults to Cloudflare, Google, Quad9.
        count: Number of ICMP echo requests per host.
        timeout: Seconds to wait for each reply.
        _ping_fn: Injectable replacement for icmplib.ping (for testing).

    Returns:
        List of PingResult for each endpoint.
    """
    targets = list(endpoints) if endpoints else DEFAULT_INTERNET_ENDPOINTS
    return [
        ping_host(target, count=count, timeout=timeout, _ping_fn=_ping_fn)
        for target in targets
    ]


def get_default_gateway(*, _netifaces_fn=None) -> str | None:
    """Detect the default gateway IP address.

    Uses psutil to find the default network interface, then inspects
    the system routing to determine the gateway.

    Args:
        _netifaces_fn: Injectable callable that returns a gateway IP string
                       (for testing). If None, uses system detection.

    Returns:
        Gateway IP address string, or None if detection fails.
    """
    if _netifaces_fn is not None:
        return _netifaces_fn()

    # Strategy: parse the system's routing table via psutil net_if_addrs
    # and fall back to socket-based detection.
    try:
        import subprocess

        result = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("gateway:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass

    # Fallback: try Linux-style /proc/net/route
    try:
        import struct

        with open("/proc/net/route", "r") as f:
            for line in f.readlines()[1:]:
                fields = line.strip().split()
                if fields[1] == "00000000":  # default route
                    gateway_hex = fields[2]
                    gateway_ip = socket.inet_ntoa(
                        struct.pack("<L", int(gateway_hex, 16))
                    )
                    return gateway_ip
    except Exception:
        pass

    return None


def check_gateway(
    count: int = 4,
    timeout: float = 2.0,
    *,
    _ping_fn=None,
    _gateway_fn=None,
) -> PingResult:
    """Detect and ping the default gateway.

    Args:
        count: Number of ICMP echo requests.
        timeout: Seconds to wait for each reply.
        _ping_fn: Injectable replacement for icmplib.ping (for testing).
        _gateway_fn: Injectable callable returning gateway IP (for testing).

    Returns:
        PingResult for the default gateway.

    Raises:
        RuntimeError: If the default gateway cannot be detected.
    """
    gateway = get_default_gateway(_netifaces_fn=_gateway_fn)
    if gateway is None:
        raise RuntimeError("Could not detect default gateway")
    return ping_host(gateway, count=count, timeout=timeout, _ping_fn=_ping_fn)


def latency_color(ms: float | None) -> str:
    """Return a rich color name based on latency thresholds.

    Green: < 20ms, Yellow: < 100ms, Red: >= 100ms.
    """
    if ms is None:
        return "red"
    if ms < 20.0:
        return "green"
    if ms < 100.0:
        return "yellow"
    return "red"
