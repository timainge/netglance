"""Internet speed testing module (Cloudflare, Ookla, iperf3)."""

from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
import time
from typing import Any, Callable

import httpx

from netglance.store.models import SpeedTestResult

DEFAULT_SERVER = "speed.cloudflare.com"

# Download sizes for adaptive testing (bytes)
_DOWNLOAD_SIZES = [1_000_000, 10_000_000, 25_000_000, 100_000_000]


def _default_http_fn(method: str, url: str, **kwargs: Any) -> tuple[float, int]:
    """Make an HTTP request and return (elapsed_seconds, bytes_transferred).

    For GET requests, counts response bytes received.
    For POST requests, counts request body bytes sent.
    """
    with httpx.Client(timeout=60.0) as client:
        if method == "GET":
            start = time.perf_counter()
            with client.stream("GET", url, **kwargs) as resp:
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
            elapsed = time.perf_counter() - start
            return elapsed, total
        else:  # POST
            content = kwargs.pop("content", b"")
            start = time.perf_counter()
            client.post(url, content=content, **kwargs)
            elapsed = time.perf_counter() - start
            return elapsed, len(content)


def _cache_bust() -> str:
    """Return a random cache-busting query string value."""
    return str(random.randint(100_000, 999_999))


def test_download(
    server: str = DEFAULT_SERVER,
    duration_s: float = 10.0,
    *,
    _http_fn: Callable | None = None,
) -> tuple[float, int]:
    """Test download speed against the given server.

    Uses adaptive sizing: starts with small chunks and increases if the
    connection is fast, aiming to fill the requested duration.

    Args:
        server: Hostname to test against.
        duration_s: Approximate target duration for the test in seconds.
        _http_fn: Injectable HTTP function (method, url, **kwargs) -> (elapsed_s, bytes).
                  Defaults to real httpx-based implementation.

    Returns:
        Tuple of (megabits_per_second, total_bytes_downloaded).
    """
    http_fn = _http_fn or _default_http_fn

    total_bytes = 0
    total_time = 0.0
    start_wall = time.perf_counter()

    for size in _DOWNLOAD_SIZES:
        if time.perf_counter() - start_wall >= duration_s:
            break
        url = f"https://{server}/__down?bytes={size}&r={_cache_bust()}"
        elapsed, received = http_fn("GET", url)
        total_bytes += received
        total_time += elapsed

        # If this chunk alone took longer than half the budget, stop scaling up
        if total_time >= duration_s * 0.5:
            break

    if total_time <= 0:
        return 0.0, 0

    mbps = (total_bytes * 8) / (total_time * 1_000_000)
    return round(mbps, 2), total_bytes


def test_upload(
    server: str = DEFAULT_SERVER,
    duration_s: float = 10.0,
    payload_size: int = 1_000_000,
    *,
    _http_fn: Callable | None = None,
) -> tuple[float, int]:
    """Test upload speed against the given server.

    Sends random binary payloads via POST requests, repeating until the
    duration budget is consumed.

    Args:
        server: Hostname to test against.
        duration_s: Approximate target duration for the test in seconds.
        payload_size: Bytes per POST request.
        _http_fn: Injectable HTTP function (method, url, **kwargs) -> (elapsed_s, bytes).

    Returns:
        Tuple of (megabits_per_second, total_bytes_uploaded).
    """
    http_fn = _http_fn or _default_http_fn

    payload = os.urandom(payload_size)
    total_bytes = 0
    total_time = 0.0
    url = f"https://{server}/__up?r={_cache_bust()}"
    start_wall = time.perf_counter()

    while time.perf_counter() - start_wall < duration_s:
        elapsed, sent = http_fn("POST", url, content=payload)
        total_bytes += sent
        total_time += elapsed

    if total_time <= 0:
        return 0.0, 0

    mbps = (total_bytes * 8) / (total_time * 1_000_000)
    return round(mbps, 2), total_bytes


def test_latency(
    server: str = DEFAULT_SERVER,
    count: int = 20,
    *,
    _http_fn: Callable | None = None,
) -> tuple[float, float | None]:
    """Measure latency (RTT) to the server with small requests.

    Args:
        server: Hostname to test against.
        count: Number of probe requests to send.
        _http_fn: Injectable HTTP function (method, url, **kwargs) -> (elapsed_s, bytes).

    Returns:
        Tuple of (median_latency_ms, jitter_ms). Jitter is None if fewer
        than 2 samples succeed.
    """
    http_fn = _http_fn or _default_http_fn

    samples: list[float] = []
    url = f"https://{server}/__down?bytes=1&r={_cache_bust()}"

    for _ in range(count):
        try:
            elapsed, _ = http_fn("GET", url)
            samples.append(elapsed * 1000.0)  # convert to ms
        except Exception:
            continue

    if not samples:
        return 0.0, None

    median_ms = statistics.median(samples)

    jitter: float | None = None
    if len(samples) >= 2:
        diffs = [abs(samples[i + 1] - samples[i]) for i in range(len(samples) - 1)]
        jitter = round(statistics.mean(diffs), 2)

    return round(median_ms, 2), jitter


