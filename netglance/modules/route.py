"""Traceroute and path analysis module.

Provides traceroute functionality with per-hop ASN/hostname resolution,
route persistence, and route-diff detection for spotting path changes.
"""

from __future__ import annotations

import socket
from dataclasses import asdict
from datetime import datetime
from typing import Any

from netglance.store.models import Hop, TraceResult


# ---------------------------------------------------------------------------
# Thin wrappers around network I/O -- easy to mock in tests
# ---------------------------------------------------------------------------


def _scapy_traceroute(host: str, max_hops: int, timeout: float) -> list[dict[str, Any]]:
    """Run scapy traceroute and return raw hop data.

    Returns a list of dicts with keys: ttl, ip, rtt_ms.
    Non-responsive hops are included with ip=None, rtt_ms=None.
    """
    from scapy.all import IP, TCP, sr  # type: ignore[import-untyped]

    # Build packets for each TTL value
    packets = [IP(dst=host, ttl=ttl) / TCP(dport=80, flags="S") for ttl in range(1, max_hops + 1)]
    answered, unanswered = sr(packets, timeout=timeout, verbose=0)

    # Build a map of ttl -> (ip, rtt_ms) from answered packets
    hop_map: dict[int, tuple[str, float]] = {}
    for sent, received in answered:
        ttl = sent.ttl
        ip = received.src
        rtt_ms = (received.time - sent.sent_time) * 1000.0
        hop_map[ttl] = (ip, rtt_ms)

    # Build result for all TTLs, marking non-responsive hops
    results: list[dict[str, Any]] = []
    for ttl in range(1, max_hops + 1):
        if ttl in hop_map:
            ip, rtt_ms = hop_map[ttl]
            results.append({"ttl": ttl, "ip": ip, "rtt_ms": rtt_ms})
        else:
            results.append({"ttl": ttl, "ip": None, "rtt_ms": None})

    return results


def _resolve_hostname(ip: str) -> str | None:
    """Reverse-DNS lookup for an IP address."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        return None


def _lookup_asn(ip: str) -> tuple[str | None, str | None]:
    """Look up ASN information for an IP address using DNS-based Team Cymru lookup.

    Returns (asn, as_name) tuple. Returns (None, None) on failure.
    """
    import dns.resolver  # type: ignore[import-untyped]

    try:
        # Reverse the IP octets for the Team Cymru DNS query
        octets = ip.split(".")
        reversed_ip = ".".join(reversed(octets))
        query = f"{reversed_ip}.origin.asn.cymru.com"
        answers = dns.resolver.resolve(query, "TXT")
        if not answers:
            return None, None

        # Response format: "ASN | prefix | CC | registry | date"
        txt = str(answers[0]).strip('"')
        parts = [p.strip() for p in txt.split("|")]
        asn = parts[0] if parts else None

        # Now look up the AS name
        if asn:
            name_query = f"AS{asn}.asn.cymru.com"
            name_answers = dns.resolver.resolve(name_query, "TXT")
            if name_answers:
                name_txt = str(name_answers[0]).strip('"')
                name_parts = [p.strip() for p in name_txt.split("|")]
                as_name = name_parts[-1].strip() if name_parts else None
                return f"AS{asn}", as_name

        return f"AS{asn}" if asn else None, None
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_dest(host: str) -> str:
    """Resolve a hostname to an IP address for destination matching."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return host


