"""Tests for the TLS certificate verification module.

All network I/O is mocked -- no real TLS connections are made.
"""

from __future__ import annotations

import hashlib
import ssl
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.tls import (
    DEFAULT_HOSTS,
    TRUSTED_ROOT_CAS,
    TlsCheckResult,
    _is_trusted_ca,
    _parse_cert_dict,
    _parse_dn_field,
    check_certificate,
    check_multiple,
    diff_fingerprints,
)
from netglance.store.models import CertInfo

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers to build fake certificate dicts (as returned by SSLSocket.getpeercert)
# ---------------------------------------------------------------------------

def _make_cert_dict(
    cn: str = "example.com",
    issuer_cn: str = "DigiCert SHA2 Extended Validation Server CA",
    issuer_org: str = "DigiCert Inc",
    serial: str = "0A1B2C3D4E5F",
    not_before: str | None = None,
    not_after: str | None = None,
    san: list[tuple[str, str]] | None = None,
) -> dict:
    """Build a fake certificate dict matching the ssl.getpeercert() format."""
    now = datetime.now(tz=timezone.utc)
    if not_before is None:
        not_before = (now - timedelta(days=30)).strftime("%b %d %H:%M:%S %Y GMT")
    if not_after is None:
        not_after = (now + timedelta(days=365)).strftime("%b %d %H:%M:%S %Y GMT")
    if san is None:
        san = [("DNS", cn)]

    return {
        "subject": ((("commonName", cn),),),
        "issuer": (
            (("organizationName", issuer_org),),
            (("commonName", issuer_cn),),
        ),
        "serialNumber": serial,
        "notBefore": not_before,
        "notAfter": not_after,
        "subjectAltName": tuple(san),
    }


def _mock_ssl_connection(cert_dict: dict):
    """Return a context-manager mock that simulates ssl.wrap_socket + getpeercert."""
    mock_ssock = MagicMock()
    mock_ssock.getpeercert.return_value = cert_dict
    mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
    mock_ssock.__exit__ = MagicMock(return_value=False)

    mock_ctx = MagicMock(spec=ssl.SSLContext)
    mock_ctx.wrap_socket.return_value = mock_ssock

    return mock_ctx, mock_ssock


# ---------------------------------------------------------------------------
# Unit tests -- internal helpers
# ---------------------------------------------------------------------------


class TestParseDnField:
    def test_extracts_common_name(self):
        dn = ((("commonName", "example.com"),),)
        assert _parse_dn_field(dn, "commonName") == "example.com"

    def test_returns_empty_for_missing_field(self):
        dn = ((("commonName", "example.com"),),)
        assert _parse_dn_field(dn, "organizationName") == ""

    def test_extracts_org_name(self):
        dn = (
            (("organizationName", "DigiCert Inc"),),
            (("commonName", "DigiCert SHA2"),),
        )
        assert _parse_dn_field(dn, "organizationName") == "DigiCert Inc"


class TestParseCertDict:
    def test_parses_subject_and_issuer(self):
        cert_dict = _make_cert_dict(cn="github.com", issuer_org="DigiCert Inc")
        info = _parse_cert_dict("github.com", 443, cert_dict)
        assert info.host == "github.com"
        assert info.subject == "github.com"
        assert info.root_ca == "DigiCert Inc"

    def test_fingerprint_is_sha256_hex(self):
        cert_dict = _make_cert_dict(serial="AABBCCDD")
        info = _parse_cert_dict("example.com", 443, cert_dict)
        expected = hashlib.sha256(b"AABBCCDD").hexdigest()
        assert info.fingerprint_sha256 == expected

    def test_san_parsed(self):
        cert_dict = _make_cert_dict(
            san=[("DNS", "example.com"), ("DNS", "www.example.com")]
        )
        info = _parse_cert_dict("example.com", 443, cert_dict)
        assert len(info.san) == 2
        assert "DNS:example.com" in info.san

    def test_dates_parsed(self):
        cert_dict = _make_cert_dict(
            not_before="Jan 01 00:00:00 2024 GMT",
            not_after="Dec 31 23:59:59 2025 GMT",
        )
        info = _parse_cert_dict("example.com", 443, cert_dict)
        assert info.not_before.year == 2024
        assert info.not_after.year == 2025


