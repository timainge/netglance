"""MCP server for netglance — exposes network diagnostics as AI-accessible tools.

Use ``create_mcp_server()`` to get a configured FastMCP instance, then call
``mcp.run()`` (stdio) or ``mcp.run_async(transport="sse", ...)`` for SSE.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import fastmcp
from mcp.types import ToolAnnotations

from netglance import __version__
from netglance.validation import validate_host, validate_port_range, validate_subnet, validate_url

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses / datetimes to JSON-safe types."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def _period_to_since(period: str) -> datetime:
    """Convert a period string like '24h', '7d' to a cutoff datetime."""
    period = period.strip().lower()
    try:
        if period.endswith("h"):
            hours = int(period[:-1])
            return datetime.now(timezone.utc) - timedelta(hours=hours)
        if period.endswith("d"):
            days = int(period[:-1])
            return datetime.now(timezone.utc) - timedelta(days=days)
    except ValueError:
        pass
    # Default: 24h
    return datetime.now(timezone.utc) - timedelta(hours=24)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_mcp_server(
    *,
    _discover_fn: Callable | None = None,
    _ping_gateway_fn: Callable | None = None,
    _ping_internet_fn: Callable | None = None,
    _ping_host_fn: Callable | None = None,
    _dns_fn: Callable | None = None,
    _scan_fn: Callable | None = None,
    _arp_table_fn: Callable | None = None,
    _arp_anomalies_fn: Callable | None = None,
    _tls_fn: Callable | None = None,
    _wifi_scan_fn: Callable | None = None,
    _wifi_channel_fn: Callable | None = None,
    _report_fn: Callable | None = None,
    _baseline_capture_fn: Callable | None = None,
    _baseline_load_fn: Callable | None = None,
    _baseline_diff_fn: Callable | None = None,
    _speed_fn: Callable | None = None,
    _vpn_fn: Callable | None = None,
    _fingerprint_fn: Callable | None = None,
    _store: Any = None,
    _http_fn: Callable | None = None,
    _route_fn: Callable | None = None,
    _dhcp_fn: Callable | None = None,
    _firewall_fn: Callable | None = None,
    _ipv6_fn: Callable | None = None,
    _perf_fn: Callable | None = None,
    _uptime_fn: Callable | None = None,
    _iot_fn: Callable | None = None,
    _wol_fn: Callable | None = None,
    _topology_fn: Callable | None = None,
) -> fastmcp.FastMCP:
    """Create and return a configured FastMCP server instance.

    All ``_*_fn`` parameters are dependency-injection overrides used for
    testing.  Pass ``None`` (the default) to use the real module functions.
    """
    mcp = fastmcp.FastMCP(
        name="netglance",
        instructions=(
            "netglance is a home-network situational-awareness toolkit. "
            "Use these tools to discover devices, check connectivity, audit "
            "DNS/TLS health, scan ports, monitor WiFi, and run speed tests."
        ),
        version=__version__,
    )

    # ------------------------------------------------------------------
    # Lazy imports — only pulled in when the tool is actually called so
    # that import errors on optional deps don't break the whole server.
    # ------------------------------------------------------------------

    def _get_discover():
        if _discover_fn is not None:
            return _discover_fn
        from netglance.modules.discover import discover_all
        return discover_all

    def _get_ping_gateway():
        if _ping_gateway_fn is not None:
            return _ping_gateway_fn
        from netglance.modules.ping import check_gateway
        return check_gateway

    def _get_ping_internet():
        if _ping_internet_fn is not None:
            return _ping_internet_fn
        from netglance.modules.ping import check_internet
        return check_internet

    def _get_ping_host():
        if _ping_host_fn is not None:
            return _ping_host_fn
        from netglance.modules.ping import ping_host
        return ping_host

    def _get_dns():
        if _dns_fn is not None:
            return _dns_fn
        from netglance.modules.dns import check_consistency
        return check_consistency

    def _get_scan():
        if _scan_fn is not None:
            return _scan_fn
        from netglance.modules.scan import scan_host
        return scan_host

    def _get_arp_table():
        if _arp_table_fn is not None:
            return _arp_table_fn
        from netglance.modules.arp import get_arp_table
        return get_arp_table

    def _get_arp_anomalies():
        if _arp_anomalies_fn is not None:
            return _arp_anomalies_fn
        from netglance.modules.arp import check_arp_anomalies
        return check_arp_anomalies

    def _get_tls():
        if _tls_fn is not None:
            return _tls_fn
        from netglance.modules.tls import check_multiple
        return check_multiple

    def _get_wifi_scan():
        if _wifi_scan_fn is not None:
            return _wifi_scan_fn
        from netglance.modules.wifi import scan_wifi
        return scan_wifi

    def _get_wifi_channel():
        if _wifi_channel_fn is not None:
            return _wifi_channel_fn
        from netglance.modules.wifi import channel_utilization
        return channel_utilization

    def _get_report():
        if _report_fn is not None:
            return _report_fn
        from netglance.modules.report import generate_report
        return generate_report

    def _get_speed():
        if _speed_fn is not None:
            return _speed_fn
        from netglance.modules.speed import run_speedtest
        return run_speedtest

    def _get_vpn():
        if _vpn_fn is not None:
            return _vpn_fn
        from netglance.modules.vpn import run_vpn_leak_check
        return run_vpn_leak_check

    def _get_fingerprint():
        if _fingerprint_fn is not None:
            return _fingerprint_fn
        from netglance.modules.fingerprint import fingerprint_all
        return fingerprint_all

    def _get_store():
        if _store is not None:
            return _store
        from netglance.store.db import Store
        store = Store()
        store.init_db()
        return store

    def _get_http():
        if _http_fn is not None:
            return _http_fn
        from netglance.modules.http import probe_url
        return probe_url

    def _get_route():
        if _route_fn is not None:
            return _route_fn
        from netglance.modules.route import traceroute
        return traceroute

    def _get_dhcp():
        if _dhcp_fn is not None:
            return _dhcp_fn
        from netglance.modules.dhcp import sniff_dhcp
        return sniff_dhcp

    def _get_firewall():
        if _firewall_fn is not None:
            return _firewall_fn
        from netglance.modules.firewall import run_firewall_audit
        return run_firewall_audit

    def _get_ipv6():
        if _ipv6_fn is not None:
            return _ipv6_fn
        from netglance.modules.ipv6 import run_ipv6_audit
        return run_ipv6_audit

    def _get_perf():
        if _perf_fn is not None:
            return _perf_fn
        from netglance.modules.perf import run_performance_test
        return run_performance_test

    def _get_uptime():
        if _uptime_fn is not None:
            return _uptime_fn
        from netglance.modules.uptime import get_uptime_summary
        return get_uptime_summary

    def _get_iot():
        if _iot_fn is not None:
            return _iot_fn
        from netglance.modules.iot import audit_network
        return audit_network

    def _get_wol():
        if _wol_fn is not None:
            return _wol_fn
        from netglance.modules.wol import send_wol
        return send_wol

    def _get_topology():
        if _topology_fn is not None:
            return _topology_fn
        from netglance.modules.topology import build_topology
        return build_topology

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def discover_devices(subnet: str = "192.168.1.0/24") -> list[dict]:
        """Discover all devices on the local network using ARP scanning and mDNS.

        Returns a list of devices with IP, MAC address, hostname, and vendor.
        Use this to get an inventory of everything connected to the network.

        Args:
            subnet: CIDR subnet to scan, e.g. "192.168.1.0/24".
        """
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            return [{"error": str(exc)}]
        try:
            devices = _get_discover()(subnet)
        except PermissionError:
            return [{"error": "discover_devices requires elevated privileges (sudo) for ARP scanning."}]
        return [_to_dict(d) for d in devices]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def check_connectivity(
        hosts: list[str] | None = None,
        count: int = 4,
    ) -> dict:
        """Check network connectivity to the default gateway, internet, and optional custom hosts.

        Tests whether the router (gateway) is reachable, whether public internet
        DNS servers are reachable, and optionally pings custom hosts you specify.
        Returns latency stats for each target.

        Args:
            hosts: Optional list of additional hostnames or IPs to ping.
            count: Number of ICMP echo requests per host.
        """
        result: dict[str, Any] = {}

        # Gateway
        try:
            gw = _get_ping_gateway()(count=count)
            result["gateway"] = _to_dict(gw)
        except RuntimeError as exc:
            result["gateway"] = {"error": str(exc)}

        # Internet
        internet = _get_ping_internet()(count=count)
        result["internet"] = [_to_dict(r) for r in internet]

        # Custom hosts
        if hosts:
            ping_fn = _get_ping_host()
            result["custom"] = [_to_dict(ping_fn(h, count=count)) for h in hosts]

        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def check_dns_health(domain: str = "example.com") -> dict:
        """Check DNS resolver consistency and detect potential DNS hijacking.

        Queries multiple public DNS resolvers (Cloudflare, Google, etc.) for the
        same domain and compares answers.  Inconsistent results may indicate a
        hijack.  Also reports DNSSEC support and resolver latencies.

        Args:
            domain: Domain name to use as the consistency-check query.
        """
        try:
            domain = validate_host(domain)
        except ValueError as exc:
            return {"error": str(exc)}
        report = _get_dns()(domain)
        return _to_dict(report)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def scan_ports(host: str, ports: str = "1-1024") -> dict:
        """Scan TCP ports on a host and identify open services.

        Uses nmap (if available) or a fallback pure-Python scanner to detect
        which ports are open, closed, or filtered.  Identifies service names and
        version banners where possible.

        Args:
            host: Target IP address or hostname.
            ports: Port range string, e.g. "1-1024", "22,80,443", "1-65535".
        """
        try:
            host = validate_host(host)
            ports = validate_port_range(ports)
        except ValueError as exc:
            return {"error": str(exc)}
        try:
            result = _get_scan()(host, ports=ports)
        except PermissionError:
            return {"error": "scan_ports SYN scan requires elevated privileges. Falling back may work with TCP connect scan."}
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def check_arp_table() -> dict:
        """Read the ARP table and check for anomalies (MAC changes, duplicates, MITM).

        Retrieves the current ARP cache and looks for suspicious patterns such as
        duplicate MACs (potential ARP poisoning), IP re-use, and gateway spoofing.

        Returns:
            dict with "entries" (list of ARP table entries) and "alerts" (list of
            anomaly alerts, empty if everything looks normal).
        """
        entries = _get_arp_table()()
        alerts = _get_arp_anomalies()(entries)
        return {
            "entries": [_to_dict(e) for e in entries],
            "alerts": [_to_dict(a) for a in alerts],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def check_tls_certificates(hosts: list[str] | None = None) -> list[dict]:
        """Verify TLS certificates on one or more hosts and detect interception.

        Checks certificate trust chains, expiry, issuer, and detects signs of
        TLS interception (corporate proxies, middleboxes) by comparing root CAs
        against a known-good list.

        Args:
            hosts: Hosts to check. Defaults to google.com, cloudflare.com, 1.1.1.1.
        """
        tls_fn = _get_tls()
        results = tls_fn(hosts) if hosts else tls_fn()
        return [_to_dict(r) for r in results]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def scan_wifi_environment() -> dict:
        """Scan the surrounding WiFi environment and analyse channel utilisation.

        Lists visible access points (SSID, BSSID, channel, band, signal strength,
        security) and summarises which 2.4 GHz and 5 GHz channels are congested.

        Returns:
            dict with "networks" (list of WifiNetwork) and "channel_analysis"
            (utilisation breakdown from channel_utilization()).
        """
        networks = _get_wifi_scan()()
        channel_info = _get_wifi_channel()(networks)
        return {
            "networks": [_to_dict(n) for n in networks],
            "channel_analysis": _to_dict(channel_info),
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def run_health_check(subnet: str = "192.168.1.0/24") -> dict:
        """Run a comprehensive network health check across all netglance modules.

        Executes discovery, connectivity, DNS, ARP, TLS, HTTP, and WiFi checks
        in sequence and returns a unified HealthReport with per-module status
        (pass / warn / fail / error / skip) and an overall status rollup.

        Args:
            subnet: Subnet to use for the device-discovery check.
        """
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            return {"error": str(exc)}
        report = _get_report()(subnet=subnet)
        return _to_dict(report)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False))
    def compare_to_baseline(label: str | None = None) -> dict:
        """Capture the current network state and compare it to the saved baseline.

        Takes a fresh snapshot of the network (devices, ARP, DNS, ports) and diffs
        it against the most recently saved baseline.  Highlights new/missing devices,
        MAC changes, new open ports, and DNS answer changes.

        Args:
            label: Optional label for the saved baseline (used when loading a named
                   baseline rather than the latest one).
        """
        if _baseline_capture_fn is not None and _baseline_load_fn is not None and _baseline_diff_fn is not None:
            # Fully injected (for testing)
            current = _baseline_capture_fn()
            store = _get_store()
            previous = _baseline_load_fn(store)
            if previous is None:
                return {"error": "No baseline found. Run 'netglance baseline save' first."}
            diff = _baseline_diff_fn(current, previous)
            return _to_dict(diff)

        from netglance.modules.baseline import (
            capture_baseline,
            diff_baselines,
            load_baseline,
        )
        store = _get_store()
        previous = load_baseline(store)
        if previous is None:
            return {"error": "No baseline found. Run 'netglance baseline save' first."}
        current = capture_baseline()
        diff = diff_baselines(current, previous)
        return _to_dict(diff)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def run_speed_test(provider: str = "cloudflare") -> dict:
        """Run a network speed test measuring download, upload, and latency.

        Downloads and uploads test payloads to measure throughput. Supports
        'cloudflare' (HTTP-based) and 'ookla'/'iperf3' providers if installed.

        Args:
            provider: Speed test provider. One of "cloudflare", "ookla", "iperf3".
        """
        result = _get_speed()(provider=provider)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def check_vpn_leaks() -> dict:
        """Check for VPN DNS and IPv6 leaks.

        Detects whether a VPN is active, and if so, checks whether DNS queries or
        IPv6 traffic could be leaking outside the VPN tunnel.

        Returns:
            VpnLeakReport dict with vpn_detected, dns_leak, ipv6_leak, and details.
        """
        result = _get_vpn()()
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def identify_devices(subnet: str = "192.168.1.0/24") -> list[dict]:
        """Fingerprint and classify devices on the network.

        Goes beyond basic ARP discovery to identify device types (phone, laptop,
        router, IoT), manufacturers, and operating systems using mDNS, UPnP, port
        banners, and hostname analysis.

        Args:
            subnet: Subnet to fingerprint.
        """
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            return [{"error": str(exc)}]
        profiles = _get_fingerprint()(subnet)
        return [_to_dict(p) for p in profiles]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_metrics(metric: str, period: str = "24h") -> dict:
        """Query stored metric time-series data.

        Retrieves historical metric samples from the netglance database and returns
        them with summary statistics (avg, min, max, count).

        Args:
            metric: Metric name, e.g. "download_mbps", "ping_rtt_ms".
            period: Time window, e.g. "24h", "7d", "1h".

        Returns:
            dict with "metric", "period", "series" (list of {ts, value}) and "stats".
        """
        since = _period_to_since(period)
        store = _get_store()
        series = store.get_metric_series(metric, since=since)
        stats = store.get_metric_stats(metric, since=since)
        return {
            "metric": metric,
            "period": period,
            "series": series,
            "stats": stats,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_alert_log(hours: int = 24) -> list[dict]:
        """Retrieve recent alert log entries from the netglance database.

        Returns threshold-crossing alerts recorded by the daemon, including
        the metric name, value, threshold, and whether the alert was acknowledged.

        Args:
            hours: How many hours of history to return (default 24).
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        store = _get_store()
        rows = store.conn.execute(
            "SELECT id, ts, rule_id, metric, value, threshold, message, acknowledged "
            "FROM alert_log WHERE ts >= ? ORDER BY ts DESC",
            (since.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def check_http_headers(url: str) -> dict:
        """Probe a URL and check HTTP response headers for signs of proxy injection.

        Examines headers for suspicious proxy indicators, content injection,
        and transparent proxy detection.

        Args:
            url: The URL to probe (e.g. "http://example.com").
        """
        try:
            url = validate_url(url)
        except ValueError as exc:
            return {"error": str(exc)}
        result = _get_http()(url)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def trace_route(host: str, max_hops: int = 30) -> dict:
        """Trace the network path to a destination host.

        Performs a traceroute showing each hop, RTT, and ASN information.
        Useful for diagnosing routing issues or identifying where packets are being dropped.

        Args:
            host: Destination hostname or IP address.
            max_hops: Maximum number of hops to trace (default 30).
        """
        try:
            host = validate_host(host)
        except ValueError as exc:
            return {"error": str(exc)}
        try:
            result = _get_route()(host, max_hops=max_hops)
        except PermissionError:
            return {"error": "trace_route requires elevated privileges (sudo) for raw ICMP packets."}
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def check_dhcp(timeout: float = 5.0) -> list[dict]:
        """Listen for DHCP traffic on the local network.

        Passively sniffs DHCP discover, offer, request, and ack packets.
        Useful for identifying rogue DHCP servers or lease issues.

        Args:
            timeout: Seconds to listen for DHCP traffic (default 5.0).
        """
        try:
            events = _get_dhcp()(timeout=timeout)
        except PermissionError:
            return [{"error": "check_dhcp requires elevated privileges (sudo) for packet capture."}]
        return [_to_dict(e) for e in events]

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def audit_firewall() -> dict:
        """Test egress firewall rules by probing common outbound ports.

        Checks whether commonly used ports (HTTP, HTTPS, SSH, DNS, etc.) are
        open or blocked for outbound traffic. Helps identify overly restrictive
        or misconfigured firewall rules.
        """
        result = _get_firewall()()
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def check_ipv6() -> dict:
        """Audit IPv6 configuration and discover IPv6 neighbours.

        Checks local IPv6 addresses, classifies address types (EUI-64, temporary,
        link-local), detects privacy extensions, and discovers IPv6 neighbours.
        Reports DNS leak risk from IPv6.
        """
        result = _get_ipv6()()
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def assess_performance(host: str) -> dict:
        """Assess network performance to a target host.

        Measures jitter, packet loss, path MTU, and bufferbloat. Provides latency
        percentiles (p95, p99) for a detailed quality assessment.

        Args:
            host: Target hostname or IP to measure against.
        """
        try:
            host = validate_host(host)
        except ValueError as exc:
            return {"error": str(exc)}
        result = _get_perf()(host)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_uptime_summary(host: str, period: str = "24h") -> dict:
        """Get uptime history for a monitored host.

        Returns uptime percentage, total checks, outage windows, and average
        latency over the specified time period. Requires prior uptime monitoring
        data in the database.

        Args:
            host: Hostname or IP to query uptime for.
            period: Time period, e.g. "24h", "7d", "30d".
        """
        try:
            host = validate_host(host)
        except ValueError as exc:
            return {"error": str(exc)}
        result = _get_uptime()(host, period=period)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def audit_iot_devices(subnet: str = "192.168.1.0/24") -> dict:
        """Discover and audit IoT devices on the network for security risks.

        Finds all devices on the subnet, then classifies IoT devices (cameras,
        smart speakers, thermostats, etc.) and assigns risk scores based on
        open ports, known vulnerabilities, and device type.

        Args:
            subnet: CIDR subnet to scan for IoT devices.
        """
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            return {"error": str(exc)}
        devices = _get_discover()(subnet)
        result = _get_iot()(devices)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False))
    def send_wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> dict:
        """Send a Wake-on-LAN magic packet to wake a device.

        Sends a WoL magic packet to the specified MAC address. The target device
        must support WoL and be connected via Ethernet.

        Args:
            mac: Target MAC address (e.g. "aa:bb:cc:dd:ee:ff").
            broadcast: Broadcast address (default "255.255.255.255").
        """
        result = _get_wol()(mac, broadcast=broadcast)
        return _to_dict(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True, destructiveHint=False))
    def get_network_topology(subnet: str = "192.168.1.0/24") -> dict:
        """Build a topology map of the network.

        Discovers devices, reads ARP tables, and traces routes to build a
        graph of how devices are connected. Returns nodes, edges, and an
        ASCII visualisation.

        Args:
            subnet: CIDR subnet to map.
        """
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            return {"error": str(exc)}
        from netglance.modules.topology import topology_to_ascii

        devices = _get_discover()(subnet)
        arp_entries = _get_arp_table()()
        topology = _get_topology()(devices, arp_entries, [], None)
        ascii_map = topology_to_ascii(topology)
        result = _to_dict(topology)
        result["ascii"] = ascii_map
        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False))
    def get_server_capabilities() -> dict:
        """Report which netglance tools are available at the current privilege level.

        Checks whether the server is running with elevated privileges (root/sudo)
        and reports which tools may be degraded without them.
        """
        privileged = os.geteuid() == 0
        needs_root = {
            "discover_devices": "ARP scanning requires raw sockets",
            "scan_ports": "SYN scan requires raw sockets (TCP connect fallback available)",
            "check_dhcp": "DHCP sniffing requires packet capture",
            "trace_route": "Raw ICMP requires raw sockets",
            "get_network_topology": "Uses discover (ARP scan) internally",
            "audit_iot_devices": "Uses discover (ARP scan) internally",
        }
        tools_status = {}
        for name, reason in needs_root.items():
            tools_status[name] = {
                "available": True,
                "privileged_mode": privileged,
                "note": None if privileged else reason,
            }
        return {
            "privileged": privileged,
            "version": __version__,
            "total_tools": 25,
            "tools_needing_privileges": tools_status,
        }

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("netglance://baseline/current")
    def resource_baseline() -> str:
        """Current network baseline snapshot stored in the netglance database."""
        store = _get_store()
        data = store.get_latest_baseline()
        if data is None:
            return json.dumps({"error": "No baseline saved. Run 'netglance baseline save' first."})
        return json.dumps(data, default=str)

    @mcp.resource("netglance://config")
    def resource_config() -> str:
        """Current netglance configuration (settings.yaml)."""
        try:
            from netglance.config.settings import load_config
            cfg = load_config()
            return json.dumps(dataclasses.asdict(cfg), default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.resource("netglance://devices")
    def resource_devices() -> str:
        """Last known device inventory from the netglance database."""
        store = _get_store()
        rows = store.get_results("discover", limit=1)
        if not rows:
            return json.dumps({"error": "No device inventory found. Run 'netglance discover' first."})
        return json.dumps(rows[0], default=str)

    return mcp


def main():
    """Entry point for the ``netglance-mcp`` console script (stdio transport)."""
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