def traceroute(
    host: str,
    max_hops: int = 30,
    timeout: float = 2.0,
    *,
    _traceroute_fn=_scapy_traceroute,
    _hostname_fn=_resolve_hostname,
    _asn_fn=_lookup_asn,
    _resolve_dest_fn=_resolve_dest,
) -> TraceResult:
    """Run a traceroute to *host* and return structured results.

    Each hop includes reverse-DNS hostname and ASN information where available.
    Non-responsive hops are represented with ip=None and rtt_ms=None.

    Args:
        host: Target hostname or IP address.
        max_hops: Maximum TTL (number of hops) to probe.
        timeout: Seconds to wait for each probe reply.
        _traceroute_fn: Injectable replacement for scapy traceroute (for testing).
        _hostname_fn: Injectable replacement for hostname resolution (for testing).
        _asn_fn: Injectable replacement for ASN lookup (for testing).
        _resolve_dest_fn: Injectable replacement for destination IP resolution (for testing).

    Returns:
        TraceResult with hop-by-hop path data.
    """
    raw_hops = _traceroute_fn(host, max_hops, timeout)

    hops: list[Hop] = []
    reached = False

    # Resolve the destination IP for reachability check
    dest_ip = _resolve_dest_fn(host)

    for raw in raw_hops:
        ip = raw["ip"]
        rtt_ms = raw["rtt_ms"]
        ttl = raw["ttl"]

        hostname: str | None = None
        asn: str | None = None
        as_name: str | None = None

        if ip is not None:
            hostname = _hostname_fn(ip)
            asn, as_name = _asn_fn(ip)
            if ip == dest_ip:
                reached = True

        hops.append(
            Hop(
                ttl=ttl,
                ip=ip,
                hostname=hostname,
                rtt_ms=rtt_ms,
                asn=asn,
                as_name=as_name,
            )
        )

    # Trim trailing non-responsive hops after the last responsive hop.
    # If no hops responded at all, return an empty list.
    if hops:
        last_responsive = -1
        for i, hop in enumerate(hops):
            if hop.ip is not None:
                last_responsive = i
        if last_responsive >= 0:
            hops = hops[: last_responsive + 1]
        else:
            # All hops were non-responsive
            hops = []

    return TraceResult(
        destination=host,
        hops=hops,
        reached=reached,
    )


def diff_routes(current: TraceResult, previous: TraceResult) -> dict[str, Any]:
    """Compare two traceroute results and report changes.

    Returns a dict with:
        changed_hops: list of dicts with ttl, old_ip, new_ip for hops that differ.
        new_asns: list of ASN strings seen in current but not in previous.
        path_length_delta: difference in hop count (current - previous).
    """
    changed_hops: list[dict[str, Any]] = []

    max_len = max(len(current.hops), len(previous.hops))
    for i in range(max_len):
        cur_hop = current.hops[i] if i < len(current.hops) else None
        prev_hop = previous.hops[i] if i < len(previous.hops) else None

        cur_ip = cur_hop.ip if cur_hop else None
        prev_ip = prev_hop.ip if prev_hop else None

        if cur_ip != prev_ip:
            ttl = (cur_hop.ttl if cur_hop else prev_hop.ttl) if (cur_hop or prev_hop) else i + 1
            changed_hops.append(
                {
                    "ttl": ttl,
                    "old_ip": prev_ip,
                    "new_ip": cur_ip,
                }
            )

    # Collect ASNs from each route
    current_asns = {hop.asn for hop in current.hops if hop.asn is not None}
    previous_asns = {hop.asn for hop in previous.hops if hop.asn is not None}
    new_asns = sorted(current_asns - previous_asns)

    path_length_delta = len(current.hops) - len(previous.hops)

    return {
        "changed_hops": changed_hops,
        "new_asns": new_asns,
        "path_length_delta": path_length_delta,
    }


# ---------------------------------------------------------------------------
# Serialisation helpers (for store / JSON output)
# ---------------------------------------------------------------------------


def trace_to_dict(result: TraceResult) -> dict[str, Any]:
    """Convert a TraceResult to a serialisable dict."""
    return {
        "destination": result.destination,
        "reached": result.reached,
        "timestamp": result.timestamp.isoformat(),
        "hops": [asdict(hop) for hop in result.hops],
    }


def dict_to_trace(data: dict[str, Any]) -> TraceResult:
    """Reconstruct a TraceResult from a serialised dict."""
    hops = [Hop(**hop_data) for hop_data in data["hops"]]
    return TraceResult(
        destination=data["destination"],
        hops=hops,
        reached=data["reached"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )
