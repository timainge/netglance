"""Tests for the HTTP header inspection & proxy detection module."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.http import (
    DEFAULT_CHECK_URLS,
    PROXY_HEADERS,
    HttpProbeResult,
    check_for_proxies,
    detect_content_injection,
    probe_url,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers: fake httpx.Response objects
# ---------------------------------------------------------------------------

def _make_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    content: bytes = b"hello world",
) -> httpx.Response:
    """Build a real httpx.Response with controlled headers and body."""
    resp = httpx.Response(
        status_code=status_code,
        headers=headers or {},
        content=content,
        request=httpx.Request("GET", "http://test.local"),
    )
    return resp


def _fake_get_factory(response: httpx.Response):
    """Return a callable ``(url, timeout) -> response`` suitable for ``_get_fn``."""
    def _fake_get(url: str, timeout: float) -> httpx.Response:
        return response
    return _fake_get


# ---------------------------------------------------------------------------
# probe_url tests
# ---------------------------------------------------------------------------

class TestProbeUrl:
    """Unit tests for probe_url()."""

    def test_clean_response_no_proxy(self) -> None:
        """A response without proxy headers should report proxy_detected=False."""
        resp = _make_response(headers={"Content-Type": "text/html"})
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert isinstance(result, HttpProbeResult)
        assert result.url == "http://example.com"
        assert result.status_code == 200
        assert result.proxy_detected is False
        assert result.suspicious_headers == {}
        assert result.injected_content is False
        assert result.details == []

    def test_via_header_detected(self) -> None:
        """A response containing a Via header should flag proxy_detected=True."""
        resp = _make_response(headers={"Via": "1.1 squid-proxy"})
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert result.proxy_detected is True
        assert "Via" in result.suspicious_headers
        assert result.suspicious_headers["Via"] == "1.1 squid-proxy"
        assert any("Via" in d for d in result.details)

    def test_x_forwarded_for_detected(self) -> None:
        """A response containing X-Forwarded-For should flag proxy_detected=True."""
        resp = _make_response(headers={"X-Forwarded-For": "10.0.0.1"})
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert result.proxy_detected is True
        assert "X-Forwarded-For" in result.suspicious_headers
        assert result.suspicious_headers["X-Forwarded-For"] == "10.0.0.1"

    def test_multiple_proxy_headers(self) -> None:
        """Multiple proxy headers should all appear in suspicious_headers."""
        resp = _make_response(headers={
            "Via": "1.0 cache",
            "X-Cache": "HIT",
            "X-Proxy-ID": "proxy-42",
        })
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert result.proxy_detected is True
        assert len(result.suspicious_headers) == 3
        assert result.suspicious_headers["Via"] == "1.0 cache"
        assert result.suspicious_headers["X-Cache"] == "HIT"
        assert result.suspicious_headers["X-Proxy-ID"] == "proxy-42"

    def test_non_proxy_x_header_ignored(self) -> None:
        """Headers that look custom but are not in PROXY_HEADERS should be ignored."""
        resp = _make_response(headers={"X-Request-Id": "abc123"})
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert result.proxy_detected is False
        assert result.suspicious_headers == {}

    def test_status_code_preserved(self) -> None:
        """The HTTP status code should be faithfully recorded."""
        resp = _make_response(status_code=403)
        result = probe_url("http://example.com", _get_fn=_fake_get_factory(resp))

        assert result.status_code == 403


# ---------------------------------------------------------------------------
# check_for_proxies tests
# ---------------------------------------------------------------------------

class TestCheckForProxies:
    """Unit tests for check_for_proxies()."""

    def test_default_urls_checked(self) -> None:
        """When no URLs are supplied, DEFAULT_CHECK_URLS should be probed."""
        resp = _make_response()
        results = check_for_proxies(_get_fn=_fake_get_factory(resp))

        assert len(results) == len(DEFAULT_CHECK_URLS)
        urls_checked = [r.url for r in results]
        assert urls_checked == DEFAULT_CHECK_URLS

    def test_custom_urls(self) -> None:
        """Caller-supplied URLs should be used instead of defaults."""
        resp = _make_response()
        custom = ["http://foo.test", "http://bar.test"]
        results = check_for_proxies(urls=custom, _get_fn=_fake_get_factory(resp))

        assert len(results) == 2
        assert results[0].url == "http://foo.test"
        assert results[1].url == "http://bar.test"

    def test_per_url_results(self) -> None:
        """Each URL gets its own independent HttpProbeResult."""
        call_count = 0

        def _counting_get(url: str, timeout: float) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "proxy" in url:
                return _make_response(headers={"Via": "1.1 proxy"})
            return _make_response()

        results = check_for_proxies(
            urls=["http://clean.test", "http://proxy.test"],
            _get_fn=_counting_get,
        )
        assert call_count == 2
        assert results[0].proxy_detected is False
        assert results[1].proxy_detected is True


# ---------------------------------------------------------------------------
# detect_content_injection tests
# ---------------------------------------------------------------------------

class TestDetectContentInjection:
    """Unit tests for detect_content_injection()."""

    def test_matching_hash_returns_false(self) -> None:
        """When the body hash matches, no injection is detected."""
        body = b"expected content"
        expected = hashlib.sha256(body).hexdigest()
        resp = _make_response(content=body)

        result = detect_content_injection(
            "http://example.com",
            expected_hash=expected,
            _get_fn=_fake_get_factory(resp),
        )
        assert result is False

    def test_mismatched_hash_returns_true(self) -> None:
        """When the body hash differs, content injection is detected."""
        resp = _make_response(content=b"tampered body")
        result = detect_content_injection(
            "http://example.com",
            expected_hash="0000000000000000000000000000000000000000000000000000000000000000",
            _get_fn=_fake_get_factory(resp),
        )
        assert result is True

    def test_no_expected_hash_returns_false(self) -> None:
        """Without a reference hash, the function cannot detect injection."""
        resp = _make_response(content=b"anything")
        result = detect_content_injection(
            "http://example.com",
            expected_hash=None,
            _get_fn=_fake_get_factory(resp),
        )
        assert result is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestHttpCli:
    """Integration tests for the ``netglance http`` CLI subcommands."""

    def test_http_help(self) -> None:
        """``netglance http --help`` should succeed and mention 'check'."""
        result = runner.invoke(app, ["http", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output
        assert "headers" in result.output

    def test_http_check_default_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``netglance http check`` (no URL) should probe defaults without errors."""
        resp = _make_response(headers={"Content-Type": "text/html"})

        monkeypatch.setattr(
            "netglance.modules.http._httpx_get",
            lambda url, timeout: resp,
        )

        result = runner.invoke(app, ["http", "check"])
        assert result.exit_code == 0
        assert "HTTP Probe Results" in result.output

    def test_http_check_specific_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``netglance http check <url>`` should probe that URL only."""
        resp = _make_response(headers={"Via": "1.0 myproxy"})

        monkeypatch.setattr(
            "netglance.modules.http._httpx_get",
            lambda url, timeout: resp,
        )

        result = runner.invoke(app, ["http", "check", "http://test.local"])
        assert result.exit_code == 0
        assert "YES" in result.output  # proxy detected
        assert "Via" in result.output

    def test_http_check_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A clean response should show NO in the proxy column."""
        resp = _make_response()

        monkeypatch.setattr(
            "netglance.modules.http._httpx_get",
            lambda url, timeout: resp,
        )

        result = runner.invoke(app, ["http", "check", "http://clean.local"])
        assert result.exit_code == 0
        assert "NO" in result.output

    def test_http_headers_cmd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``netglance http headers <url>`` should display all response headers."""
        resp = _make_response(headers={
            "Content-Type": "text/html",
            "X-Cache": "MISS",
            "Server": "nginx",
        })

        monkeypatch.setattr(
            "netglance.modules.http._httpx_get",
            lambda url, timeout: resp,
        )

        result = runner.invoke(app, ["http", "headers", "http://test.local"])
        assert result.exit_code == 0
        assert "Response Headers" in result.output
        assert "content-type" in result.output.lower()
        assert "server" in result.output.lower()
