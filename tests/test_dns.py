"""Tests for netglance.modules.dns and DNS CLI subcommands.

All DNS network I/O is mocked -- no real queries are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dns.flags
import dns.message
import dns.name
import dns.rdatatype
import dns.resolver
import dns.rrset
import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.dns import (
    DEFAULT_RESOLVERS,
    DnsHealthReport,
    _HIJACK_CANARY,
    benchmark_resolvers,
    check_consistency,
    check_dnssec,
    detect_dns_hijack,
    query_resolver,
)
from netglance.store.models import DnsResolverResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers to build mock dns.resolver responses
# ---------------------------------------------------------------------------


class _FakeRData:
    """Minimal rdata stand-in with a .to_text() method."""

    def __init__(self, text: str) -> None:
        self._text = text

    def to_text(self) -> str:
        return self._text


class _FakeAnswer:
    """Minimal Answer stand-in that is iterable over rdata items."""

    def __init__(self, texts: list[str], flags: int = 0) -> None:
        self._items = [_FakeRData(t) for t in texts]
        self.response = MagicMock()
        self.response.flags = flags

    def __iter__(self):
        return iter(self._items)


def _make_resolve_side_effect(
    mapping: dict[tuple[str, str], list[str] | Exception],
):
    """Return a side_effect function for ``Resolver.resolve()``.

    *mapping* maps ``(domain, rdtype)`` to either a list of answer strings
    or an exception to raise.
    """

    def _side_effect(domain: str, rdtype: str = "A", **kw):
        key = (str(domain), str(rdtype))
        value = mapping.get(key)
        if value is None:
            raise dns.resolver.NXDOMAIN()
        if isinstance(value, Exception):
            raise value
        return _FakeAnswer(value)

    return _side_effect


# ---------------------------------------------------------------------------
# Tests for query_resolver
# ---------------------------------------------------------------------------


class TestQueryResolver:
    """Unit tests for query_resolver()."""

    @patch("netglance.modules.dns._make_resolver")
    def test_successful_query(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["1.2.3.4", "5.6.7.8"])
        mock_make.return_value = resolver_obj

        result = query_resolver("1.1.1.1", "example.com")

        assert isinstance(result, DnsResolverResult)
        assert result.resolver == "1.1.1.1"
        assert result.resolver_name == "Cloudflare"
        assert result.query == "example.com"
        assert sorted(result.answers) == ["1.2.3.4", "5.6.7.8"]
        assert result.error is None
        assert result.response_time_ms >= 0

    @patch("netglance.modules.dns._make_resolver")
    def test_nxdomain(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.resolver.NXDOMAIN()
        mock_make.return_value = resolver_obj

        result = query_resolver("8.8.8.8", "nonexistent.example.invalid")

        assert result.answers == []
        assert result.error == "NXDOMAIN"

    @patch("netglance.modules.dns._make_resolver")
    def test_timeout(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.exception.Timeout()
        mock_make.return_value = resolver_obj

        result = query_resolver("9.9.9.9", "example.com")

        assert result.answers == []
        assert result.error == "Timeout"

    @patch("netglance.modules.dns._make_resolver")
    def test_no_answer(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.resolver.NoAnswer()
        mock_make.return_value = resolver_obj

        result = query_resolver("1.1.1.1", "example.com", rdtype="AAAA")

        assert result.answers == []
        assert result.error == "NoAnswer"

    @patch("netglance.modules.dns._make_resolver")
    def test_no_nameservers(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.resolver.NoNameservers()
        mock_make.return_value = resolver_obj

        result = query_resolver("1.1.1.1", "example.com")

        assert result.answers == []
        assert result.error == "NoNameservers"

    @patch("netglance.modules.dns._make_resolver")
    def test_custom_resolver_name(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["10.0.0.1"])
        mock_make.return_value = resolver_obj

        result = query_resolver("10.10.10.10", "example.com", resolver_name="Custom")

        assert result.resolver_name == "Custom"


# ---------------------------------------------------------------------------
# Tests for check_consistency
# ---------------------------------------------------------------------------


class TestCheckConsistency:
    """Unit tests for check_consistency()."""

    @patch("netglance.modules.dns.check_dnssec", return_value=False)
    @patch("netglance.modules.dns._make_resolver")
    def test_consistent_results(self, mock_make, mock_dnssec):
        """All resolvers return the same answers -> consistent=True."""
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["93.184.216.34"])
        mock_make.return_value = resolver_obj

        report = check_consistency("example.com")

        assert isinstance(report, DnsHealthReport)
        assert report.consistent is True
        assert report.potential_hijack is False
        assert report.resolvers_checked == len(DEFAULT_RESOLVERS)
        assert len(report.details) == len(DEFAULT_RESOLVERS)
        assert report.fastest_resolver is not None

    @patch("netglance.modules.dns.check_dnssec", return_value=False)
    @patch("netglance.modules.dns._make_resolver")
    def test_inconsistent_results(self, mock_make, mock_dnssec):
        """Different resolvers return different IPs -> potential hijack."""
        call_count = 0

        def _varying_resolve(domain, rdtype="A", **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeAnswer(["1.2.3.4"])
            return _FakeAnswer(["9.9.9.9"])

        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = _varying_resolve
        mock_make.return_value = resolver_obj

        report = check_consistency("example.com")

        assert report.consistent is False
        assert report.potential_hijack is True

    @patch("netglance.modules.dns.check_dnssec", return_value=True)
    @patch("netglance.modules.dns._make_resolver")
    def test_dnssec_flag_propagated(self, mock_make, mock_dnssec):
        """DNSSEC support is reflected in the report."""
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["93.184.216.34"])
        mock_make.return_value = resolver_obj

        report = check_consistency("example.com")

        assert report.dnssec_supported is True

    @patch("netglance.modules.dns.check_dnssec", return_value=False)
    @patch("netglance.modules.dns._make_resolver")
    def test_custom_resolvers(self, mock_make, mock_dnssec):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["1.2.3.4"])
        mock_make.return_value = resolver_obj

        custom = {"10.0.0.1": "Local", "10.0.0.2": "Backup"}
        report = check_consistency("example.com", resolvers=custom)

        assert report.resolvers_checked == 2


# ---------------------------------------------------------------------------
# Tests for check_dnssec
# ---------------------------------------------------------------------------


class TestCheckDnssec:
    """Unit tests for check_dnssec()."""

    @patch("netglance.modules.dns._make_resolver")
    def test_dnssec_ad_flag_set(self, mock_make):
        """AD flag in response -> True."""
        resolver_obj = MagicMock()
        answer = _FakeAnswer(["93.184.216.34"], flags=dns.flags.AD)
        resolver_obj.resolve.return_value = answer
        mock_make.return_value = resolver_obj

        assert check_dnssec("example.com") is True

    @patch("netglance.modules.dns._make_resolver")
    def test_dnssec_no_ad_flag(self, mock_make):
        """No AD flag in response -> False."""
        resolver_obj = MagicMock()
        answer = _FakeAnswer(["93.184.216.34"], flags=0)
        resolver_obj.resolve.return_value = answer
        mock_make.return_value = resolver_obj

        assert check_dnssec("example.com") is False

    @patch("netglance.modules.dns._make_resolver")
    def test_dnssec_exception_returns_false(self, mock_make):
        """Exception during DNSSEC check -> False."""
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.exception.Timeout()
        mock_make.return_value = resolver_obj

        assert check_dnssec("example.com") is False


# ---------------------------------------------------------------------------
# Tests for benchmark_resolvers
# ---------------------------------------------------------------------------


class TestBenchmarkResolvers:
    """Unit tests for benchmark_resolvers()."""

    @patch("netglance.modules.dns._make_resolver")
    def test_benchmark_returns_results(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["1.2.3.4"])
        mock_make.return_value = resolver_obj

        results = benchmark_resolvers()

        # default: 3 resolvers x 3 domains = 9 results
        assert len(results) == 9
        for r in results:
            assert isinstance(r, DnsResolverResult)
            assert r.error is None
            assert r.response_time_ms >= 0

    @patch("netglance.modules.dns._make_resolver")
    def test_benchmark_custom_domains(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["1.2.3.4"])
        mock_make.return_value = resolver_obj

        results = benchmark_resolvers(domains=["example.com"])

        assert len(results) == len(DEFAULT_RESOLVERS)

    @patch("netglance.modules.dns._make_resolver")
    def test_benchmark_with_errors(self, mock_make):
        call_count = 0

        def _sometimes_fail(domain, rdtype="A", **kw):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise dns.exception.Timeout()
            return _FakeAnswer(["1.2.3.4"])

        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = _sometimes_fail
        mock_make.return_value = resolver_obj

        results = benchmark_resolvers(domains=["test.com"])

        errors = [r for r in results if r.error is not None]
        successes = [r for r in results if r.error is None]
        assert len(errors) > 0
        assert len(successes) > 0


# ---------------------------------------------------------------------------
# Tests for detect_dns_hijack
# ---------------------------------------------------------------------------


class TestDetectDnsHijack:
    """Unit tests for detect_dns_hijack()."""

    @patch("netglance.modules.dns._make_resolver")
    def test_no_hijack_all_nxdomain(self, mock_make):
        """All resolvers return NXDOMAIN for canary -> no hijack."""
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.resolver.NXDOMAIN()
        mock_make.return_value = resolver_obj

        result = detect_dns_hijack()

        assert result["hijack_detected"] is False
        assert len(result["details"]) == len(DEFAULT_RESOLVERS)
        for detail in result["details"]:
            assert detail.answers == []

    @patch("netglance.modules.dns._make_resolver")
    def test_hijack_detected(self, mock_make):
        """If a resolver returns an IP for the canary domain -> hijack."""
        resolver_obj = MagicMock()
        # Return actual answers instead of NXDOMAIN -> hijack indicator
        resolver_obj.resolve.return_value = _FakeAnswer(["10.10.10.10"])
        mock_make.return_value = resolver_obj

        result = detect_dns_hijack()

        assert result["hijack_detected"] is True

    @patch("netglance.modules.dns._make_resolver")
    def test_partial_hijack(self, mock_make):
        """Some resolvers hijack, some don't."""
        call_count = 0

        def _partial_hijack(domain, rdtype="A", **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeAnswer(["10.10.10.10"])  # hijacked
            raise dns.resolver.NXDOMAIN()  # normal

        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = _partial_hijack
        mock_make.return_value = resolver_obj

        result = detect_dns_hijack()

        assert result["hijack_detected"] is True
        hijacked = [d for d in result["details"] if d.answers]
        clean = [d for d in result["details"] if not d.answers]
        assert len(hijacked) >= 1
        assert len(clean) >= 1


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestDnsCli:
    """Tests for the DNS CLI subcommands."""

    @patch("netglance.modules.dns.check_dnssec", return_value=False)
    @patch("netglance.modules.dns._make_resolver")
    def test_dns_check_command(self, mock_make, mock_dnssec):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["93.184.216.34"])
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "check", "example.com"])

        assert result.exit_code == 0
        assert "DNS Health Check" in result.output
        assert "CONSISTENT" in result.output
        assert "Resolvers checked" in result.output

    @patch("netglance.modules.dns.check_dnssec", return_value=False)
    @patch("netglance.modules.dns._make_resolver")
    def test_dns_check_inconsistent(self, mock_make, mock_dnssec):
        call_count = 0

        def _varying_resolve(domain, rdtype="A", **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeAnswer(["1.1.1.1"])
            return _FakeAnswer(["2.2.2.2"])

        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = _varying_resolve
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "check", "example.com"])

        assert result.exit_code == 0
        assert "INCONSISTENT" in result.output
        assert "YES" in result.output  # potential hijack

    @patch("netglance.modules.dns._make_resolver")
    def test_dns_resolve_command(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["93.184.216.34"])
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "resolve", "example.com"])

        assert result.exit_code == 0
        assert "DNS Resolution Results" in result.output
        assert "93.184.216.34" in result.output

    @patch("netglance.modules.dns._make_resolver")
    def test_dns_resolve_with_custom_resolver(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["10.0.0.1"])
        mock_make.return_value = resolver_obj

        result = runner.invoke(
            app, ["dns", "resolve", "example.com", "--resolver", "10.10.10.10"]
        )

        assert result.exit_code == 0
        assert "10.0.0.1" in result.output

    @patch("netglance.modules.dns._make_resolver")
    def test_dns_benchmark_command(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["1.2.3.4"])
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "benchmark"])

        assert result.exit_code == 0
        assert "Benchmark" in result.output
        assert "Average response times" in result.output

    @patch("netglance.modules.dns._make_resolver")
    def test_dns_hijack_no_hijack(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.side_effect = dns.resolver.NXDOMAIN()
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "hijack"])

        assert result.exit_code == 0
        assert "No DNS hijacking detected" in result.output

    @patch("netglance.modules.dns._make_resolver")
    def test_dns_hijack_detected(self, mock_make):
        resolver_obj = MagicMock()
        resolver_obj.resolve.return_value = _FakeAnswer(["10.10.10.10"])
        mock_make.return_value = resolver_obj

        result = runner.invoke(app, ["dns", "hijack"])

        assert result.exit_code == 0
        assert "Potential DNS hijacking detected" in result.output
        assert "HIJACKED" in result.output

    def test_dns_help(self):
        result = runner.invoke(app, ["dns", "--help"])

        assert result.exit_code == 0
        assert "DNS" in result.output or "dns" in result.output
