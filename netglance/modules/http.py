"""HTTP header inspection and proxy / content-injection detection."""

from __future__ import annotations

import hashlib

import httpx

from netglance.store.models import HttpProbeResult

# Well-known headers that indicate a transparent or intercepting proxy
PROXY_HEADERS: list[str] = [
    "Via",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Cache",
    "X-Proxy-ID",
]

# Default URLs used when no explicit targets are supplied
DEFAULT_CHECK_URLS: list[str] = [
    "http://httpbin.org/get",
    "http://example.com",
]


# ---------------------------------------------------------------------------
# Thin I/O wrapper -- easy to replace in tests
# ---------------------------------------------------------------------------

def _httpx_get(url: str, timeout: float) -> httpx.Response:
    """Perform an HTTP GET via httpx.  Isolated for mockability."""
    return httpx.get(url, timeout=timeout, follow_redirects=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def probe_url(
    url: str,
    timeout: float = 5.0,
    *,
    _get_fn=None,
) -> HttpProbeResult:
    """Fetch *url* and inspect the response for proxy / injection indicators.

    Args:
        url: The URL to probe.
        timeout: Request timeout in seconds.
        _get_fn: Injectable replacement for ``httpx.get`` (for testing).

    Returns:
        An ``HttpProbeResult`` summarising findings.
    """
    get_fn = _get_fn or _httpx_get
    resp = get_fn(url, timeout)

    suspicious: dict[str, str] = {}
    details: list[str] = []

    for header_name in PROXY_HEADERS:
        value = resp.headers.get(header_name)
        if value is not None:
            suspicious[header_name] = value
            details.append(f"Proxy header detected: {header_name}: {value}")

    proxy_detected = len(suspicious) > 0

    if proxy_detected:
        details.insert(0, "One or more proxy-related headers found in the response.")

    return HttpProbeResult(
        url=url,
        status_code=resp.status_code,
        suspicious_headers=suspicious,
        injected_content=False,
        proxy_detected=proxy_detected,
        details=details,
    )


def check_for_proxies(
    urls: list[str] | None = None,
    timeout: float = 5.0,
    *,
    _get_fn=None,
) -> list[HttpProbeResult]:
    """Probe multiple URLs for proxy indicators.

    Args:
        urls: URLs to check.  Defaults to ``DEFAULT_CHECK_URLS``.
        timeout: Per-request timeout in seconds.
        _get_fn: Injectable replacement for the HTTP GET callable.

    Returns:
        A list of ``HttpProbeResult``, one per URL.
    """
    targets = urls if urls is not None else DEFAULT_CHECK_URLS
    return [probe_url(u, timeout=timeout, _get_fn=_get_fn) for u in targets]


def detect_content_injection(
    url: str,
    expected_hash: str | None = None,
    timeout: float = 5.0,
    *,
    _get_fn=None,
) -> bool:
    """Fetch *url* and compare the response body SHA-256 against *expected_hash*.

    If no ``expected_hash`` is provided the function simply returns ``False``
    (no mismatch can be detected without a reference).

    Args:
        url: The URL to fetch.
        expected_hash: Hex-encoded SHA-256 digest of the expected body.
        timeout: Request timeout in seconds.
        _get_fn: Injectable replacement for the HTTP GET callable.

    Returns:
        ``True`` when the body hash does **not** match ``expected_hash``
        (i.e. content has been injected / tampered with).  ``False`` when
        the hashes match or no reference hash was supplied.
    """
    if expected_hash is None:
        return False

    get_fn = _get_fn or _httpx_get
    resp = get_fn(url, timeout)
    actual_hash = hashlib.sha256(resp.content).hexdigest()
    return actual_hash != expected_hash
