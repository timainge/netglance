"""Tests for Phase 2 shared types in store/models.py."""

from dataclasses import asdict
from datetime import datetime

from netglance.store.models import (
    Alert,
    DhcpAlert,
    DhcpEvent,
    ExportResult,
    FirewallAuditReport,
    FirewallTestResult,
    IPv6AuditResult,
    IPv6Neighbor,
    NetworkPerformanceResult,
    SpeedTestResult,
    UptimeRecord,
    UptimeSummary,
    VpnLeakReport,
    WolResult,
)


def test_speed_test_result_defaults():
    r = SpeedTestResult(download_mbps=100.0, upload_mbps=50.0, latency_ms=10.0)
    assert r.download_mbps == 100.0
    assert r.provider == "cloudflare"
    assert r.jitter_ms is None
    assert r.download_bytes == 0


def test_speed_test_result_full():
    r = SpeedTestResult(
        download_mbps=500.0,
        upload_mbps=200.0,
        latency_ms=5.0,
        jitter_ms=1.2,
        server="speed.cloudflare.com",
        provider="cloudflare",
        download_bytes=62_500_000,
        upload_bytes=25_000_000,
    )
    d = asdict(r)
    assert d["download_mbps"] == 500.0
    assert d["jitter_ms"] == 1.2


def test_uptime_record():
    r = UptimeRecord(host="192.168.1.1", check_time=datetime.now(), is_alive=True, latency_ms=2.5)
    assert r.is_alive
    assert r.latency_ms == 2.5


def test_uptime_summary_defaults():
    s = UptimeSummary(host="gw", period="24h", uptime_pct=99.9, total_checks=100, successful_checks=99)
    assert s.current_status == "unknown"
    assert s.outages == []
    assert s.last_seen is None


def test_network_performance_result():
    r = NetworkPerformanceResult(
        target="1.1.1.1",
        avg_latency_ms=10.0,
        jitter_ms=1.5,
        p95_latency_ms=15.0,
        p99_latency_ms=20.0,
        packet_loss_pct=0.0,
    )
    assert r.path_mtu is None
    assert r.bufferbloat_rating is None
    d = asdict(r)
    assert d["target"] == "1.1.1.1"


def test_wol_result():
    r = WolResult(mac="AA:BB:CC:DD:EE:FF")
    assert r.broadcast == "255.255.255.255"
    assert r.port == 9
    assert not r.sent


def test_dhcp_event_defaults():
    e = DhcpEvent(event_type="discover", client_mac="AA:BB:CC:DD:EE:FF")
    assert e.dns_servers == []
    assert e.lease_time is None


def test_dhcp_alert():
    a = DhcpAlert(alert_type="rogue_server", severity="critical", description="Unknown DHCP server")
    assert a.server_ip == ""
    d = asdict(a)
    assert d["alert_type"] == "rogue_server"


def test_vpn_leak_report_defaults():
    r = VpnLeakReport(vpn_detected=True, vpn_interface="utun0")
    assert not r.dns_leak
    assert r.dns_leak_resolvers == []
    assert not r.ipv6_leak


def test_vpn_leak_report_full():
    r = VpnLeakReport(
        vpn_detected=True,
        vpn_interface="utun0",
        dns_leak=True,
        dns_leak_resolvers=["8.8.8.8"],
        ipv6_leak=True,
        ipv6_addresses=["2001:db8::1"],
    )
    d = asdict(r)
    assert d["dns_leak"]
    assert len(d["dns_leak_resolvers"]) == 1


def test_ipv6_neighbor():
    n = IPv6Neighbor(ipv6_address="fe80::1", mac="AA:BB:CC:DD:EE:FF")
    assert n.address_type == ""
    assert n.interface == ""


def test_ipv6_audit_result_defaults():
    r = IPv6AuditResult()
    assert r.neighbors == []
    assert not r.privacy_extensions
    assert r.ipv6_dns_leak is None


def test_firewall_test_result():
    r = FirewallTestResult(direction="egress", protocol="tcp", port=443, status="open")
    assert r.target == ""
    assert r.latency_ms is None


def test_firewall_audit_report_defaults():
    r = FirewallAuditReport()
    assert r.egress_results == []
    assert r.recommendations == []


def test_firewall_audit_report_with_results():
    result = FirewallTestResult(direction="egress", protocol="tcp", port=80, status="open")
    report = FirewallAuditReport(
        egress_results=[result],
        blocked_egress_ports=[25],
        recommendations=["Block outbound SMTP"],
    )
    d = asdict(report)
    assert len(d["egress_results"]) == 1
    assert d["blocked_egress_ports"] == [25]


def test_export_result():
    r = ExportResult(format="json", path="/tmp/out.json", record_count=42)
    d = asdict(r)
    assert d["format"] == "json"
    assert d["record_count"] == 42


def test_alert_defaults():
    a = Alert(severity="warning", category="new_device", title="New device", message="Found 192.168.1.50")
    assert a.data == {}
    assert isinstance(a.timestamp, datetime)


def test_alert_with_data():
    a = Alert(
        severity="critical",
        category="arp_spoof",
        title="ARP spoof detected",
        message="Gateway MAC changed",
        data={"old_mac": "AA:BB:CC:DD:EE:FF", "new_mac": "11:22:33:44:55:66"},
    )
    d = asdict(a)
    assert d["data"]["old_mac"] == "AA:BB:CC:DD:EE:FF"


def test_all_models_serializable():
    """Every new model can be converted to dict for JSON storage."""
    models = [
        SpeedTestResult(download_mbps=100, upload_mbps=50, latency_ms=10),
        UptimeRecord(host="h", check_time=datetime.now(), is_alive=True),
        UptimeSummary(host="h", period="24h", uptime_pct=99, total_checks=10, successful_checks=9),
        NetworkPerformanceResult(target="t", avg_latency_ms=10, jitter_ms=1, p95_latency_ms=15, p99_latency_ms=20, packet_loss_pct=0),
        WolResult(mac="AA:BB:CC:DD:EE:FF"),
        DhcpEvent(event_type="discover", client_mac="AA:BB:CC:DD:EE:FF"),
        DhcpAlert(alert_type="rogue", severity="critical", description="bad"),
        VpnLeakReport(vpn_detected=False),
        IPv6Neighbor(ipv6_address="::1", mac="AA:BB:CC:DD:EE:FF"),
        IPv6AuditResult(),
        FirewallTestResult(direction="egress", protocol="tcp", port=80, status="open"),
        FirewallAuditReport(),
        ExportResult(format="json", path="/tmp/out.json", record_count=0),
        Alert(severity="info", category="test", title="test", message="test"),
    ]
    for model in models:
        d = asdict(model)
        assert isinstance(d, dict), f"{type(model).__name__} failed asdict"
