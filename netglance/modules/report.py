"""Aggregate health report module.

Runs checks across all netglance modules and produces a unified health report
with per-module status, summaries, and an overall network health assessment.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Any, Callable

from netglance.store.models import CheckStatus, HealthReport

if TYPE_CHECKING:
    from netglance.store.db import Store

# Status severity ordering: pass < warn < fail < error  (skip is excluded)
STATUS_ORDER: dict[str, int] = {"pass": 0, "warn": 1, "fail": 2, "error": 3, "skip": -1}


# ---------------------------------------------------------------------------
# Individual module check functions
# ---------------------------------------------------------------------------


def _check_discover(subnet: str = "192.168.1.0/24", **kwargs: Any) -> CheckStatus:
    """Run discovery and report device count."""
    try:
        discover_fn = kwargs.get("_discover_fn")
        if discover_fn is None:
            from netglance.modules.discover import discover_all

            discover_fn = discover_all
        devices = discover_fn(subnet)
        count = len(devices)
        return CheckStatus(
            module="discover",
            status="pass",
            summary=f"Found {count} device(s) on {subnet}",
            details=[f"{d.ip} ({d.mac}) - {d.hostname or 'unknown'}" for d in devices],
        )
    except Exception as e:
        return CheckStatus(
            module="discover",
            status="error",
            summary=str(e),
        )


def _check_ping(**kwargs: Any) -> CheckStatus:
    """Check gateway and internet connectivity."""
    try:
        gateway_fn = kwargs.get("_gateway_fn")
        internet_fn = kwargs.get("_internet_fn")
        if gateway_fn is None:
            from netglance.modules.ping import check_gateway

            gateway_fn = check_gateway
        if internet_fn is None:
            from netglance.modules.ping import check_internet

            internet_fn = check_internet

        details: list[str] = []
        all_ok = True
        any_ok = False

        # Check gateway
        try:
            gw = gateway_fn()
            if gw.is_alive:
                details.append(f"Gateway {gw.host}: UP ({gw.avg_latency_ms:.1f} ms)")
                any_ok = True
            else:
                details.append(f"Gateway {gw.host}: DOWN")
                all_ok = False
        except RuntimeError as e:
            details.append(f"Gateway: {e}")
            all_ok = False

        # Check internet
        internet_results = internet_fn()
        alive = [r for r in internet_results if r.is_alive]
        dead = [r for r in internet_results if not r.is_alive]
        for r in internet_results:
            if r.is_alive:
                details.append(f"Internet {r.host}: UP ({r.avg_latency_ms:.1f} ms)")
                any_ok = True
            else:
                details.append(f"Internet {r.host}: DOWN")
                all_ok = False

        if all_ok:
            return CheckStatus(
                module="ping",
                status="pass",
                summary="Gateway and internet connectivity OK",
                details=details,
            )
        elif any_ok:
            return CheckStatus(
                module="ping",
                status="warn",
                summary="Partial connectivity issues detected",
                details=details,
            )
        else:
            return CheckStatus(
                module="ping",
                status="fail",
                summary="All connectivity checks failed",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="ping",
            status="error",
            summary=str(e),
        )


def _check_dns(**kwargs: Any) -> CheckStatus:
    """Run DNS consistency check."""
    try:
        dns_fn = kwargs.get("_dns_fn")
        if dns_fn is None:
            from netglance.modules.dns import check_consistency

            dns_fn = check_consistency

        report = dns_fn("example.com")
        details: list[str] = []
        for r in report.details:
            if r.error:
                details.append(f"{r.resolver_name} ({r.resolver}): {r.error}")
            else:
                details.append(
                    f"{r.resolver_name} ({r.resolver}): "
                    f"{', '.join(r.answers)} ({r.response_time_ms:.1f} ms)"
                )

        if report.potential_hijack:
            return CheckStatus(
                module="dns",
                status="fail",
                summary="Potential DNS hijack detected - resolver answers diverge",
                details=details,
            )
        elif not report.consistent:
            return CheckStatus(
                module="dns",
                status="warn",
                summary="DNS resolvers returned inconsistent results",
                details=details,
            )
        else:
            fastest = report.fastest_resolver or "unknown"
            return CheckStatus(
                module="dns",
                status="pass",
                summary=f"DNS resolvers consistent, fastest: {fastest}",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="dns",
            status="error",
            summary=str(e),
        )


def _check_arp(**kwargs: Any) -> CheckStatus:
    """Check ARP table for anomalies (informational)."""
    try:
        arp_fn = kwargs.get("_arp_fn")
        if arp_fn is None:
            from netglance.modules.arp import get_arp_table

            arp_fn = get_arp_table

        entries = arp_fn()
        count = len(entries)
        details = [f"{e.ip} -> {e.mac} ({e.interface})" for e in entries]
        return CheckStatus(
            module="arp",
            status="pass",
            summary=f"ARP table contains {count} entries",
            details=details,
        )
    except Exception as e:
        return CheckStatus(
            module="arp",
            status="error",
            summary=str(e),
        )


def _check_tls(**kwargs: Any) -> CheckStatus:
    """Verify TLS certs on default sites."""
    try:
        tls_fn = kwargs.get("_tls_fn")
        if tls_fn is None:
            from netglance.modules.tls import check_multiple

            tls_fn = check_multiple

        results = tls_fn()
        details: list[str] = []
        any_intercepted = False
        any_untrusted = False
        for r in results:
            detail = f"{r.host}: "
            if r.is_intercepted:
                detail += "INTERCEPTED"
                any_intercepted = True
            elif r.is_trusted:
                detail += "trusted"
            else:
                detail += "untrusted"
                any_untrusted = True
            if r.details:
                detail += f" - {r.details}"
            details.append(detail)

        if any_intercepted:
            return CheckStatus(
                module="tls",
                status="fail",
                summary="TLS interception detected on one or more hosts",
                details=details,
            )
        elif any_untrusted:
            return CheckStatus(
                module="tls",
                status="warn",
                summary="Some TLS certificates are untrusted",
                details=details,
            )
        else:
            return CheckStatus(
                module="tls",
                status="pass",
                summary=f"All {len(results)} TLS certificates trusted",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="tls",
            status="error",
            summary=str(e),
        )


def _check_http(**kwargs: Any) -> CheckStatus:
    """Check for proxy detection."""
    try:
        http_fn = kwargs.get("_http_fn")
        if http_fn is None:
            from netglance.modules.http import check_for_proxies

            http_fn = check_for_proxies

        results = http_fn()
        details: list[str] = []
        any_proxy = False
        for r in results:
            if r.proxy_detected:
                any_proxy = True
                details.append(f"{r.url}: proxy detected ({', '.join(r.suspicious_headers.keys())})")
            else:
                details.append(f"{r.url}: no proxy detected")

        if any_proxy:
            return CheckStatus(
                module="http",
                status="warn",
                summary="HTTP proxy detected",
                details=details,
            )
        else:
            return CheckStatus(
                module="http",
                status="pass",
                summary="No HTTP proxy detected",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="http",
            status="error",
            summary=str(e),
        )


def _check_wifi(**kwargs: Any) -> CheckStatus:
    """Report current WiFi connection info."""
    try:
        wifi_fn = kwargs.get("_wifi_fn")
        if wifi_fn is None:
            from netglance.modules.wifi import current_connection

            wifi_fn = current_connection

        conn = wifi_fn()
        if conn is None:
            return CheckStatus(
                module="wifi",
                status="warn",
                summary="Not connected to WiFi",
            )
        details = [
            f"SSID: {conn.ssid}",
            f"BSSID: {conn.bssid}",
            f"Channel: {conn.channel} ({conn.band})",
            f"Signal: {conn.signal_dbm} dBm",
            f"Security: {conn.security}",
        ]
        return CheckStatus(
            module="wifi",
            status="pass",
            summary=f"Connected to {conn.ssid} ({conn.signal_dbm} dBm)",
            details=details,
        )
    except RuntimeError:
        return CheckStatus(
            module="wifi",
            status="skip",
            summary="WiFi check not available on this platform",
        )
    except Exception as e:
        return CheckStatus(
            module="wifi",
            status="error",
            summary=str(e),
        )


def _get_store(kwargs: dict[str, Any]) -> "Store":
    """Get or create a Store from kwargs."""
    store = kwargs.get("_store")
    if store is None:
        from netglance.store.db import Store as _Store

        store = _Store()
        store.init_db()
    return store  # type: ignore[return-value]


def _check_speed(**kwargs: Any) -> CheckStatus:
    """Check recent speed test results from db.

    Pass if recent result exists and download >= 25 Mbps.
    Warn if download < 25 Mbps. Fail if download < 10 Mbps.
    Skip if no recent results.
    """
    try:
        store = _get_store(kwargs)
        results = store.get_results("speed", limit=1)
        if not results:
            return CheckStatus(
                module="speed",
                status="skip",
                summary="No speed test results found",
            )
        latest = results[0]
        download_mbps = latest.get("download_mbps", 0.0)
        upload_mbps = latest.get("upload_mbps", 0.0)
        latency_ms = latest.get("latency_ms", 0.0)
        details = [
            f"Download: {download_mbps:.1f} Mbps",
            f"Upload: {upload_mbps:.1f} Mbps",
            f"Latency: {latency_ms:.1f} ms",
        ]
        if latest.get("server"):
            details.append(f"Server: {latest['server']}")
        if download_mbps < 10.0:
            return CheckStatus(
                module="speed",
                status="fail",
                summary=f"Download speed critically low: {download_mbps:.1f} Mbps",
                details=details,
            )
        elif download_mbps < 25.0:
            return CheckStatus(
                module="speed",
                status="warn",
                summary=f"Download speed below threshold: {download_mbps:.1f} Mbps",
                details=details,
            )
        else:
            return CheckStatus(
                module="speed",
                status="pass",
                summary=f"Download {download_mbps:.1f} Mbps, Upload {upload_mbps:.1f} Mbps",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="speed",
            status="error",
            summary=str(e),
        )


def _check_uptime(**kwargs: Any) -> CheckStatus:
    """Check uptime monitoring status from db.

    Pass if recent uptime data shows >= 99% uptime.
    Warn if 95-99%. Fail if < 95%. Skip if no data.
    """
    try:
        store = _get_store(kwargs)
        results = store.get_results("uptime", limit=1)
        if not results:
            return CheckStatus(
                module="uptime",
                status="skip",
                summary="No uptime data found",
            )
        latest = results[0]
        uptime_pct = latest.get("uptime_pct", 100.0)
        host = latest.get("host", "unknown")
        total_checks = latest.get("total_checks", 0)
        details = [
            f"Host: {host}",
            f"Uptime: {uptime_pct:.2f}%",
            f"Total checks: {total_checks}",
        ]
        if latest.get("avg_latency_ms") is not None:
            details.append(f"Avg latency: {latest['avg_latency_ms']:.1f} ms")
        if uptime_pct < 95.0:
            return CheckStatus(
                module="uptime",
                status="fail",
                summary=f"Uptime critically low: {uptime_pct:.2f}%",
                details=details,
            )
        elif uptime_pct < 99.0:
            return CheckStatus(
                module="uptime",
                status="warn",
                summary=f"Uptime below target: {uptime_pct:.2f}%",
                details=details,
            )
        else:
            return CheckStatus(
                module="uptime",
                status="pass",
                summary=f"Uptime {uptime_pct:.2f}% for {host}",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="uptime",
            status="error",
            summary=str(e),
        )


def _check_vpn(**kwargs: Any) -> CheckStatus:
    """Check recent VPN leak detection results from db.

    Pass if no leaks found. Fail if DNS or IPv6 leak detected.
    Skip if no VPN data.
    """
    try:
        store = _get_store(kwargs)
        results = store.get_results("vpn", limit=1)
        if not results:
            return CheckStatus(
                module="vpn",
                status="skip",
                summary="No VPN leak detection data found",
            )
        latest = results[0]
        dns_leak = latest.get("dns_leak", False)
        ipv6_leak = latest.get("ipv6_leak", False)
        vpn_detected = latest.get("vpn_detected", False)
        details = []
        if vpn_detected:
            iface = latest.get("vpn_interface") or "unknown"
            details.append(f"VPN interface: {iface}")
        if dns_leak:
            resolvers = latest.get("dns_leak_resolvers", [])
            details.append(f"DNS leak via: {', '.join(resolvers)}" if resolvers else "DNS leak detected")
        if ipv6_leak:
            addrs = latest.get("ipv6_addresses", [])
            details.append(f"IPv6 leak: {', '.join(addrs)}" if addrs else "IPv6 leak detected")
        if not details:
            details.append("No leaks detected")
        if dns_leak or ipv6_leak:
            leak_types = []
            if dns_leak:
                leak_types.append("DNS")
            if ipv6_leak:
                leak_types.append("IPv6")
            return CheckStatus(
                module="vpn",
                status="fail",
                summary=f"VPN leak detected: {', '.join(leak_types)}",
                details=details,
            )
        else:
            return CheckStatus(
                module="vpn",
                status="pass",
                summary="No VPN leaks detected",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="vpn",
            status="error",
            summary=str(e),
        )


def _check_dhcp(**kwargs: Any) -> CheckStatus:
    """Check DHCP monitoring for rogue servers from db.

    Pass if no alerts. Warn if rogue server detected.
    Skip if no DHCP data.
    """
    try:
        store = _get_store(kwargs)
        results = store.get_results("dhcp", limit=10)
        if not results:
            return CheckStatus(
                module="dhcp",
                status="skip",
                summary="No DHCP monitoring data found",
            )
        rogue_alerts = [r for r in results if r.get("alert_type") == "rogue_server"]
        all_alerts = [r for r in results if "alert_type" in r]
        details = []
        for alert in all_alerts[:5]:
            desc = alert.get("description", "")
            server_ip = alert.get("server_ip", "")
            if server_ip:
                details.append(f"{alert.get('alert_type', 'alert')}: {desc} (server: {server_ip})")
            else:
                details.append(f"{alert.get('alert_type', 'alert')}: {desc}")
        if not details:
            details.append("No DHCP alerts")
        if rogue_alerts:
            return CheckStatus(
                module="dhcp",
                status="warn",
                summary=f"Rogue DHCP server detected ({len(rogue_alerts)} alert(s))",
                details=details,
            )
        else:
            return CheckStatus(
                module="dhcp",
                status="pass",
                summary="No rogue DHCP servers detected",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="dhcp",
            status="error",
            summary=str(e),
        )


def _check_ipv6(**kwargs: Any) -> CheckStatus:
    """Check IPv6 audit results from db.

    Pass if privacy extensions enabled. Warn if EUI-64 exposed.
    Skip if no IPv6 data.
    """
    try:
        store = _get_store(kwargs)
        results = store.get_results("ipv6", limit=1)
        if not results:
            return CheckStatus(
                module="ipv6",
                status="skip",
                summary="No IPv6 audit data found",
            )
        latest = results[0]
        privacy_extensions = latest.get("privacy_extensions", False)
        eui64_exposed = latest.get("eui64_exposed", False)
        dual_stack = latest.get("dual_stack", False)
        details = [
            f"Dual stack: {'Yes' if dual_stack else 'No'}",
            f"Privacy extensions: {'Enabled' if privacy_extensions else 'Disabled'}",
            f"EUI-64 exposed: {'Yes' if eui64_exposed else 'No'}",
        ]
        local_addresses = latest.get("local_addresses", [])
        if local_addresses:
            details.append(f"Local IPv6 addresses: {len(local_addresses)}")
        if eui64_exposed:
            return CheckStatus(
                module="ipv6",
                status="warn",
                summary="EUI-64 MAC address exposed in IPv6 address",
                details=details,
            )
        elif privacy_extensions:
            return CheckStatus(
                module="ipv6",
                status="pass",
                summary="IPv6 privacy extensions enabled",
                details=details,
            )
        else:
            return CheckStatus(
                module="ipv6",
                status="pass",
                summary="IPv6 audit complete",
                details=details,
            )
    except Exception as e:
        return CheckStatus(
            module="ipv6",
            status="error",
            summary=str(e),
        )


# ---------------------------------------------------------------------------
# Registry mapping module name -> check function
# ---------------------------------------------------------------------------

MODULE_CHECKS: dict[str, Callable[..., CheckStatus]] = {
    "discover": _check_discover,
    "ping": _check_ping,
    "dns": _check_dns,
    "arp": _check_arp,
    "tls": _check_tls,
    "http": _check_http,
    "wifi": _check_wifi,
    "speed": _check_speed,
    "uptime": _check_uptime,
    "vpn": _check_vpn,
    "dhcp": _check_dhcp,
    "ipv6": _check_ipv6,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _worst_status(checks: list[CheckStatus]) -> str:
    """Return the worst status across all checks, excluding 'skip'."""
    worst = "pass"
    worst_order = STATUS_ORDER["pass"]
    for check in checks:
        order = STATUS_ORDER.get(check.status, 0)
        if order > worst_order:
            worst = check.status
            worst_order = order
    return worst


def generate_report(
    modules: list[str] | None = None,
    subnet: str = "192.168.1.0/24",
    *,
    _checks: dict[str, Callable[..., CheckStatus]] | None = None,
    _store: "Store | None" = None,
) -> HealthReport:
    """Run specified (or all) module checks and aggregate into a HealthReport.

    Parameters
    ----------
    modules:
        List of module names to check. If ``None``, all registered checks are run.
    subnet:
        Network subnet passed to the discover check.
    _checks:
        Optional dict of module name -> check function, for injecting mock check
        functions during testing. When provided, these replace the real check
        functions entirely.
    _store:
        Optional Store instance passed through to check functions that query the db.
    """
    check_registry = _checks if _checks is not None else MODULE_CHECKS
    target_modules = modules if modules is not None else list(check_registry.keys())

    results: list[CheckStatus] = []
    for mod_name in target_modules:
        check_fn = check_registry.get(mod_name)
        if check_fn is None:
            results.append(
                CheckStatus(
                    module=mod_name,
                    status="error",
                    summary=f"Unknown module: {mod_name}",
                )
            )
            continue

        if mod_name == "discover":
            result = check_fn(subnet=subnet, _store=_store)
        else:
            result = check_fn(_store=_store)
        results.append(result)

    overall = _worst_status(results)

    return HealthReport(
        timestamp=datetime.now(),
        checks=results,
        overall_status=overall,
    )


def format_report_markdown(report: HealthReport) -> str:
    """Render a HealthReport as a markdown string."""
    lines: list[str] = []
    lines.append("# Network Health Report")
    lines.append("")
    lines.append(f"**Timestamp:** {report.timestamp.isoformat()}")
    lines.append(f"**Overall Status:** {report.overall_status.upper()}")
    lines.append("")

    for check in report.checks:
        status_icon = {
            "pass": "OK",
            "warn": "WARNING",
            "fail": "FAIL",
            "error": "ERROR",
            "skip": "SKIP",
        }.get(check.status, check.status.upper())

        lines.append(f"## {check.module} [{status_icon}]")
        lines.append("")
        lines.append(f"**Summary:** {check.summary}")
        lines.append("")
        if check.details:
            for detail in check.details:
                lines.append(f"- {detail}")
            lines.append("")

    return "\n".join(lines)


def report_to_dict(report: HealthReport) -> dict[str, Any]:
    """Convert a HealthReport to a JSON-serialisable dict."""
    return {
        "timestamp": report.timestamp.isoformat(),
        "overall_status": report.overall_status,
        "checks": [
            {
                "module": check.module,
                "status": check.status,
                "summary": check.summary,
                "details": check.details,
            }
            for check in report.checks
        ],
    }


# ---------------------------------------------------------------------------
# SVG sparkline and HTML report generation
# ---------------------------------------------------------------------------

_HTML_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "pass": ("#2d6a4f", "#d8f3dc"),
    "warn": ("#7d5a00", "#fff3cd"),
    "fail": ("#9b1a1a", "#ffe0e0"),
    "error": ("#9b1a1a", "#ffe0e0"),
    "skip": ("#555555", "#f0f0f0"),
}

_HTML_STATUS_ICONS: dict[str, str] = {
    "pass": "&#x2714;",   # ✔
    "warn": "&#x26a0;",   # ⚠
    "fail": "&#x2718;",   # ✘
    "error": "&#x2718;",  # ✘
    "skip": "&#x2014;",   # —
}


def _svg_sparkline(values: list[float], width: int = 200, height: int = 30) -> str:
    """Generate an inline SVG sparkline from values.

    Returns an <svg> element string with a polyline path.
    """
    if not values:
        return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"></svg>'

    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val

    n = len(values)
    padding = 2

    points: list[str] = []
    for i, v in enumerate(values):
        x = padding + (i / max(n - 1, 1)) * (width - 2 * padding)
        if val_range == 0:
            y = height / 2
        else:
            # Flip y: higher values should be higher on the chart
            y = padding + (1.0 - (v - min_val) / val_range) * (height - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    points_str = " ".join(points)
    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{points_str}" fill="none" stroke="#3a86ff" stroke-width="1.5"/>'
        f"</svg>"
    )


def generate_html_report(
    report: HealthReport,
    metric_sparklines: dict[str, str] | None = None,
    alert_log: list[dict] | None = None,
) -> str:
    """Generate a standalone HTML report.

    Args:
        report: HealthReport from generate_report().
        metric_sparklines: Optional dict of metric_name -> SVG sparkline string.
        alert_log: Optional list of recent alert log entries.

    Returns:
        Complete HTML string with inline CSS, no external dependencies.
    """
    overall = report.overall_status
    banner_fg, banner_bg = _HTML_STATUS_COLORS.get(overall, ("#333", "#eee"))
    overall_icon = _HTML_STATUS_ICONS.get(overall, "?")

    # Build per-module rows
    rows_html = []
    for check in report.checks:
        fg, bg = _HTML_STATUS_COLORS.get(check.status, ("#333", "#eee"))
        icon = _HTML_STATUS_ICONS.get(check.status, "?")
        module_label = escape(check.module)
        summary_label = escape(check.summary)
        status_label = escape(check.status.upper())

        details_html = ""
        if check.details:
            detail_items = "".join(f"<li>{escape(d)}</li>" for d in check.details)
            details_html = f"<ul style='margin:4px 0 0 0;padding-left:18px;font-size:12px;color:#555;'>{detail_items}</ul>"

        rows_html.append(f"""
        <tr>
          <td style="padding:8px 12px;font-weight:bold;white-space:nowrap;">{module_label}</td>
          <td style="padding:8px 12px;">
            <span style="background:{bg};color:{fg};padding:2px 8px;border-radius:3px;font-size:12px;font-weight:bold;">
              {icon} {status_label}
            </span>
          </td>
          <td style="padding:8px 12px;">{summary_label}{details_html}</td>
        </tr>""")

    rows_str = "\n".join(rows_html)

    # Build sparklines section
    sparklines_html = ""
    if metric_sparklines:
        spark_items = []
        for metric_name, svg_str in sorted(metric_sparklines.items()):
            spark_items.append(
                f"""<div style="margin-bottom:12px;">
                  <div style="font-size:12px;color:#555;margin-bottom:2px;">{escape(metric_name)}</div>
                  {svg_str}
                </div>"""
            )
        sparklines_html = f"""
        <h2 style="font-size:16px;color:#333;margin:24px 0 12px;">Metric Trends</h2>
        <div style="display:flex;flex-wrap:wrap;gap:16px;">
          {"".join(spark_items)}
        </div>"""

    # Build alert log section
    alerts_html = ""
    if alert_log:
        alert_rows = []
        for entry in alert_log:
            ts = escape(str(entry.get("ts", "")))
            metric = escape(str(entry.get("metric", "")))
            value = escape(str(entry.get("value", "")))
            threshold = escape(str(entry.get("threshold", "")))
            message = escape(str(entry.get("message", "")))
            ack = entry.get("acknowledged", 0)
            ack_label = "Yes" if ack else "No"
            alert_rows.append(
                f"<tr>"
                f"<td style='padding:6px 10px;font-size:12px;color:#555;'>{ts}</td>"
                f"<td style='padding:6px 10px;font-size:12px;'>{metric}</td>"
                f"<td style='padding:6px 10px;font-size:12px;'>{value}</td>"
                f"<td style='padding:6px 10px;font-size:12px;'>{threshold}</td>"
                f"<td style='padding:6px 10px;font-size:12px;'>{message}</td>"
                f"<td style='padding:6px 10px;font-size:12px;color:#888;'>{ack_label}</td>"
                f"</tr>"
            )
        alert_rows_str = "\n".join(alert_rows)
        alerts_html = f"""
        <h2 style="font-size:16px;color:#333;margin:24px 0 12px;">Recent Alerts</h2>
        <table style="width:100%;border-collapse:collapse;font-family:sans-serif;">
          <thead>
            <tr style="background:#f5f5f5;">
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Time</th>
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Metric</th>
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Value</th>
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Threshold</th>
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Message</th>
              <th style="padding:6px 10px;text-align:left;font-size:12px;color:#555;">Ack</th>
            </tr>
          </thead>
          <tbody>
            {alert_rows_str}
          </tbody>
        </table>"""

    timestamp_str = escape(report.timestamp.isoformat())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Network Health Report</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 20px; background: #f9f9f9; color: #222; }}
    .container {{ max-width: 900px; margin: 0 auto; background: #fff; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); padding: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    th, td {{ border-bottom: 1px solid #eee; }}
    .footer {{ margin-top: 24px; font-size: 11px; color: #aaa; text-align: right; }}
  </style>
</head>
<body>
  <div class="container">
    <div style="background:{banner_bg};color:{banner_fg};padding:14px 20px;border-radius:4px;margin-bottom:20px;">
      <h1 style="margin:0;font-size:20px;">
        {overall_icon} Network Health Report &mdash; {escape(overall.upper())}
      </h1>
    </div>

    <p style="font-size:13px;color:#666;margin:0 0 16px;">
      <strong>Generated:</strong> {timestamp_str}
    </p>

    <h2 style="font-size:16px;color:#333;margin:0 0 12px;">Module Summary</h2>
    <table>
      <thead>
        <tr style="background:#f5f5f5;">
          <th style="padding:8px 12px;text-align:left;font-size:13px;color:#555;">Module</th>
          <th style="padding:8px 12px;text-align:left;font-size:13px;color:#555;">Status</th>
          <th style="padding:8px 12px;text-align:left;font-size:13px;color:#555;">Summary</th>
        </tr>
      </thead>
      <tbody>
        {rows_str}
      </tbody>
    </table>

    {sparklines_html}
    {alerts_html}

    <div class="footer">Generated by netglance</div>
  </div>
</body>
</html>"""

    return html
