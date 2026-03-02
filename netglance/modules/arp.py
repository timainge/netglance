"""ARP table monitor & MITM detection.

Reads the OS ARP table, detects anomalies such as MAC address changes,
duplicate MACs, duplicate IPs, and gateway spoofing by comparing
current state against a saved baseline.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from typing import Callable

from netglance.store.models import ArpAlert, ArpEntry


# ---------------------------------------------------------------------------
# Thin wrapper around the OS subprocess call (easy to mock)
# ---------------------------------------------------------------------------

def _run_arp_command() -> str:
    """Run ``arp -a`` and return raw stdout."""
    result = subprocess.run(
        ["arp", "-a"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout


def _run_route_command() -> str:
    """Run ``route -n get default`` (macOS) and return raw stdout."""
    result = subprocess.run(
        ["route", "-n", "get", "default"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# macOS ARP-table parser
# ---------------------------------------------------------------------------

# Typical macOS line:
#   ? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
_ARP_LINE_RE = re.compile(
    r"\?\s+\((?P<ip>[\d.]+)\)\s+at\s+(?P<mac>[0-9a-fA-F:]+)\s+on\s+(?P<iface>\S+)"
)


def parse_arp_output(raw: str) -> list[ArpEntry]:
    """Parse the output of ``arp -a`` into a list of :class:`ArpEntry`."""
    entries: list[ArpEntry] = []
    for line in raw.splitlines():
        m = _ARP_LINE_RE.search(line)
        if m:
            entries.append(
                ArpEntry(
                    ip=m.group("ip"),
                    mac=m.group("mac").lower(),
                    interface=m.group("iface"),
                )
            )
    return entries


def parse_gateway_ip(raw: str) -> str | None:
    """Extract the gateway IP from ``route -n get default`` output."""
    for line in raw.splitlines():
        if "gateway" in line.lower():
            parts = line.split(":")
            if len(parts) >= 2:
                return parts[1].strip()
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_arp_table(
    *,
    _run_arp: Callable[[], str] | None = None,
) -> list[ArpEntry]:
    """Read and return the current OS ARP table.

    Parameters
    ----------
    _run_arp:
        Injectable callable that returns the raw ``arp -a`` output.
        Defaults to the real subprocess wrapper.
    """
    if _run_arp is None:
        _run_arp = _run_arp_command
    raw = _run_arp()
    return parse_arp_output(raw)


def get_gateway_mac(
    interface: str | None = None,
    *,
    _run_arp: Callable[[], str] | None = None,
    _run_route: Callable[[], str] | None = None,
) -> ArpEntry | None:
    """Return the ARP entry for the default gateway.

    Parameters
    ----------
    interface:
        Restrict the lookup to a specific network interface.
    _run_arp:
        Injectable callable returning ``arp -a`` output.
    _run_route:
        Injectable callable returning ``route -n get default`` output.
    """
    if _run_route is None:
        _run_route = _run_route_command
    if _run_arp is None:
        _run_arp = _run_arp_command

    gateway_ip = parse_gateway_ip(_run_route())
    if not gateway_ip:
        return None

    entries = get_arp_table(_run_arp=_run_arp)
    for entry in entries:
        if entry.ip == gateway_ip:
            if interface is None or entry.interface == interface:
                return entry
    return None


def check_arp_anomalies(
    current: list[ArpEntry],
    baseline: list[ArpEntry],
    gateway_ip: str | None = None,
) -> list[ArpAlert]:
    """Compare *current* ARP table against *baseline* and return alerts.

    Detection categories
    --------------------
    * **mac_changed** -- same IP, different MAC (critical if it is the gateway)
    * **duplicate_mac** -- multiple IPs share the same MAC (warning)
    * **duplicate_ip** -- same IP appears with multiple MACs (warning, possible MITM)
    * **gateway_spoof** -- gateway IP has a different MAC than baseline (critical)
    """
    alerts: list[ArpAlert] = []

    # Build lookup maps
    baseline_by_ip: dict[str, ArpEntry] = {e.ip: e for e in baseline}

    # --- mac_changed & gateway_spoof ---
    for entry in current:
        if entry.ip in baseline_by_ip:
            old = baseline_by_ip[entry.ip]
            if entry.mac != old.mac:
                is_gateway = gateway_ip is not None and entry.ip == gateway_ip

                if is_gateway:
                    alerts.append(
                        ArpAlert(
                            alert_type="gateway_spoof",
                            severity="critical",
                            description=(
                                f"Gateway {entry.ip} MAC changed from "
                                f"{old.mac} to {entry.mac} — possible ARP spoofing"
                            ),
                            old_value=old.mac,
                            new_value=entry.mac,
                        )
                    )
                else:
                    alerts.append(
                        ArpAlert(
                            alert_type="mac_changed",
                            severity="critical",
                            description=(
                                f"IP {entry.ip} changed MAC from "
                                f"{old.mac} to {entry.mac}"
                            ),
                            old_value=old.mac,
                            new_value=entry.mac,
                        )
                    )

    # --- duplicate_mac (in current table) ---
    mac_to_ips: dict[str, list[str]] = {}
    for entry in current:
        mac_to_ips.setdefault(entry.mac, []).append(entry.ip)

    for mac, ips in mac_to_ips.items():
        if len(ips) > 1:
            alerts.append(
                ArpAlert(
                    alert_type="duplicate_mac",
                    severity="warning",
                    description=(
                        f"MAC {mac} is shared by multiple IPs: "
                        f"{', '.join(sorted(ips))}"
                    ),
                    old_value=None,
                    new_value=mac,
                )
            )

    # --- duplicate_ip (in current table) ---
    ip_to_macs: dict[str, list[str]] = {}
    for entry in current:
        ip_to_macs.setdefault(entry.ip, []).append(entry.mac)

    for ip, macs in ip_to_macs.items():
        if len(macs) > 1:
            alerts.append(
                ArpAlert(
                    alert_type="duplicate_ip",
                    severity="warning",
                    description=(
                        f"IP {ip} has multiple MACs: "
                        f"{', '.join(sorted(macs))} — possible MITM"
                    ),
                    old_value=None,
                    new_value=ip,
                )
            )

    return alerts


def watch_arp(
    callback: Callable[[list[ArpEntry]], None],
    interval: float = 5.0,
    *,
    _run_arp: Callable[[], str] | None = None,
    _sleep: Callable[[float], None] | None = None,
) -> None:
    """Continuously poll the ARP table and invoke *callback* with each snapshot.

    Runs forever until interrupted. The *_sleep* and *_run_arp* parameters are
    injectable for testing.
    """
    if _run_arp is None:
        _run_arp = _run_arp_command
    if _sleep is None:
        _sleep = time.sleep

    while True:
        entries = get_arp_table(_run_arp=_run_arp)
        callback(entries)
        _sleep(interval)