class TestIsTrustedCA:
    def test_digicert_is_trusted(self):
        assert _is_trusted_ca("DigiCert Inc") is True

    def test_lets_encrypt_is_trusted(self):
        assert _is_trusted_ca("Let's Encrypt") is True

    def test_google_trust_services_is_trusted(self):
        assert _is_trusted_ca("Google Trust Services LLC") is True

    def test_amazon_trust_is_trusted(self):
        assert _is_trusted_ca("Amazon Trust Services") is True

    def test_unknown_ca_is_not_trusted(self):
        assert _is_trusted_ca("Corporate Proxy CA") is False

    def test_empty_is_not_trusted(self):
        assert _is_trusted_ca("") is False

    def test_case_insensitive_match(self):
        assert _is_trusted_ca("digicert inc") is True


# ---------------------------------------------------------------------------
# Integration-level tests -- check_certificate / check_multiple
# ---------------------------------------------------------------------------


class TestCheckCertificate:
    """Tests for the check_certificate function with mocked sockets."""

    @patch("netglance.modules.tls.socket.create_connection")
    def test_trusted_certificate(self, mock_create_conn):
        cert_dict = _make_cert_dict(issuer_org="DigiCert Inc")
        mock_ctx, mock_ssock = _mock_ssl_connection(cert_dict)

        # wire up: context.wrap_socket(sock, ...) -> ssock
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = check_certificate("example.com", _context_factory=mock_ctx)

        assert result.host == "example.com"
        assert result.is_trusted is True
        assert result.is_intercepted is False
        assert "DigiCert" in result.details

    @patch("netglance.modules.tls.socket.create_connection")
    def test_intercepted_certificate(self, mock_create_conn):
        cert_dict = _make_cert_dict(
            issuer_cn="Corporate Proxy CA",
            issuer_org="ACME Corp Internal",
        )
        mock_ctx, mock_ssock = _mock_ssl_connection(cert_dict)

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = check_certificate("example.com", _context_factory=mock_ctx)

        assert result.is_trusted is False
        assert result.is_intercepted is True
        assert "interception" in result.details.lower() or "unknown CA" in result.details

    @patch("netglance.modules.tls.socket.create_connection")
    def test_connection_error(self, mock_create_conn):
        mock_create_conn.side_effect = OSError("Connection refused")
        mock_ctx = MagicMock(spec=ssl.SSLContext)

        result = check_certificate("unreachable.example", _context_factory=mock_ctx)

        assert result.is_trusted is False
        assert "Connection error" in result.details

    @patch("netglance.modules.tls.socket.create_connection")
    def test_ssl_verification_error(self, mock_create_conn):
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock
        mock_ctx.wrap_socket.side_effect = ssl.SSLCertVerificationError(
            "certificate verify failed"
        )

        result = check_certificate("badcert.example", _context_factory=mock_ctx)

        assert result.is_trusted is False
        assert "verification failed" in result.details.lower()

    @patch("netglance.modules.tls.socket.create_connection")
    def test_lets_encrypt_trusted(self, mock_create_conn):
        cert_dict = _make_cert_dict(
            issuer_cn="R3",
            issuer_org="Let's Encrypt",
        )
        mock_ctx, mock_ssock = _mock_ssl_connection(cert_dict)

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = check_certificate("letsencrypt.org", _context_factory=mock_ctx)

        assert result.is_trusted is True
        assert result.is_intercepted is False

    @patch("netglance.modules.tls.socket.create_connection")
    def test_empty_cert_returned(self, mock_create_conn):
        """getpeercert() returning None/empty dict."""
        mock_ctx = MagicMock(spec=ssl.SSLContext)
        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = {}
        mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
        mock_ssock.__exit__ = MagicMock(return_value=False)
        mock_ctx.wrap_socket.return_value = mock_ssock

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = check_certificate("empty.example", _context_factory=mock_ctx)

        assert result.is_trusted is False
        assert "No certificate" in result.details


