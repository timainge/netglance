"""Port scanning and service enumeration.

Provides host-level port scanning with optional nmap integration.
Falls back to scapy TCP SYN scanning when nmap is not available.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime

import nmap3
from scapy.all import IP, TCP, sr1

from netglance.store.models import HostScanResult, PortResult

# Well-known ports commonly associated with insecure or suspicious services.
SUSPICIOUS_PORTS: list[int] = [
    21,    # FTP
    23,    # Telnet
    135,   # MS-RPC
    139,   # NetBIOS
    445,   # SMB
    1433,  # MSSQL
    1434,  # MSSQL Browser
    3389,  # RDP
    5900,  # VNC
    5985,  # WinRM HTTP
    5986,  # WinRM HTTPS
    6379,  # Redis
    8080,  # HTTP Proxy / alt HTTP
    8443,  # alt HTTPS
    9200,  # Elasticsearch
    27017, # MongoDB
]

# Top 100 most commonly used TCP ports.
TOP_100_PORTS: list[int] = [
    7, 9, 13, 21, 22, 23, 25, 26, 37, 53,
    79, 80, 81, 88, 106, 110, 111, 113, 119, 135,
    139, 143, 144, 179, 199, 389, 427, 443, 444, 445,
    465, 513, 514, 515, 543, 544, 548, 554, 587, 631,
    646, 873, 990, 993, 995, 1025, 1026, 1027, 1028, 1029,
    1110, 1433, 1720, 1723, 1755, 1900, 2000, 2001, 2049, 2121,
    2717, 3000, 3128, 3306, 3389, 3986, 4899, 5000, 5009, 5051,
    5060, 5101, 5190, 5357, 5432, 5631, 5666, 5800, 5900, 5901,
    6000, 6001, 6646, 7070, 8000, 8008, 8080, 8083, 8443, 8888,
    9100, 9200, 9999, 10000, 27017, 32768, 49152, 49153, 49154, 49155,
]


def has_nmap() -> bool:
    """Check whether the nmap binary is available on the system PATH."""
    return shutil.which("nmap") is not None


def _parse_port_range(ports: str) -> list[int]:
    """Parse a port specification string like '22,80,443' or '1-1024' into a list of ints."""
    result: list[int] = []
    for part in ports.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            result.extend(range(start, end + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def _scan_with_nmap(host: str, ports: str = "1-1024", timeout: float = 5.0) -> HostScanResult:
    """Scan using python3-nmap wrapper around the nmap binary."""
    nm = nmap3.Nmap()
    start = time.monotonic()

    # Use nmap's service version detection
    raw = nm.scan_top_ports(host, args=f"-p {ports} --host-timeout {int(timeout)}s")

    elapsed = time.monotonic() - start

    open_ports: list[PortResult] = []
    host_data = raw.get(host, {})

    if isinstance(host_data, dict) and "ports" in host_data:
        for port_info in host_data["ports"]:
            state = port_info.get("state", "closed")
            if state in ("open", "filtered"):
                service_info = port_info.get("service", {})
                open_ports.append(
                    PortResult(
                        port=int(port_info["portid"]),
                        state=state,
                        service=service_info.get("name"),
                        version=service_info.get("version") or None,
                        banner=service_info.get("product") or None,
                    )
                )

    return HostScanResult(
        host=host,
        ports=open_ports,
        scan_time=datetime.now(),
        scan_duration_s=round(elapsed, 3),
    )


def _scan_with_scapy(host: str, ports: str = "1-1024", timeout: float = 5.0) -> HostScanResult:
    """Fallback TCP SYN scan using scapy when nmap is not available."""
    port_list = _parse_port_range(ports)
    open_ports: list[PortResult] = []
    start = time.monotonic()

    per_port_timeout = min(timeout, 2.0)

    for port in port_list:
        pkt = IP(dst=host) / TCP(dport=port, flags="S")
        resp = sr1(pkt, timeout=per_port_timeout, verbose=0)

        if resp is not None and resp.haslayer(TCP):
            tcp_layer = resp.getlayer(TCP)
            if tcp_layer.flags == 0x12:  # SYN-ACK
                open_ports.append(
                    PortResult(
                        port=port,
                        state="open",
                        service=None,
                        version=None,
                        banner=None,
                    )
                )
            elif tcp_layer.flags == 0x14:  # RST-ACK
                pass  # closed, skip
        # No response => filtered, could add if desired

    elapsed = time.monotonic() - start

    return HostScanResult(
        host=host,
        ports=open_ports,
        scan_time=datetime.now(),
        scan_duration_s=round(elapsed, 3),
    )


def scan_host(host: str, ports: str = "1-1024", timeout: float = 5.0) -> HostScanResult:
    """Scan a host for open ports.

    Uses nmap (via python3-nmap) when available, otherwise falls back to
    a scapy TCP SYN scan.

    Args:
        host: Target hostname or IP address.
        ports: Port specification, e.g. '22,80,443' or '1-1024'.
        timeout: Per-scan timeout in seconds.

    Returns:
        HostScanResult with open/filtered ports found.
    """
    if has_nmap():
        return _scan_with_nmap(host, ports=ports, timeout=timeout)
    return _scan_with_scapy(host, ports=ports, timeout=timeout)


def quick_scan(host: str, timeout: float = 5.0) -> HostScanResult:
    """Scan the top 100 most common ports on a host.

    Args:
        host: Target hostname or IP address.
        timeout: Per-scan timeout in seconds.

    Returns:
        HostScanResult with open ports from the top-100 list.
    """
    ports_str = ",".join(str(p) for p in TOP_100_PORTS)
    return scan_host(host, ports=ports_str, timeout=timeout)


def diff_scans(
    current: HostScanResult, previous: HostScanResult
) -> dict[str, list[dict[str, object]]]:
    """Compare two scan results and return the differences.

    Args:
        current: The latest scan result.
        previous: An earlier scan result to compare against.

    Returns:
        Dict with keys 'new_ports', 'closed_ports', and 'changed_services'.
        Each value is a list of dicts describing the change.
    """
    current_by_port = {p.port: p for p in current.ports}
    previous_by_port = {p.port: p for p in previous.ports}

    current_port_nums = set(current_by_port.keys())
    previous_port_nums = set(previous_by_port.keys())

    new_ports: list[dict[str, object]] = []
    for port_num in sorted(current_port_nums - previous_port_nums):
        p = current_by_port[port_num]
        new_ports.append({
            "port": p.port,
            "state": p.state,
            "service": p.service,
        })

    closed_ports: list[dict[str, object]] = []
    for port_num in sorted(previous_port_nums - current_port_nums):
        p = previous_by_port[port_num]
        closed_ports.append({
            "port": p.port,
            "state": p.state,
            "service": p.service,
        })

    changed_services: list[dict[str, object]] = []
    for port_num in sorted(current_port_nums & previous_port_nums):
        cur = current_by_port[port_num]
        prev = previous_by_port[port_num]
        if cur.service != prev.service or cur.version != prev.version:
            changed_services.append({
                "port": port_num,
                "old_service": prev.service,
                "new_service": cur.service,
                "old_version": prev.version,
                "new_version": cur.version,
            })

    return {
        "new_ports": new_ports,
        "closed_ports": closed_ports,
        "changed_services": changed_services,
    }