def run_speedtest(
    server: str | None = None,
    provider: str = "cloudflare",
    duration_s: float = 10.0,
    *,
    _http_fn: Callable | None = None,
) -> SpeedTestResult:
    """Run a full speed test: latency + download + upload.

    This is the main entry point for Cloudflare-based speed testing.

    Args:
        server: Override the test server hostname.
        provider: Provider label stored in the result (default "cloudflare").
        duration_s: Target duration for download and upload phases.
        _http_fn: Injectable HTTP function for testing.

    Returns:
        SpeedTestResult with all measurements populated.
    """
    host = server or DEFAULT_SERVER

    latency_ms, jitter_ms = test_latency(host, _http_fn=_http_fn)
    download_mbps, download_bytes = test_download(host, duration_s=duration_s, _http_fn=_http_fn)
    upload_mbps, upload_bytes = test_upload(host, duration_s=duration_s, _http_fn=_http_fn)

    return SpeedTestResult(
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        server=host,
        server_location="",
        provider=provider,
        download_bytes=download_bytes,
        upload_bytes=upload_bytes,
    )


def run_speedtest_ookla(*, _subprocess_fn: Callable | None = None) -> SpeedTestResult:
    """Run a speed test via the Ookla speedtest CLI.

    The binary must be installed and available as `speedtest` on PATH.

    Args:
        _subprocess_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        SpeedTestResult populated from Ookla JSON output.

    Raises:
        FileNotFoundError: If the `speedtest` binary is not found on PATH.
        RuntimeError: If the binary exits with an error or produces invalid JSON.
    """
    run_fn = _subprocess_fn or subprocess.run

    try:
        result = run_fn(
            ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "Ookla speedtest CLI not found. Install it from https://www.speedtest.net/apps/cli"
        )

    if result.returncode != 0:
        raise RuntimeError(f"Ookla speedtest failed: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse Ookla output: {exc}") from exc

    # Ookla reports bytes/s; convert to megabits/s
    download_mbps = round(data["download"]["bandwidth"] * 8 / 1_000_000, 2)
    upload_mbps = round(data["upload"]["bandwidth"] * 8 / 1_000_000, 2)
    latency_ms = float(data["ping"]["latency"])
    jitter_ms = float(data.get("ping", {}).get("jitter", 0)) or None

    server_info = data.get("server", {})
    server_name = server_info.get("host", "")
    server_location = f"{server_info.get('location', '')} ({server_info.get('country', '')})".strip(
        " ()"
    )

    return SpeedTestResult(
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        server=server_name,
        server_location=server_location,
        provider="ookla",
        download_bytes=data["download"].get("bytes", 0),
        upload_bytes=data["upload"].get("bytes", 0),
    )


def run_speedtest_iperf3(
    server: str,
    port: int = 5201,
    duration_s: float = 10.0,
    *,
    _client_fn: Callable | None = None,
) -> SpeedTestResult:
    """Run a LAN speed test via iperf3.

    Requires iperf3 to be installed. Runs a bidirectional test against the
    given server.

    Args:
        server: iperf3 server IP or hostname.
        port: iperf3 server port (default 5201).
        duration_s: Duration of each test direction in seconds.
        _client_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        SpeedTestResult populated from iperf3 JSON output.

    Raises:
        FileNotFoundError: If iperf3 is not installed.
        RuntimeError: If iperf3 exits with an error or produces invalid output.
    """
    run_fn = _client_fn or subprocess.run

    def _run_iperf(reverse: bool = False) -> dict:
        cmd = [
            "iperf3",
            "-c", server,
            "-p", str(port),
            "-t", str(int(duration_s)),
            "--json",
        ]
        if reverse:
            cmd.append("-R")

        try:
            result = run_fn(cmd, capture_output=True, text=True, timeout=duration_s + 30)
        except FileNotFoundError:
            raise FileNotFoundError(
                "iperf3 not found. Install it with: brew install iperf3 (macOS) "
                "or apt install iperf3 (Linux)"
            )

        if result.returncode != 0:
            raise RuntimeError(f"iperf3 failed: {result.stderr.strip()}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse iperf3 output: {exc}") from exc

    # Download (reverse: server sends to us)
    dl_data = _run_iperf(reverse=True)
    dl_bps = dl_data["end"]["sum_received"]["bits_per_second"]
    download_mbps = round(dl_bps / 1_000_000, 2)
    download_bytes = dl_data["end"]["sum_received"].get("bytes", 0)

    # Upload (normal: we send to server)
    ul_data = _run_iperf(reverse=False)
    ul_bps = ul_data["end"]["sum_sent"]["bits_per_second"]
    upload_mbps = round(ul_bps / 1_000_000, 2)
    upload_bytes = ul_data["end"]["sum_sent"].get("bytes", 0)

    # Latency from iperf3 RTT (if available)
    rtt_ms: float = 0.0
    try:
        rtt_us = ul_data["end"]["streams"][0]["sender"]["mean_rtt"]
        rtt_ms = round(rtt_us / 1000.0, 2)
    except (KeyError, IndexError):
        pass

    return SpeedTestResult(
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        latency_ms=rtt_ms,
        jitter_ms=None,
        server=server,
        server_location="",
        provider="iperf3",
        download_bytes=download_bytes,
        upload_bytes=upload_bytes,
    )