class TestCheckMultiple:
    @patch("netglance.modules.tls.socket.create_connection")
    def test_checks_default_hosts(self, mock_create_conn):
        cert_dict = _make_cert_dict(issuer_org="DigiCert Inc")
        mock_ctx, _ = _mock_ssl_connection(cert_dict)

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        results = check_multiple(_context_factory=mock_ctx)

        assert len(results) == len(DEFAULT_HOSTS)
        hosts_checked = {r.host for r in results}
        assert hosts_checked == set(DEFAULT_HOSTS)

    @patch("netglance.modules.tls.socket.create_connection")
    def test_custom_host_list(self, mock_create_conn):
        cert_dict = _make_cert_dict(issuer_org="Let's Encrypt")
        mock_ctx, _ = _mock_ssl_connection(cert_dict)

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        results = check_multiple(hosts=["a.com", "b.com"], _context_factory=mock_ctx)

        assert len(results) == 2
        assert results[0].host == "a.com"
        assert results[1].host == "b.com"


# ---------------------------------------------------------------------------
# diff_fingerprints tests
# ---------------------------------------------------------------------------


class TestDiffFingerprints:
    def _make_result(self, host: str, fingerprint: str) -> TlsCheckResult:
        cert = CertInfo(host=host, fingerprint_sha256=fingerprint)
        return TlsCheckResult(host=host, cert=cert)

    def test_matching_fingerprints(self):
        current = [self._make_result("google.com", "aabbcc")]
        baseline = [{"host": "google.com", "fingerprint_sha256": "aabbcc"}]

        diffs = diff_fingerprints(current, baseline)

        assert len(diffs) == 1
        assert diffs[0]["status"] == "match"
        assert diffs[0]["host"] == "google.com"

    def test_changed_fingerprint(self):
        current = [self._make_result("google.com", "new_fp")]
        baseline = [{"host": "google.com", "fingerprint_sha256": "old_fp"}]

        diffs = diff_fingerprints(current, baseline)

        assert len(diffs) == 1
        assert diffs[0]["status"] == "changed"
        assert diffs[0]["old_fingerprint"] == "old_fp"
        assert diffs[0]["new_fingerprint"] == "new_fp"

    def test_new_host_not_in_baseline(self):
        current = [self._make_result("newhost.com", "some_fp")]
        baseline = [{"host": "google.com", "fingerprint_sha256": "aaa"}]

        diffs = diff_fingerprints(current, baseline)

        assert len(diffs) == 1
        assert diffs[0]["status"] == "new"
        assert diffs[0]["old_fingerprint"] is None

    def test_empty_baseline(self):
        current = [
            self._make_result("a.com", "fp1"),
            self._make_result("b.com", "fp2"),
        ]
        baseline: list[dict] = []

        diffs = diff_fingerprints(current, baseline)

        assert len(diffs) == 2
        assert all(d["status"] == "new" for d in diffs)

    def test_mixed_results(self):
        current = [
            self._make_result("same.com", "fingerprint_same"),
            self._make_result("changed.com", "fingerprint_new"),
            self._make_result("new.com", "fingerprint_x"),
        ]
        baseline = [
            {"host": "same.com", "fingerprint_sha256": "fingerprint_same"},
            {"host": "changed.com", "fingerprint_sha256": "fingerprint_old"},
        ]

        diffs = diff_fingerprints(current, baseline)

        status_map = {d["host"]: d["status"] for d in diffs}
        assert status_map["same.com"] == "match"
        assert status_map["changed.com"] == "changed"
        assert status_map["new.com"] == "new"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestTlsCli:
    """CLI tests for the tls subcommand group."""

    @patch("netglance.modules.tls.socket.create_connection")
    @patch("netglance.modules.tls.ssl.create_default_context")
    def test_tls_verify_default(self, mock_ssl_ctx_factory, mock_create_conn):
        cert_dict = _make_cert_dict(issuer_org="DigiCert Inc")
        mock_ctx, _ = _mock_ssl_connection(cert_dict)
        mock_ssl_ctx_factory.return_value = mock_ctx

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = runner.invoke(app, ["tls", "verify"])

        assert result.exit_code == 0
        assert "TLS Certificate Check" in result.output

    @patch("netglance.modules.tls.socket.create_connection")
    @patch("netglance.modules.tls.ssl.create_default_context")
    def test_tls_verify_single_host(self, mock_ssl_ctx_factory, mock_create_conn):
        cert_dict = _make_cert_dict(cn="github.com", issuer_org="DigiCert Inc")
        mock_ctx, _ = _mock_ssl_connection(cert_dict)
        mock_ssl_ctx_factory.return_value = mock_ctx

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = runner.invoke(app, ["tls", "verify", "github.com"])

        assert result.exit_code == 0
        assert "github.com" in result.output

    @patch("netglance.modules.tls.socket.create_connection")
    @patch("netglance.modules.tls.ssl.create_default_context")
    def test_tls_verify_intercepted_shows_red(self, mock_ssl_ctx_factory, mock_create_conn):
        cert_dict = _make_cert_dict(
            issuer_cn="Evil Corp Proxy",
            issuer_org="Evil Corp",
        )
        mock_ctx, _ = _mock_ssl_connection(cert_dict)
        mock_ssl_ctx_factory.return_value = mock_ctx

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = runner.invoke(app, ["tls", "verify", "example.com"])

        assert result.exit_code == 0
        assert "INTERCEPTED" in result.output

    @patch("netglance.modules.tls.socket.create_connection")
    @patch("netglance.modules.tls.ssl.create_default_context")
    def test_tls_chain_command(self, mock_ssl_ctx_factory, mock_create_conn):
        cert_dict = _make_cert_dict(
            cn="example.com",
            issuer_org="DigiCert Inc",
            san=[("DNS", "example.com"), ("DNS", "www.example.com")],
        )
        mock_ctx, _ = _mock_ssl_connection(cert_dict)
        mock_ssl_ctx_factory.return_value = mock_ctx

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_create_conn.return_value = mock_sock

        result = runner.invoke(app, ["tls", "chain", "example.com"])

        assert result.exit_code == 0
        assert "Certificate Chain" in result.output
        assert "example.com" in result.output
        assert "DigiCert" in result.output

    def test_tls_help(self):
        result = runner.invoke(app, ["tls", "--help"])
        assert result.exit_code == 0
        assert "TLS" in result.output or "tls" in result.output

    def test_tls_verify_help(self):
        result = runner.invoke(app, ["tls", "verify", "--help"])
        assert result.exit_code == 0
        assert "Verify" in result.output or "verify" in result.output


