"""Network baseline capture and diff.

Captures a full snapshot of the network state (devices, ARP table, DNS
consistency, open ports, gateway MAC) and compares snapshots to detect
changes over time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from netglance.modules.arp import check_arp_anomalies, get_arp_table, get_gateway_mac
from netglance.modules.discover import (
    devices_to_dicts,
    dicts_to_devices,
    diff_devices,
    discover_all,
)
from netglance.modules.dns import check_consistency
from netglance.modules.scan import diff_scans, quick_scan
from netglance.store.db import Store
from netglance.store.models import (
    ArpEntry,
    Device,
    DnsHealthReport,
    DnsResolverResult,
    HostScanResult,
    NetworkBaseline,
    PortResult,
)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def capture_baseline(
    subnet: str,
    interface: str | None = None,
    label: str | None = None,
    *,
    _discover_fn: Callable[..., list[Device]] | None = None,
    _arp_fn: Callable[..., list[ArpEntry]] | None = None,
    _dns_fn: Callable[..., DnsHealthReport] | None = None,
    _scan_fn: Callable[..., HostScanResult] | None = None,
    _gateway_fn: Callable[..., ArpEntry | None] | None = None,
) -> NetworkBaseline:
    """Run discover, ARP, DNS, and scan modules and capture full state.

    All module calls are injectable for testing via the ``_*_fn`` keyword
    arguments.
    """
    if _discover_fn is None:
        _discover_fn = discover_all
    if _arp_fn is None:
        _arp_fn = get_arp_table
    if _dns_fn is None:
        _dns_fn = check_consistency
    if _scan_fn is None:
        _scan_fn = quick_scan
    if _gateway_fn is None:
        _gateway_fn = get_gateway_mac

    # 1. Device discovery
    devices = _discover_fn(subnet, interface)

    # 2. ARP table
    arp_table = _arp_fn()

    # 3. DNS consistency check
    dns_report: DnsHealthReport = _dns_fn("example.com")
    dns_results: list[DnsResolverResult] = dns_report.details

    # 4. Port scan only discovered device IPs
    open_ports: dict[str, list[PortResult]] = {}
    for device in devices:
        scan_result: HostScanResult = _scan_fn(device.ip)
        if scan_result.ports:
            open_ports[device.ip] = scan_result.ports

    # 5. Gateway MAC
    gw_entry = _gateway_fn(interface)
    gateway_mac = gw_entry.mac if gw_entry else None

    return NetworkBaseline(
        timestamp=datetime.now(),
        devices=devices,
        arp_table=arp_table,
        dns_results=dns_results,
        open_ports=open_ports,
        gateway_mac=gateway_mac,
        label=label,
    )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def diff_baselines(current: NetworkBaseline, previous: NetworkBaseline) -> dict:
    """Comprehensive diff between two baselines.

    Returns a dict with keys:
        new_devices, missing_devices, changed_devices,
        arp_alerts, dns_changes, port_changes
    """
    # Device diff
    device_diff = diff_devices(current.devices, previous.devices)

    # ARP anomalies
    gateway_ip: str | None = None
    # Try to find the gateway IP from ARP entries matching the gateway MAC
    if previous.gateway_mac:
        for entry in previous.arp_table:
            if entry.mac == previous.gateway_mac:
                gateway_ip = entry.ip
                break
    arp_alerts = check_arp_anomalies(
        current.arp_table, previous.arp_table, gateway_ip=gateway_ip
    )

    # DNS changes
    dns_changes: list[dict[str, Any]] = []
    prev_dns_by_resolver = {r.resolver: r for r in previous.dns_results}
    for cur_result in current.dns_results:
        prev_result = prev_dns_by_resolver.get(cur_result.resolver)
        if prev_result is None:
            dns_changes.append({
                "resolver": cur_result.resolver,
                "resolver_name": cur_result.resolver_name,
                "change": "new_resolver",
                "current_answers": cur_result.answers,
            })
        elif sorted(cur_result.answers) != sorted(prev_result.answers):
            dns_changes.append({
                "resolver": cur_result.resolver,
                "resolver_name": cur_result.resolver_name,
                "change": "answers_changed",
                "old_answers": prev_result.answers,
                "new_answers": cur_result.answers,
            })

    # Port changes per host
    port_changes: dict[str, dict[str, list[dict[str, object]]]] = {}
    all_hosts = set(current.open_ports.keys()) | set(previous.open_ports.keys())
    for host in all_hosts:
        cur_ports = current.open_ports.get(host, [])
        prev_ports = previous.open_ports.get(host, [])
        cur_scan = HostScanResult(host=host, ports=cur_ports)
        prev_scan = HostScanResult(host=host, ports=prev_ports)
        changes = diff_scans(cur_scan, prev_scan)
        if changes["new_ports"] or changes["closed_ports"] or changes["changed_services"]:
            port_changes[host] = changes

    return {
        "new_devices": device_diff["new"],
        "missing_devices": device_diff["missing"],
        "changed_devices": device_diff["changed"],
        "arp_alerts": arp_alerts,
        "dns_changes": dns_changes,
        "port_changes": port_changes,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def baseline_to_dict(baseline: NetworkBaseline) -> dict:
    """Serialise a NetworkBaseline to a JSON-compatible dict for SQLite storage."""
    return {
        "timestamp": baseline.timestamp.isoformat(),
        "label": baseline.label,
        "devices": devices_to_dicts(baseline.devices),
        "arp_table": [
            {
                "ip": e.ip,
                "mac": e.mac,
                "interface": e.interface,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in baseline.arp_table
        ],
        "dns_results": [
            {
                "resolver": r.resolver,
                "resolver_name": r.resolver_name,
                "query": r.query,
                "answers": r.answers,
                "response_time_ms": r.response_time_ms,
                "dnssec_valid": r.dnssec_valid,
                "error": r.error,
            }
            for r in baseline.dns_results
        ],
        "open_ports": {
            host: [
                {
                    "port": p.port,
                    "state": p.state,
                    "service": p.service,
                    "version": p.version,
                    "banner": p.banner,
                }
                for p in ports
            ]
            for host, ports in baseline.open_ports.items()
        },
        "gateway_mac": baseline.gateway_mac,
    }


def dict_to_baseline(data: dict) -> NetworkBaseline:
    """Deserialise a dict (from SQLite) back into a NetworkBaseline."""
    devices = dicts_to_devices(data["devices"])

    arp_table = [
        ArpEntry(
            ip=e["ip"],
            mac=e["mac"],
            interface=e.get("interface", ""),
            timestamp=datetime.fromisoformat(e["timestamp"]),
        )
        for e in data["arp_table"]
    ]

    dns_results = [
        DnsResolverResult(
            resolver=r["resolver"],
            resolver_name=r["resolver_name"],
            query=r["query"],
            answers=r.get("answers", []),
            response_time_ms=r.get("response_time_ms", 0.0),
            dnssec_valid=r.get("dnssec_valid"),
            error=r.get("error"),
        )
        for r in data["dns_results"]
    ]

    open_ports: dict[str, list[PortResult]] = {}
    for host, port_list in data["open_ports"].items():
        open_ports[host] = [
            PortResult(
                port=p["port"],
                state=p["state"],
                service=p.get("service"),
                version=p.get("version"),
                banner=p.get("banner"),
            )
            for p in port_list
        ]

    return NetworkBaseline(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        devices=devices,
        arp_table=arp_table,
        dns_results=dns_results,
        open_ports=open_ports,
        gateway_mac=data.get("gateway_mac"),
        label=data.get("label"),
    )


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def save_baseline(baseline: NetworkBaseline, store: Store) -> int:
    """Persist a baseline to SQLite via the Store. Returns the baseline ID."""
    data = baseline_to_dict(baseline)
    return store.save_baseline(data, label=baseline.label)


def load_baseline(store: Store, baseline_id: int | None = None) -> NetworkBaseline | None:
    """Load the most recent baseline (or a specific one by ID) from the Store."""
    if baseline_id is not None:
        raw = store.get_baseline(baseline_id)
    else:
        raw = store.get_latest_baseline()
    if raw is None:
        return None
    return dict_to_baseline(raw)
