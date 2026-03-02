"""Tests for reports-v2 enhancements:
- New check functions (_check_speed, _check_uptime, _check_vpn, _check_dhcp, _check_ipv6)
- SVG sparkline generation
- HTML report generation
- CLI --html, --include-trending, --include-alerts flags
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.report import (
    MODULE_CHECKS,
    CheckStatus,
    HealthReport,
    _check_dhcp,
    _check_ipv6,
    _check_speed,
    _check_uptime,
    _check_vpn,
    _svg_sparkline,
    generate_html_report,
    generate_report,
)
from netglance.store.db import Store

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Store:
    """Return an initialised in-memory Store backed by a tmp file."""
    s = Store(tmp_path / "test.db")
    s.init_db()
    return s


def _make_check_fn(module: str, status: str = "pass", summary: str = "OK"):
    def _check(**kwargs):
        return CheckStatus(module=module, status=status, summary=summary)

    return _check


# ---------------------------------------------------------------------------
# _check_speed
# ---------------------------------------------------------------------------


class TestCheckSpeed:
    def test_skip_when_no_data(self, store: Store):
        result = _check_speed(_store=store)
        assert result.status == "skip"
        assert "No speed test" in result.summary

    def test_pass_when_high_download(self, store: Store):
        store.save_result("speed", {"download_mbps": 100.0, "upload_mbps": 50.0, "latency_ms": 10.0})
        result = _check_speed(_store=store)
        assert result.status == "pass"
        assert "100.0 Mbps" in result.summary

    def test_warn_when_download_between_10_and_25(self, store: Store):
        store.save_result("speed", {"download_mbps": 20.0, "upload_mbps": 10.0, "latency_ms": 25.0})
        result = _check_speed(_store=store)
        assert result.status == "warn"
        assert "below threshold" in result.summary

    def test_fail_when_download_below_10(self, store: Store):
        store.save_result("speed", {"download_mbps": 5.0, "upload_mbps": 2.0, "latency_ms": 100.0})
        result = _check_speed(_store=store)
        assert result.status == "fail"
        assert "critically low" in result.summary

    def test_boundary_at_25_is_pass(self, store: Store):
        store.save_result("speed", {"download_mbps": 25.0, "upload_mbps": 10.0, "latency_ms": 20.0})
        result = _check_speed(_store=store)
        assert result.status == "pass"

    def test_boundary_at_10_is_warn(self, store: Store):
        store.save_result("speed", {"download_mbps": 10.0, "upload_mbps": 5.0, "latency_ms": 50.0})
        result = _check_speed(_store=store)
        assert result.status == "warn"

    def test_details_include_upload_and_latency(self, store: Store):
        store.save_result("speed", {"download_mbps": 50.0, "upload_mbps": 20.0, "latency_ms": 15.0})
        result = _check_speed(_store=store)
        assert any("Upload" in d for d in result.details)
        assert any("Latency" in d for d in result.details)

    def test_details_include_server_if_present(self, store: Store):
        store.save_result(
            "speed",
            {"download_mbps": 50.0, "upload_mbps": 20.0, "latency_ms": 15.0, "server": "speedtest.example.com"},
        )
        result = _check_speed(_store=store)
        assert any("Server" in d for d in result.details)

    def test_uses_most_recent_result(self, store: Store):
        store.save_result("speed", {"download_mbps": 5.0, "upload_mbps": 2.0, "latency_ms": 100.0})
        store.save_result("speed", {"download_mbps": 80.0, "upload_mbps": 40.0, "latency_ms": 10.0})
        result = _check_speed(_store=store)
        assert result.status == "pass"

    def test_error_on_bad_store(self):
        class BadStore:
            def get_results(self, *a, **kw):
                raise RuntimeError("DB exploded")

        result = _check_speed(_store=BadStore())
        assert result.status == "error"


# ---------------------------------------------------------------------------
# _check_uptime
# ---------------------------------------------------------------------------


class TestCheckUptime:
    def test_skip_when_no_data(self, store: Store):
        result = _check_uptime(_store=store)
        assert result.status == "skip"

    def test_pass_when_99_percent(self, store: Store):
        store.save_result("uptime", {"host": "gateway", "uptime_pct": 99.5, "total_checks": 100})
        result = _check_uptime(_store=store)
        assert result.status == "pass"
        assert "gateway" in result.summary

    def test_warn_when_95_to_99(self, store: Store):
        store.save_result("uptime", {"host": "gateway", "uptime_pct": 97.0, "total_checks": 100})
        result = _check_uptime(_store=store)
        assert result.status == "warn"
        assert "below target" in result.summary

    def test_fail_when_below_95(self, store: Store):
        store.save_result("uptime", {"host": "gateway", "uptime_pct": 90.0, "total_checks": 100})
        result = _check_uptime(_store=store)
        assert result.status == "fail"
        assert "critically low" in result.summary

    def test_boundary_at_99_is_pass(self, store: Store):
        store.save_result("uptime", {"host": "h", "uptime_pct": 99.0, "total_checks": 10})
        result = _check_uptime(_store=store)
        assert result.status == "pass"

    def test_boundary_at_95_is_warn(self, store: Store):
        store.save_result("uptime", {"host": "h", "uptime_pct": 95.0, "total_checks": 10})
        result = _check_uptime(_store=store)
        assert result.status == "warn"

    def test_details_include_latency_if_present(self, store: Store):
        store.save_result(
            "uptime",
            {"host": "h", "uptime_pct": 99.9, "total_checks": 100, "avg_latency_ms": 12.5},
        )
        result = _check_uptime(_store=store)
        assert any("latency" in d.lower() for d in result.details)


# ---------------------------------------------------------------------------
# _check_vpn
# ---------------------------------------------------------------------------


class TestCheckVpn:
    def test_skip_when_no_data(self, store: Store):
        result = _check_vpn(_store=store)
        assert result.status == "skip"

    def test_pass_when_no_leaks(self, store: Store):
        store.save_result("vpn", {"vpn_detected": True, "dns_leak": False, "ipv6_leak": False})
        result = _check_vpn(_store=store)
        assert result.status == "pass"

    def test_fail_when_dns_leak(self, store: Store):
        store.save_result(
            "vpn",
            {"vpn_detected": True, "dns_leak": True, "ipv6_leak": False, "dns_leak_resolvers": ["8.8.8.8"]},
        )
        result = _check_vpn(_store=store)
        assert result.status == "fail"
        assert "DNS" in result.summary

    def test_fail_when_ipv6_leak(self, store: Store):
        store.save_result(
            "vpn",
            {"vpn_detected": True, "dns_leak": False, "ipv6_leak": True, "ipv6_addresses": ["2001:db8::1"]},
        )
        result = _check_vpn(_store=store)
        assert result.status == "fail"
        assert "IPv6" in result.summary

    def test_fail_when_both_leaks(self, store: Store):
        store.save_result(
            "vpn",
            {"vpn_detected": True, "dns_leak": True, "ipv6_leak": True},
        )
        result = _check_vpn(_store=store)
        assert result.status == "fail"
        assert "DNS" in result.summary and "IPv6" in result.summary

    def test_details_include_vpn_interface(self, store: Store):
        store.save_result(
            "vpn",
            {"vpn_detected": True, "vpn_interface": "tun0", "dns_leak": False, "ipv6_leak": False},
        )
        result = _check_vpn(_store=store)
        assert any("tun0" in d for d in result.details)


# ---------------------------------------------------------------------------
# _check_dhcp
# ---------------------------------------------------------------------------


class TestCheckDhcp:
    def test_skip_when_no_data(self, store: Store):
        result = _check_dhcp(_store=store)
        assert result.status == "skip"

    def test_pass_when_no_rogue_alerts(self, store: Store):
        store.save_result("dhcp", {"event_type": "discover", "client_mac": "aa:bb:cc:dd:ee:ff"})
        result = _check_dhcp(_store=store)
        assert result.status == "pass"

    def test_warn_when_rogue_server(self, store: Store):
        store.save_result(
            "dhcp",
            {
                "alert_type": "rogue_server",
                "severity": "warning",
                "description": "Unknown DHCP server",
                "server_ip": "192.168.1.99",
                "server_mac": "de:ad:be:ef:00:01",
            },
        )
        result = _check_dhcp(_store=store)
        assert result.status == "warn"
        assert "Rogue" in result.summary

    def test_details_show_server_ip(self, store: Store):
        store.save_result(
            "dhcp",
            {
                "alert_type": "rogue_server",
                "severity": "warning",
                "description": "Rogue DHCP",
                "server_ip": "10.0.0.99",
                "server_mac": "de:ad:be:ef:00:01",
            },
        )
        result = _check_dhcp(_store=store)
        assert any("10.0.0.99" in d for d in result.details)

    def test_multiple_rogue_alerts_counted(self, store: Store):
        for i in range(3):
            store.save_result(
                "dhcp",
                {
                    "alert_type": "rogue_server",
                    "severity": "warning",
                    "description": f"Rogue server {i}",
                    "server_ip": f"192.168.1.{100 + i}",
                    "server_mac": "de:ad:be:ef:00:01",
                },
            )
        result = _check_dhcp(_store=store)
        assert result.status == "warn"
        assert "3" in result.summary


# ---------------------------------------------------------------------------
# _check_ipv6
# ---------------------------------------------------------------------------


class TestCheckIpv6:
    def test_skip_when_no_data(self, store: Store):
        result = _check_ipv6(_store=store)
        assert result.status == "skip"

    def test_pass_when_privacy_extensions_enabled(self, store: Store):
        store.save_result("ipv6", {"privacy_extensions": True, "eui64_exposed": False, "dual_stack": True})
        result = _check_ipv6(_store=store)
        assert result.status == "pass"
        assert "privacy extensions" in result.summary.lower()

    def test_warn_when_eui64_exposed(self, store: Store):
        store.save_result("ipv6", {"privacy_extensions": False, "eui64_exposed": True, "dual_stack": True})
        result = _check_ipv6(_store=store)
        assert result.status == "warn"
        assert "EUI-64" in result.summary

    def test_pass_when_no_eui64_and_no_privacy(self, store: Store):
        store.save_result("ipv6", {"privacy_extensions": False, "eui64_exposed": False, "dual_stack": False})
        result = _check_ipv6(_store=store)
        assert result.status == "pass"

    def test_details_show_dual_stack(self, store: Store):
        store.save_result("ipv6", {"privacy_extensions": True, "eui64_exposed": False, "dual_stack": True})
        result = _check_ipv6(_store=store)
        assert any("Dual stack" in d for d in result.details)

    def test_details_show_local_address_count(self, store: Store):
        store.save_result(
            "ipv6",
            {
                "privacy_extensions": True,
                "eui64_exposed": False,
                "dual_stack": True,
                "local_addresses": [{"addr": "2001:db8::1"}, {"addr": "fe80::1"}],
            },
        )
        result = _check_ipv6(_store=store)
        assert any("2" in d for d in result.details)


# ---------------------------------------------------------------------------
# Module registration
# ---------------------------------------------------------------------------


class TestModuleChecksRegistry:
    def test_new_checks_registered(self):
        for name in ("speed", "uptime", "vpn", "dhcp", "ipv6"):
            assert name in MODULE_CHECKS

    def test_existing_checks_still_registered(self):
        for name in ("discover", "ping", "dns", "arp", "tls", "http", "wifi"):
            assert name in MODULE_CHECKS


# ---------------------------------------------------------------------------
# generate_report with _store
# ---------------------------------------------------------------------------


class TestGenerateReportWithStore:
    def test_store_passed_to_check_fn(self, store: Store):
        received: list = []

        def _mock_check(**kwargs):
            received.append(kwargs.get("_store"))
            return CheckStatus(module="test", status="pass", summary="OK")

        generate_report(_checks={"test": _mock_check}, _store=store)
        assert received[0] is store

    def test_store_passed_to_discover(self, store: Store):
        received: list = []

        def _mock_discover(subnet="192.168.1.0/24", **kwargs):
            received.append(kwargs.get("_store"))
            return CheckStatus(module="discover", status="pass", summary="OK")

        generate_report(_checks={"discover": _mock_discover}, _store=store)
        assert received[0] is store


# ---------------------------------------------------------------------------
# _svg_sparkline
# ---------------------------------------------------------------------------


class TestSvgSparkline:
    def test_returns_svg_element(self):
        svg = _svg_sparkline([1.0, 2.0, 3.0])
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_empty_values_returns_empty_svg(self):
        svg = _svg_sparkline([])
        assert "<svg" in svg

    def test_contains_polyline(self):
        svg = _svg_sparkline([1.0, 2.0, 3.0, 2.0, 1.0])
        assert "polyline" in svg

    def test_width_and_height_in_svg(self):
        svg = _svg_sparkline([1.0, 2.0], width=150, height=25)
        assert 'width="150"' in svg
        assert 'height="25"' in svg

    def test_single_value(self):
        svg = _svg_sparkline([42.0])
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_all_equal_values(self):
        svg = _svg_sparkline([5.0, 5.0, 5.0, 5.0])
        assert "polyline" in svg

    def test_points_attribute_present(self):
        svg = _svg_sparkline([1.0, 2.0, 3.0])
        assert 'points="' in svg


# ---------------------------------------------------------------------------
# generate_html_report
# ---------------------------------------------------------------------------


class TestGenerateHtmlReport:
    def _make_report(self, status: str = "pass") -> HealthReport:
        checks = [
            CheckStatus(module="ping", status=status, summary="Test summary", details=["Detail 1"]),
            CheckStatus(module="dns", status="pass", summary="DNS OK"),
        ]
        return HealthReport(
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            checks=checks,
            overall_status=status,
        )

    def test_returns_html_string(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html

    def test_contains_module_names(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "ping" in html
        assert "dns" in html

    def test_contains_overall_status(self):
        report = self._make_report("fail")
        html = generate_html_report(report)
        assert "FAIL" in html

    def test_contains_timestamp(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "2024-01-15" in html

    def test_contains_summaries(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "Test summary" in html
        assert "DNS OK" in html

    def test_contains_details(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "Detail 1" in html

    def test_green_banner_for_pass(self):
        report = self._make_report("pass")
        html = generate_html_report(report)
        # Pass color should be in the banner
        assert "#2d6a4f" in html or "#d8f3dc" in html

    def test_red_banner_for_fail(self):
        report = self._make_report("fail")
        html = generate_html_report(report)
        assert "#9b1a1a" in html or "#ffe0e0" in html

    def test_inline_css_no_external_stylesheets(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "<link" not in html
        assert 'href="http' not in html

    def test_with_sparklines(self):
        report = self._make_report()
        sparklines = {"speed.download_mbps": _svg_sparkline([50.0, 60.0, 55.0, 70.0])}
        html = generate_html_report(report, metric_sparklines=sparklines)
        assert "speed.download_mbps" in html
        assert "Metric Trends" in html

    def test_with_alert_log(self):
        report = self._make_report()
        alerts = [
            {
                "id": 1,
                "ts": "2024-01-15T10:00:00",
                "rule_id": 1,
                "metric": "ping.latency_ms",
                "value": 250.0,
                "threshold": 100.0,
                "message": "High latency",
                "acknowledged": 0,
            }
        ]
        html = generate_html_report(report, alert_log=alerts)
        assert "Recent Alerts" in html
        assert "ping.latency_ms" in html
        assert "High latency" in html

    def test_without_sparklines_no_trends_section(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "Metric Trends" not in html

    def test_without_alerts_no_alerts_section(self):
        report = self._make_report()
        html = generate_html_report(report)
        assert "Recent Alerts" not in html

    def test_escapes_special_html_chars(self):
        checks = [
            CheckStatus(
                module="test",
                status="warn",
                summary='Summary with <script>alert("xss")</script>',
                details=['Detail with & ampersand'],
            )
        ]
        report = HealthReport(timestamp=datetime.now(), checks=checks, overall_status="warn")
        html = generate_html_report(report)
        assert "<script>" not in html
        assert "&amp;" in html or "&lt;" in html


# ---------------------------------------------------------------------------
# CLI --html flag
# ---------------------------------------------------------------------------


class TestReportCliHtml:
    def test_html_flag_produces_html(self):
        checks = {
            "ping": _make_check_fn("ping", "pass", "All OK"),
        }
        result = runner.invoke(app, ["report", "--html"], obj={"_checks": checks})
        assert result.exit_code == 0
        assert "<!DOCTYPE html>" in result.output

    def test_html_contains_module_names(self):
        checks = {
            "ping": _make_check_fn("ping", "pass", "All OK"),
            "dns": _make_check_fn("dns", "pass", "DNS OK"),
        }
        result = runner.invoke(app, ["report", "--html"], obj={"_checks": checks})
        assert result.exit_code == 0
        assert "ping" in result.output
        assert "dns" in result.output

    def test_html_output_to_file(self, tmp_path: Path):
        checks = {"ping": _make_check_fn("ping", "pass", "All OK")}
        out_file = tmp_path / "report.html"
        result = runner.invoke(
            app,
            ["report", "--html", "--html-output", str(out_file)],
            obj={"_checks": checks},
        )
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "<!DOCTYPE html>" in content
        assert "ping" in content

    def test_html_output_file_message(self, tmp_path: Path):
        checks = {"ping": _make_check_fn("ping", "pass", "All OK")}
        out_file = tmp_path / "report.html"
        result = runner.invoke(
            app,
            ["report", "--html", "--html-output", str(out_file)],
            obj={"_checks": checks},
        )
        assert result.exit_code == 0
        # Should print something about saving
        assert "report.html" in result.output or out_file.name in result.output

    def test_html_with_include_trending(self, store: Store, tmp_path: Path):
        store.save_metric("speed.download_mbps", 55.0)
        store.save_metric("speed.download_mbps", 60.0)
        checks = {"ping": _make_check_fn("ping", "pass", "All OK")}
        result = runner.invoke(
            app,
            ["report", "--html", "--include-trending"],
            obj={"_checks": checks, "_store": store},
        )
        assert result.exit_code == 0
        html = result.output
        assert "<!DOCTYPE html>" in html
        assert "speed.download_mbps" in html

    def test_html_with_include_alerts(self, store: Store):
        # Insert an alert log entry
        store.conn.execute(
            "INSERT INTO alert_rules (metric, condition, threshold, window_s, enabled, message) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            ("ping.latency_ms", "above", 100.0, 300, "High latency"),
        )
        store.conn.commit()
        store.conn.execute(
            "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message, acknowledged) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            ("2024-01-15T10:00:00", 1, "ping.latency_ms", 250.0, 100.0, "High latency"),
        )
        store.conn.commit()
        checks = {"ping": _make_check_fn("ping", "pass", "All OK")}
        result = runner.invoke(
            app,
            ["report", "--html", "--include-alerts"],
            obj={"_checks": checks, "_store": store},
        )
        assert result.exit_code == 0
        assert "Recent Alerts" in result.output
        assert "ping.latency_ms" in result.output

    def test_no_html_flag_produces_rich_output(self):
        checks = {"ping": _make_check_fn("ping", "pass", "All OK")}
        result = runner.invoke(app, ["report"], obj={"_checks": checks})
        assert result.exit_code == 0
        assert "<!DOCTYPE html>" not in result.output