# ---------------------------------------------------------------------------
# TlsCheckResult dataclass tests
# ---------------------------------------------------------------------------


class TestTlsCheckResult:
    def test_default_values(self):
        cert = CertInfo(host="test.com")
        result = TlsCheckResult(host="test.com", cert=cert)
        assert result.is_trusted is True
        assert result.is_intercepted is False
        assert result.matches_baseline is None
        assert result.details == ""

    def test_custom_values(self):
        cert = CertInfo(host="test.com", issuer="Test CA")
        result = TlsCheckResult(
            host="test.com",
            cert=cert,
            is_trusted=False,
            is_intercepted=True,
            details="Intercepted by corporate proxy",
        )
        assert result.is_intercepted is True
        assert result.is_trusted is False


# ---------------------------------------------------------------------------
# TRUSTED_ROOT_CAS constant tests
# ---------------------------------------------------------------------------


class TestTrustedRootCAs:
    def test_contains_major_cas(self):
        expected_cas = [
            "DigiCert Inc",
            "Let's Encrypt",
            "GlobalSign",
            "Google Trust Services",
            "Amazon",
        ]
        for ca in expected_cas:
            assert ca in TRUSTED_ROOT_CAS, f"{ca} should be in TRUSTED_ROOT_CAS"

    def test_is_non_empty(self):
        assert len(TRUSTED_ROOT_CAS) > 10
