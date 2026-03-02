"""Tests for netglance.modules.report and the report CLI subcommand.

All module network I/O is mocked -- no real network access.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.report import (
    MODULE_CHECKS,
    CheckStatus,
    HealthReport,
    STATUS_ORDER,
    _check_arp,
    _check_discover,
    _check_dns,
    _check_http,
    _check_ping,
    _check_tls,
    _check_wifi,
    _worst_status,
    format_report_markdown,
    generate_report,
    report_to_dict,
)
from netglance.store.models import (
    ArpEntry,
    Device,
    DnsResolverResult,
    WifiNetwork,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers: mock check functions returning controlled results
# ---------------------------------------------------------------------------


def _make_check_fn(
    module: str, status: str = "pass", summary: str = "OK", details: list[str] | None = None
):
    """Return a callable that produces a known CheckStatus."""

    def _check(**kwargs):
        return CheckStatus(
            module=module,
            status=status,
            summary=summary,
            details=details or [],
        )

    return _check


def _make_discover_check_fn(
    module: str = "discover",
    status: str = "pass",
    summary: str = "OK",
    details: list[str] | None = None,
):
    """Return a callable that accepts subnet and produces a known CheckStatus."""

    def _check(subnet: str = "192.168.1.0/24", **kwargs):
        return CheckStatus(
            module=module,
            status=status,
            summary=summary,
            details=details or [],
        )

    return _check


ALL_PASS_CHECKS: dict[str, object] = {
    "discover": _make_discover_check_fn("discover", "pass", "Found 5 devices"),
    "ping": _make_check_fn("ping", "pass", "All connectivity OK"),
    "dns": _make_check_fn("dns", "pass", "DNS consistent"),
    "arp": _make_check_fn("arp", "pass", "ARP table normal"),
    "tls": _make_check_fn("tls", "pass", "All certs trusted"),
    "http": _make_check_fn("http", "pass", "No proxy detected"),
    "wifi": _make_check_fn("wifi", "pass", "Connected to MyWifi"),
}

MIXED_CHECKS: dict[str, object] = {
    "discover": _make_discover_check_fn("discover", "pass", "Found 3 devices"),
    "ping": _make_check_fn("ping", "warn", "Partial connectivity"),
    "dns": _make_check_fn("dns", "fail", "DNS hijack detected"),
    "arp": _make_check_fn("arp", "pass", "ARP OK"),
    "tls": _make_check_fn("tls", "pass", "Certs OK"),
    "http": _make_check_fn("http", "warn", "Proxy detected"),
    "wifi": _make_check_fn("wifi", "skip", "Not available on this platform"),
}

ALL_FAIL_CHECKS: dict[str, object] = {
    "discover": _make_discover_check_fn("discover", "fail", "Discovery failed"),
    "ping": _make_check_fn("ping", "fail", "All down"),
    "dns": _make_check_fn("dns", "fail", "DNS broken"),
    "arp": _make_check_fn("arp", "fail", "ARP anomaly"),
    "tls": _make_check_fn("tls", "fail", "TLS interception"),
    "http": _make_check_fn("http", "fail", "Proxy issue"),
    "wifi": _make_check_fn("wifi", "fail", "WiFi down"),
}


# ---------------------------------------------------------------------------
# Tests for generate_report
# ---------------------------------------------------------------------------


class TestGenerateReport:
    """Test the report aggregation logic."""

    def test_all_pass(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)

        assert isinstance(report, HealthReport)
        assert report.overall_status == "pass"
        assert len(report.checks) == len(ALL_PASS_CHECKS)
        for check in report.checks:
            assert check.status == "pass"

    def test_mixed_results_worst_is_fail(self):
        report = generate_report(_checks=MIXED_CHECKS)

        assert report.overall_status == "fail"
        statuses = {c.module: c.status for c in report.checks}
        assert statuses["ping"] == "warn"
        assert statuses["dns"] == "fail"
        assert statuses["wifi"] == "skip"

    def test_all_fail(self):
        report = generate_report(_checks=ALL_FAIL_CHECKS)

        assert report.overall_status == "fail"
        for check in report.checks:
            assert check.status == "fail"

    def test_error_is_worst(self):
        checks = {
            "ping": _make_check_fn("ping", "pass", "OK"),
            "dns": _make_check_fn("dns", "error", "Exception occurred"),
        }
        report = generate_report(_checks=checks)

        assert report.overall_status == "error"

    def test_skip_does_not_affect_overall(self):
        checks = {
            "ping": _make_check_fn("ping", "pass", "OK"),
            "wifi": _make_check_fn("wifi", "skip", "Not available"),
        }
        report = generate_report(_checks=checks)

        assert report.overall_status == "pass"

    def test_all_skip_results_in_pass(self):
        checks = {
            "wifi": _make_check_fn("wifi", "skip", "Skipped"),
        }
        report = generate_report(_checks=checks)

        # skip has order -1, which is less than pass (0), so worst stays at pass
        assert report.overall_status == "pass"

    def test_modules_filter(self):
        report = generate_report(modules=["ping", "dns"], _checks=ALL_PASS_CHECKS)

        assert len(report.checks) == 2
        module_names = {c.module for c in report.checks}
        assert module_names == {"ping", "dns"}

    def test_unknown_module(self):
        checks = {
            "ping": _make_check_fn("ping", "pass", "OK"),
        }
        report = generate_report(modules=["ping", "nonexistent"], _checks=checks)

        assert len(report.checks) == 2
        nonexistent = [c for c in report.checks if c.module == "nonexistent"]
        assert len(nonexistent) == 1
        assert nonexistent[0].status == "error"
        assert "Unknown module" in nonexistent[0].summary

    def test_timestamp_is_set(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)

        assert isinstance(report.timestamp, datetime)

    def test_subnet_passed_to_discover(self):
        called_with: list[str] = []

        def _discover_check(subnet: str = "192.168.1.0/24", **kwargs):
            called_with.append(subnet)
            return CheckStatus(module="discover", status="pass", summary="OK")

        checks = {"discover": _discover_check}
        generate_report(modules=["discover"], subnet="10.0.0.0/8", _checks=checks)

        assert called_with == ["10.0.0.0/8"]


# ---------------------------------------------------------------------------
# Tests for _worst_status
# ---------------------------------------------------------------------------


class TestWorstStatus:
    """Test the status severity logic."""

    def test_all_pass(self):
        checks = [
            CheckStatus(module="a", status="pass", summary=""),
            CheckStatus(module="b", status="pass", summary=""),
        ]
        assert _worst_status(checks) == "pass"

    def test_warn_beats_pass(self):
        checks = [
            CheckStatus(module="a", status="pass", summary=""),
            CheckStatus(module="b", status="warn", summary=""),
        ]
        assert _worst_status(checks) == "warn"

    def test_fail_beats_warn(self):
        checks = [
            CheckStatus(module="a", status="warn", summary=""),
            CheckStatus(module="b", status="fail", summary=""),
        ]
        assert _worst_status(checks) == "fail"

    def test_error_beats_fail(self):
        checks = [
            CheckStatus(module="a", status="fail", summary=""),
            CheckStatus(module="b", status="error", summary=""),
        ]
        assert _worst_status(checks) == "error"

    def test_skip_excluded_from_worst(self):
        checks = [
            CheckStatus(module="a", status="pass", summary=""),
            CheckStatus(module="b", status="skip", summary=""),
        ]
        assert _worst_status(checks) == "pass"

    def test_empty_list(self):
        assert _worst_status([]) == "pass"


# ---------------------------------------------------------------------------
# Tests for individual _check_* functions with injected dependencies
# ---------------------------------------------------------------------------


class TestCheckDiscover:
    """Tests for _check_discover with mocked discover_all."""

    def test_pass_with_devices(self):
        devices = [
            Device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:ff", hostname="router"),
            Device(ip="192.168.1.2", mac="11:22:33:44:55:66", hostname="laptop"),
        ]
        result = _check_discover(subnet="192.168.1.0/24", _discover_fn=lambda s: devices)

        assert result.status == "pass"
        assert "2 device" in result.summary
        assert len(result.details) == 2

    def test_pass_with_no_devices(self):
        result = _check_discover(subnet="10.0.0.0/24", _discover_fn=lambda s: [])

        assert result.status == "pass"
        assert "0 device" in result.summary

    def test_error_on_exception(self):
        def _fail(s):
            raise OSError("No permission")

        result = _check_discover(subnet="192.168.1.0/24", _discover_fn=_fail)

        assert result.status == "error"
        assert "No permission" in result.summary


class TestCheckPing:
    """Tests for _check_ping with mocked gateway and internet checks."""

    def _make_ping_result(self, host: str, alive: bool, latency: float = 10.0):
        from netglance.store.models import PingResult

        return PingResult(
            host=host,
            is_alive=alive,
            avg_latency_ms=latency if alive else None,
            min_latency_ms=latency if alive else None,
            max_latency_ms=latency if alive else None,
            packet_loss=0.0 if alive else 1.0,
        )

    def test_all_pass(self):
        gw = self._make_ping_result("192.168.1.1", True)
        internet = [
            self._make_ping_result("1.1.1.1", True),
            self._make_ping_result("8.8.8.8", True),
        ]
        result = _check_ping(_gateway_fn=lambda: gw, _internet_fn=lambda: internet)

        assert result.status == "pass"
        assert "OK" in result.summary

    def test_partial_fail_is_warn(self):
        gw = self._make_ping_result("192.168.1.1", True)
        internet = [
            self._make_ping_result("1.1.1.1", True),
            self._make_ping_result("8.8.8.8", False),
        ]
        result = _check_ping(_gateway_fn=lambda: gw, _internet_fn=lambda: internet)

        assert result.status == "warn"
        assert "Partial" in result.summary or "partial" in result.summary.lower()

    def test_all_down_is_fail(self):
        gw = self._make_ping_result("192.168.1.1", False)
        internet = [
            self._make_ping_result("1.1.1.1", False),
            self._make_ping_result("8.8.8.8", False),
        ]
        result = _check_ping(_gateway_fn=lambda: gw, _internet_fn=lambda: internet)

        assert result.status == "fail"

    def test_gateway_detection_error(self):
        internet = [self._make_ping_result("1.1.1.1", True)]

        def _gw_fail():
            raise RuntimeError("Cannot detect gateway")

        result = _check_ping(_gateway_fn=_gw_fail, _internet_fn=lambda: internet)

        # Gateway failed but internet is up -> warn
        assert result.status == "warn"
        assert any("Cannot detect gateway" in d for d in result.details)

    def test_error_on_exception(self):
        def _explode():
            raise TypeError("unexpected")

        result = _check_ping(_gateway_fn=_explode)

        assert result.status == "error"


class TestCheckDns:
    """Tests for _check_dns with mocked check_consistency."""

    def _make_dns_report(self, consistent: bool, hijack: bool):
        from netglance.modules.dns import DnsHealthReport

        return DnsHealthReport(
            resolvers_checked=3,
            consistent=consistent,
            fastest_resolver="Cloudflare (1.1.1.1)",
            dnssec_supported=False,
            potential_hijack=hijack,
            details=[
                DnsResolverResult(
                    resolver="1.1.1.1",
                    resolver_name="Cloudflare",
                    query="example.com",
                    answers=["93.184.216.34"],
                    response_time_ms=10.0,
                ),
            ],
        )

    def test_consistent_pass(self):
        report = self._make_dns_report(consistent=True, hijack=False)
        result = _check_dns(_dns_fn=lambda d: report)

        assert result.status == "pass"
        assert "consistent" in result.summary.lower()

    def test_hijack_fail(self):
        report = self._make_dns_report(consistent=False, hijack=True)
        result = _check_dns(_dns_fn=lambda d: report)

        assert result.status == "fail"
        assert "hijack" in result.summary.lower()

    def test_inconsistent_warn(self):
        report = self._make_dns_report(consistent=False, hijack=False)
        result = _check_dns(_dns_fn=lambda d: report)

        assert result.status == "warn"

    def test_error_on_exception(self):
        def _fail(d):
            raise ConnectionError("DNS unreachable")

        result = _check_dns(_dns_fn=_fail)

        assert result.status == "error"
        assert "DNS unreachable" in result.summary


class TestCheckArp:
    """Tests for _check_arp with mocked get_arp_table."""

    def test_pass_with_entries(self):
        entries = [
            ArpEntry(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:ff", interface="en0"),
            ArpEntry(ip="192.168.1.2", mac="11:22:33:44:55:66", interface="en0"),
        ]
        result = _check_arp(_arp_fn=lambda: entries)

        assert result.status == "pass"
        assert "2 entries" in result.summary

    def test_error_on_exception(self):
        def _fail():
            raise PermissionError("No access")

        result = _check_arp(_arp_fn=_fail)

        assert result.status == "error"


class TestCheckTls:
    """Tests for _check_tls with mocked check_multiple."""

    def _make_tls_result(self, host: str, trusted: bool, intercepted: bool = False):
        from netglance.modules.tls import TlsCheckResult
        from netglance.store.models import CertInfo

        return TlsCheckResult(
            host=host,
            cert=CertInfo(host=host),
            is_trusted=trusted,
            is_intercepted=intercepted,
            details=f"{'Trusted' if trusted else 'Untrusted'} CA",
        )

    def test_all_trusted_pass(self):
        results = [
            self._make_tls_result("google.com", True),
            self._make_tls_result("github.com", True),
        ]
        result = _check_tls(_tls_fn=lambda: results)

        assert result.status == "pass"
        assert "2" in result.summary and "trusted" in result.summary.lower()

    def test_intercepted_fail(self):
        results = [
            self._make_tls_result("google.com", True),
            self._make_tls_result("github.com", False, intercepted=True),
        ]
        result = _check_tls(_tls_fn=lambda: results)

        assert result.status == "fail"
        assert "interception" in result.summary.lower()

    def test_untrusted_warn(self):
        results = [
            self._make_tls_result("google.com", True),
            self._make_tls_result("github.com", False, intercepted=False),
        ]
        result = _check_tls(_tls_fn=lambda: results)

        assert result.status == "warn"

    def test_error_on_exception(self):
        def _fail():
            raise TimeoutError("Connection timed out")

        result = _check_tls(_tls_fn=_fail)

        assert result.status == "error"


class TestCheckHttp:
    """Tests for _check_http with mocked check_for_proxies."""

    def _make_http_result(self, url: str, proxy: bool):
        from netglance.modules.http import HttpProbeResult

        return HttpProbeResult(
            url=url,
            status_code=200,
            proxy_detected=proxy,
            suspicious_headers={"Via": "proxy.example.com"} if proxy else {},
        )

    def test_no_proxy_pass(self):
        results = [self._make_http_result("http://example.com", False)]
        result = _check_http(_http_fn=lambda: results)

        assert result.status == "pass"
        assert "no" in result.summary.lower() and "proxy" in result.summary.lower()

    def test_proxy_detected_warn(self):
        results = [self._make_http_result("http://example.com", True)]
        result = _check_http(_http_fn=lambda: results)

        assert result.status == "warn"
        assert "proxy" in result.summary.lower()

    def test_error_on_exception(self):
        def _fail():
            raise ConnectionError("Network unreachable")

        result = _check_http(_http_fn=_fail)

        assert result.status == "error"


class TestCheckWifi:
    """Tests for _check_wifi with mocked current_connection."""

    def test_connected_pass(self):
        conn = WifiNetwork(
            ssid="HomeNet",
            bssid="aa:bb:cc:dd:ee:ff",
            channel=6,
            band="2.4 GHz",
            signal_dbm=-55,
            security="WPA2",
        )
        result = _check_wifi(_wifi_fn=lambda: conn)

        assert result.status == "pass"
        assert "HomeNet" in result.summary

    def test_not_connected_warn(self):
        result = _check_wifi(_wifi_fn=lambda: None)

        assert result.status == "warn"
        assert "not connected" in result.summary.lower() or "Not connected" in result.summary

    def test_platform_skip(self):
        def _not_macos():
            raise RuntimeError("WiFi scanning only supported on macOS")

        result = _check_wifi(_wifi_fn=_not_macos)

        assert result.status == "skip"
        assert "not available" in result.summary.lower()

    def test_other_error(self):
        def _fail():
            raise ValueError("Unexpected error")

        result = _check_wifi(_wifi_fn=_fail)

        assert result.status == "error"


# ---------------------------------------------------------------------------
# Tests for format_report_markdown
# ---------------------------------------------------------------------------


class TestFormatReportMarkdown:
    """Test markdown report formatting."""

    def test_contains_header(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        md = format_report_markdown(report)

        assert "# Network Health Report" in md

    def test_contains_overall_status(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        md = format_report_markdown(report)

        assert "PASS" in md

    def test_contains_module_sections(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        md = format_report_markdown(report)

        for module_name in ALL_PASS_CHECKS:
            assert f"## {module_name}" in md

    def test_contains_timestamp(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        md = format_report_markdown(report)

        assert "Timestamp" in md

    def test_contains_details(self):
        checks = {
            "ping": _make_check_fn(
                "ping", "pass", "All OK", details=["Gateway UP", "Internet UP"]
            ),
        }
        report = generate_report(_checks=checks)
        md = format_report_markdown(report)

        assert "Gateway UP" in md
        assert "Internet UP" in md

    def test_mixed_statuses(self):
        report = generate_report(_checks=MIXED_CHECKS)
        md = format_report_markdown(report)

        assert "FAIL" in md  # overall should be fail
        assert "WARNING" in md
        assert "SKIP" in md


# ---------------------------------------------------------------------------
# Tests for report_to_dict (JSON output)
# ---------------------------------------------------------------------------


class TestReportToDict:
    """Test JSON serialisation of HealthReport."""

    def test_structure(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        d = report_to_dict(report)

        assert "timestamp" in d
        assert "overall_status" in d
        assert "checks" in d
        assert isinstance(d["checks"], list)

    def test_check_fields(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        d = report_to_dict(report)

        for check in d["checks"]:
            assert "module" in check
            assert "status" in check
            assert "summary" in check
            assert "details" in check

    def test_json_serializable(self):
        report = generate_report(_checks=ALL_PASS_CHECKS)
        d = report_to_dict(report)

        # Should not raise
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["overall_status"] == "pass"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestReportCli:
    """Tests for the report CLI subcommand."""

    def test_report_all_pass(self):
        result = runner.invoke(app, ["report"], obj={"_checks": ALL_PASS_CHECKS})

        assert result.exit_code == 0
        assert "Network Health Report" in result.output
        assert "PASS" in result.output

    def test_report_mixed(self):
        result = runner.invoke(app, ["report"], obj={"_checks": MIXED_CHECKS})

        assert result.exit_code == 0
        assert "FAIL" in result.output

    def test_report_modules_filter(self):
        result = runner.invoke(
            app,
            ["report", "--modules", "ping,dns"],
            obj={"_checks": ALL_PASS_CHECKS},
        )

        assert result.exit_code == 0
        # ping and dns should appear in output
        assert "ping" in result.output
        assert "dns" in result.output

    def test_report_json_output(self):
        result = runner.invoke(
            app,
            ["report", "--json"],
            obj={"_checks": ALL_PASS_CHECKS},
        )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["overall_status"] == "pass"
        assert len(parsed["checks"]) == len(ALL_PASS_CHECKS)

    def test_report_json_structure(self):
        result = runner.invoke(
            app,
            ["report", "--json"],
            obj={"_checks": MIXED_CHECKS},
        )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["overall_status"] == "fail"
        modules_in_output = {c["module"] for c in parsed["checks"]}
        assert "ping" in modules_in_output
        assert "dns" in modules_in_output

    def test_report_markdown_output(self, tmp_path):
        output_file = tmp_path / "report.md"
        result = runner.invoke(
            app,
            ["report", "--output", str(output_file)],
            obj={"_checks": ALL_PASS_CHECKS},
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Network Health Report" in content
        assert "PASS" in content

    def test_report_subnet_option(self):
        called_with: list[str] = []

        def _discover_check(subnet: str = "192.168.1.0/24", **kwargs):
            called_with.append(subnet)
            return CheckStatus(module="discover", status="pass", summary="OK")

        checks = {
            "discover": _discover_check,
            "ping": _make_check_fn("ping", "pass", "OK"),
        }
        result = runner.invoke(
            app,
            ["report", "--subnet", "10.0.0.0/8"],
            obj={"_checks": checks},
        )

        assert result.exit_code == 0
        assert called_with == ["10.0.0.0/8"]

    def test_report_help(self):
        result = runner.invoke(app, ["report", "--help"])

        assert result.exit_code == 0
        assert "health" in result.output.lower() or "report" in result.output.lower()
