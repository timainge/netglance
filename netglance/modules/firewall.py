"""Firewall auditing: egress and ingress port reachability checks."""

from __future__ import annotations

import socket
import time

from netglance.store.models import FirewallAuditReport, FirewallTestResult

COMMON_EGRESS_PORTS = [22, 25, 53, 80, 443, 587, 993, 8080, 8443]

# Prevent pytest from collecting these functions as tests (they start with "test_" by spec)
__test__ = False


def _default_connect(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    """TCP connect probe. Returns (connected, latency_ms)."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = (time.monotonic() - start) * 1000
            return True, latency_ms
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False, None


def test_egress_port(
    port: int,
    protocol: str = "tcp",
    target: str = "portquiz.net",
    timeout: float = 5.0,
    *,
    _connect_fn=None,
) -> FirewallTestResult:
    """Test if an outbound port is allowed or blocked.

    _connect_fn(host, port, timeout) returns (connected: bool, latency_ms: float | None).
    Default uses socket.create_connection for TCP.

    Returns FirewallTestResult with direction="egress",
    status="open" if connected, "blocked" if connection refused/timed out.
    """
    connect_fn = _connect_fn or _default_connect
    connected, latency_ms = connect_fn(target, port, timeout)
    return FirewallTestResult(
        direction="egress",
        protocol=protocol,
        port=port,
        status="open" if connected else "blocked",
        target=target,
        latency_ms=latency_ms,
    )


def test_egress_common(
    *,
    _connect_fn=None,
) -> list[FirewallTestResult]:
    """Test common egress ports: 22, 25, 53, 80, 443, 587, 993, 8080, 8443.

    Calls test_egress_port for each.
    """
    return [
        test_egress_port(port, _connect_fn=_connect_fn)
        for port in COMMON_EGRESS_PORTS
    ]


def test_ingress_port(
    port: int,
    protocol: str = "tcp",
    *,
    _external_fn=None,
) -> FirewallTestResult:
    """Test if an inbound port is reachable from outside.

    _external_fn(port, protocol) returns (reachable: bool, latency_ms: float | None).
    This requires an external service to probe back. If no external function is
    provided, returns status="unknown" since we cannot self-probe from the outside.

    Returns FirewallTestResult with direction="ingress".
    """
    if _external_fn is None:
        return FirewallTestResult(
            direction="ingress",
            protocol=protocol,
            port=port,
            status="unknown",
        )

    reachable, latency_ms = _external_fn(port, protocol)
    return FirewallTestResult(
        direction="ingress",
        protocol=protocol,
        port=port,
        status="open" if reachable else "blocked",
        latency_ms=latency_ms,
    )


def _generate_recommendations(
    egress_results: list[FirewallTestResult],
    ingress_results: list[FirewallTestResult],
) -> list[str]:
    """Generate actionable recommendations from audit results."""
    recommendations: list[str] = []

    open_egress = {r.port for r in egress_results if r.status == "open"}
    blocked_egress = {r.port for r in egress_results if r.status == "blocked"}
    open_ingress = {r.port for r in ingress_results if r.status == "open"}

    if 25 in open_egress:
        recommendations.append(
            "Consider blocking outbound SMTP (port 25) to prevent spam relay"
        )

    if len(blocked_egress) > len(open_egress) and len(egress_results) > 0:
        recommendations.append(
            "Your network has strict egress filtering"
        )

    for port in sorted(open_ingress):
        recommendations.append(
            f"Inbound port {port} is accessible from the internet"
        )

    return recommendations


def run_firewall_audit(
    *,
    _connect_fn=None,
    _external_fn=None,
) -> FirewallAuditReport:
    """Full firewall assessment. Main entry point.

    Runs egress common ports test, optionally runs ingress tests.
    Generates recommendations based on results.
    """
    egress_results = test_egress_common(_connect_fn=_connect_fn)
    ingress_results: list[FirewallTestResult] = []

    blocked_egress_ports = [r.port for r in egress_results if r.status == "blocked"]
    open_ingress_ports = [r.port for r in ingress_results if r.status == "open"]
    recommendations = _generate_recommendations(egress_results, ingress_results)

    return FirewallAuditReport(
        egress_results=egress_results,
        ingress_results=ingress_results,
        blocked_egress_ports=blocked_egress_ports,
        open_ingress_ports=open_ingress_ports,
        recommendations=recommendations,
    )
