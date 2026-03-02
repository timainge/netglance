"""Tests for input validation module."""

from __future__ import annotations

import pytest

from netglance.validation import (
    validate_host,
    validate_port_range,
    validate_subnet,
    validate_url,
)


# ---------------------------------------------------------------------------
# validate_subnet
# ---------------------------------------------------------------------------


class TestValidateSubnet:
    def test_valid_ipv4_subnet(self) -> None:
        assert validate_subnet("192.168.1.0/24") == "192.168.1.0/24"

    def test_valid_ipv4_host_normalised(self) -> None:
        # Non-strict: host bits are cleared
        assert validate_subnet("192.168.1.50/24") == "192.168.1.0/24"

    def test_valid_slash_16(self) -> None:
        assert validate_subnet("10.0.0.0/16") == "10.0.0.0/16"

    def test_single_host(self) -> None:
        assert validate_subnet("192.168.1.1/32") == "192.168.1.1/32"

    def test_rejects_too_large_subnet(self) -> None:
        with pytest.raises(ValueError, match="too large"):
            validate_subnet("10.0.0.0/8")

    def test_rejects_slash_15(self) -> None:
        with pytest.raises(ValueError, match="too large"):
            validate_subnet("10.0.0.0/15")

    def test_rejects_nonsense(self) -> None:
        with pytest.raises(ValueError, match="Invalid subnet"):
            validate_subnet("not-a-subnet")

    def test_rejects_injection_semicolon(self) -> None:
        with pytest.raises(ValueError, match="Invalid subnet"):
            validate_subnet("192.168.1.0/24; rm -rf /")

    def test_rejects_injection_pipe(self) -> None:
        with pytest.raises(ValueError, match="Invalid subnet"):
            validate_subnet("192.168.1.0/24 | whoami")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid subnet"):
            validate_subnet("")


# ---------------------------------------------------------------------------
# validate_host
# ---------------------------------------------------------------------------


class TestValidateHost:
    def test_valid_ipv4(self) -> None:
        assert validate_host("192.168.1.1") == "192.168.1.1"

    def test_valid_ipv6(self) -> None:
        assert validate_host("::1") == "::1"

    def test_valid_hostname(self) -> None:
        assert validate_host("example.com") == "example.com"

    def test_valid_hostname_with_subdomain(self) -> None:
        assert validate_host("sub.example.com") == "sub.example.com"

    def test_valid_hostname_with_hyphen(self) -> None:
        assert validate_host("my-host.local") == "my-host.local"

    def test_rejects_semicolon_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid host"):
            validate_host("example.com; whoami")

    def test_rejects_backtick_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid host"):
            validate_host("`whoami`")

    def test_rejects_pipe_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid host"):
            validate_host("host | cat /etc/passwd")

    def test_rejects_space_in_hostname(self) -> None:
        with pytest.raises(ValueError, match="Invalid host"):
            validate_host("my host")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid host"):
            validate_host("")


# ---------------------------------------------------------------------------
# validate_port_range
# ---------------------------------------------------------------------------


class TestValidatePortRange:
    def test_valid_range(self) -> None:
        assert validate_port_range("1-1024") == "1-1024"

    def test_valid_single_port(self) -> None:
        assert validate_port_range("80") == "80"

    def test_valid_comma_separated(self) -> None:
        assert validate_port_range("22,80,443") == "22,80,443"

    def test_valid_mixed(self) -> None:
        assert validate_port_range("22,80-100,443") == "22,80-100,443"

    def test_rejects_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid port range"):
            validate_port_range("80; whoami")

    def test_rejects_letters(self) -> None:
        with pytest.raises(ValueError, match="Invalid port range"):
            validate_port_range("http")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid port range"):
            validate_port_range("")


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_valid_http(self) -> None:
        assert validate_url("http://example.com") == "http://example.com"

    def test_valid_https(self) -> None:
        assert validate_url("https://example.com/path") == "https://example.com/path"

    def test_rejects_ftp(self) -> None:
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_url("ftp://example.com")

    def test_rejects_no_scheme(self) -> None:
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_url("example.com")

    def test_rejects_semicolon_injection(self) -> None:
        with pytest.raises(ValueError, match="shell metacharacters"):
            validate_url("http://example.com; rm -rf /")

    def test_rejects_backtick_injection(self) -> None:
        with pytest.raises(ValueError, match="shell metacharacters"):
            validate_url("http://example.com/`whoami`")

    def test_rejects_pipe_injection(self) -> None:
        with pytest.raises(ValueError, match="shell metacharacters"):
            validate_url("http://example.com | cat /etc/passwd")

    def test_rejects_dollar_injection(self) -> None:
        with pytest.raises(ValueError, match="shell metacharacters"):
            validate_url("http://example.com/$(whoami)")
