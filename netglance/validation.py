"""Input validation for netglance API and MCP boundaries.

Validates user-supplied parameters (subnets, hosts, ports) before they reach
module functions.  Catches malformed or malicious input at the boundary so
modules never see it.
"""

from __future__ import annotations

import ipaddress
import re

# Maximum subnet size to prevent accidental /8 scans (65 536 addresses = /16)
_MAX_SUBNET_ADDRESSES = 65536

# Hostname regex: RFC 952 / 1123 — letters, digits, hyphens, dots, max 253 chars
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,253}$")

# Port range: digits, commas, hyphens only
_PORT_RANGE_RE = re.compile(r"^[0-9,\- ]+$")


def validate_subnet(subnet: str) -> str:
    """Validate and normalise a subnet string.

    Returns the canonical form (e.g. ``'192.168.1.0/24'``).
    Raises :class:`ValueError` for invalid or oversized subnets.
    """
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid subnet: {subnet!r}") from exc

    if net.num_addresses > _MAX_SUBNET_ADDRESSES:
        raise ValueError(
            f"Subnet too large: {subnet!r} has {net.num_addresses} addresses (max /{net.max_prefixlen - 16})"
        )
    return str(net)


def validate_host(host: str) -> str:
    """Validate a hostname or IP address.

    Returns the input unchanged if valid.
    Raises :class:`ValueError` for suspicious input.
    """
    # Allow IP addresses (v4 and v6)
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    # Allow valid hostnames
    if _HOSTNAME_RE.match(host):
        return host

    raise ValueError(f"Invalid host: {host!r}")


def validate_port_range(ports: str) -> str:
    """Validate a port range string like ``'1-1024'`` or ``'80,443,8080'``.

    Returns the input unchanged if valid.
    Raises :class:`ValueError` for non-numeric / suspicious input.
    """
    if not _PORT_RANGE_RE.match(ports):
        raise ValueError(f"Invalid port range: {ports!r}")
    return ports


def validate_url(url: str) -> str:
    """Validate a URL for HTTP probing.

    Allows ``http://`` and ``https://`` schemes only.
    Raises :class:`ValueError` for invalid or dangerous URLs.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL scheme (must be http:// or https://): {url!r}")
    # Block obvious injection attempts
    if any(c in url for c in (";", "`", "$", "|", "\n", "\r")):
        raise ValueError(f"Invalid URL: contains shell metacharacters: {url!r}")
    return url
