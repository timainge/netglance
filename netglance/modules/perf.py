"""Network performance assessment: jitter, MTU discovery, and bufferbloat detection."""

from __future__ import annotations

import statistics
import threading
import time
from typing import Callable

from netglance.store.models import NetworkPerformanceResult, PingResult


def _default_ping_fn(host: str, count: int = 1, timeout: float = 2.0) -> PingResult:
    """Default ping implementation using icmplib."""
    import icmplib

    resp = icmplib.ping(host, count=count, timeout=timeout, privileged=False)
    return PingResult(
        host=host,
        is_alive=resp.is_alive,
        avg_latency_ms=resp.avg_rtt if resp.is_alive else None,
        min_latency_ms=resp.min_rtt if resp.is_alive else None,
        max_latency_ms=resp.max_rtt if resp.is_alive else None,
        packet_loss=resp.packet_loss,
    )


def _default_send_fn(host: str, size: int) -> bool:
    """Default MTU probe using scapy with DF flag.

    Returns True if packet got through, False if fragmentation needed / no reply.
    """
    try:
        from scapy.all import IP, ICMP, sr1  # type: ignore

        # Payload size = total size - IP header (20) - ICMP header (8)
        payload_size = max(0, size - 28)
        pkt = IP(dst=host, flags="DF") / ICMP() / (b"X" * payload_size)
        reply = sr1(pkt, timeout=2, verbose=0)
        return reply is not None
    except Exception:
        return False


def _default_http_fn(url: str, duration_s: float) -> None:
    """Default HTTP load generator — download data for duration_s seconds."""
    import urllib.request

    deadline = time.monotonic() + duration_s
    try:
        with urllib.request.urlopen(url, timeout=duration_s + 5) as resp:
            while time.monotonic() < deadline:
                chunk = resp.read(65536)
                if not chunk:
                    break
    except Exception:
        pass


def measure_jitter(
    host: str,
    count: int = 50,
    *,
    _ping_fn: Callable | None = None,
) -> tuple[float, float, float]:
    """Send `count` pings and compute jitter statistics.

    Jitter = mean absolute difference between consecutive RTTs.

    Returns (jitter_ms, p95_latency_ms, p99_latency_ms).

    _ping_fn should accept (host, count=1, timeout=2.0) and return a PingResult.
    """
    ping_fn = _ping_fn or _default_ping_fn

    rtts: list[float] = []
    for _ in range(count):
        result = ping_fn(host, count=1, timeout=2.0)
        if result.is_alive and result.avg_latency_ms is not None:
            rtts.append(result.avg_latency_ms)

    if not rtts:
        # All packets lost — return zeros
        return 0.0, 0.0, 0.0

    if len(rtts) == 1:
        return 0.0, rtts[0], rtts[0]

    # Jitter: mean absolute difference between consecutive RTTs
    diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
    jitter = statistics.mean(diffs)

    # Percentiles
    sorted_rtts = sorted(rtts)
    n = len(sorted_rtts)

    def percentile(p: float) -> float:
        idx = (p / 100.0) * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_rtts[lo] * (1.0 - frac) + sorted_rtts[hi] * frac

    p95 = percentile(95)
    p99 = percentile(99)

    return jitter, p95, p99


def discover_path_mtu(
    host: str,
    *,
    _send_fn: Callable | None = None,
) -> int:
    """PMTUD via ICMP with DF flag.

    Binary search between 68 and 1500 bytes.
    _send_fn(host, size) should return True if packet got through, False otherwise.

    Returns MTU in bytes.
    """
    send_fn = _send_fn or _default_send_fn

    lo = 68
    hi = 1500

    # Quick check: does 1500 work?
    if send_fn(host, hi):
        return hi

    # Quick check: does minimum work?
    if not send_fn(host, lo):
        return lo

    # Binary search for the largest size that works
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if send_fn(host, mid):
            lo = mid
        else:
            hi = mid

    return lo


def detect_bufferbloat(
    target: str = "1.1.1.1",
    load_duration_s: float = 10.0,
    *,
    _ping_fn: Callable | None = None,
    _http_fn: Callable | None = None,
) -> tuple[str, float, float]:
    """Measure latency idle vs under load.

    1. Measure idle latency (ping target, 10 samples)
    2. Start load (_http_fn downloads data for load_duration_s)
    3. Measure loaded latency (ping target during load, 10 samples)
    4. Compare: if loaded > 4x idle → "severe", 2x-4x → "mild", else "none"

    Returns (rating, idle_latency_ms, loaded_latency_ms).
    rating: 'none', 'mild', 'severe'
    """
    ping_fn = _ping_fn or _default_ping_fn
    http_fn = _http_fn or (
        lambda: _default_http_fn("http://speed.cloudflare.com/__down?bytes=104857600", load_duration_s)
    )

    # Step 1: Measure idle latency
    idle_samples: list[float] = []
    for _ in range(10):
        result = ping_fn(target, count=1, timeout=2.0)
        if result.is_alive and result.avg_latency_ms is not None:
            idle_samples.append(result.avg_latency_ms)

    idle_latency = statistics.mean(idle_samples) if idle_samples else 0.0

    # Step 2: Start load in background thread
    load_thread = threading.Thread(target=http_fn, daemon=True)
    load_thread.start()

    # Brief pause to let the load ramp up
    time.sleep(1.0)

    # Step 3: Measure loaded latency
    loaded_samples: list[float] = []
    for _ in range(10):
        result = ping_fn(target, count=1, timeout=2.0)
        if result.is_alive and result.avg_latency_ms is not None:
            loaded_samples.append(result.avg_latency_ms)

    load_thread.join(timeout=load_duration_s + 5)

    loaded_latency = statistics.mean(loaded_samples) if loaded_samples else 0.0

    # Step 4: Rate
    if idle_latency == 0.0:
        rating = "none"
    elif loaded_latency >= idle_latency * 4.0:
        rating = "severe"
    elif loaded_latency >= idle_latency * 2.0:
        rating = "mild"
    else:
        rating = "none"

    return rating, idle_latency, loaded_latency


def run_performance_test(
    target: str = "1.1.1.1",
    *,
    _ping_fn: Callable | None = None,
    _send_fn: Callable | None = None,
    _http_fn: Callable | None = None,
) -> NetworkPerformanceResult:
    """Full performance assessment. Main entry point.

    Runs jitter measurement, MTU discovery, and bufferbloat detection.
    """
    ping_fn = _ping_fn or _default_ping_fn

    # Jitter + percentiles (50 pings)
    jitter, p95, p99 = measure_jitter(target, count=50, _ping_fn=ping_fn)

    # Average latency and packet loss from a quick ping burst
    result = ping_fn(target, count=10, timeout=2.0)
    avg_latency = result.avg_latency_ms if result.avg_latency_ms is not None else 0.0
    packet_loss_pct = result.packet_loss * 100.0

    # MTU discovery
    path_mtu = discover_path_mtu(target, _send_fn=_send_fn)

    # Bufferbloat
    rating, idle_ms, loaded_ms = detect_bufferbloat(
        target, _ping_fn=ping_fn, _http_fn=_http_fn
    )

    return NetworkPerformanceResult(
        target=target,
        avg_latency_ms=avg_latency,
        jitter_ms=jitter,
        p95_latency_ms=p95,
        p99_latency_ms=p99,
        packet_loss_pct=packet_loss_pct,
        path_mtu=path_mtu,
        bufferbloat_rating=rating,
        idle_latency_ms=idle_ms,
        loaded_latency_ms=loaded_ms,
    )
