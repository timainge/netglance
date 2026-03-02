"""Traffic and bandwidth monitoring using psutil network I/O counters."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import psutil

from netglance.store.models import BandwidthSample, InterfaceStats


# ---------------------------------------------------------------------------
# Thin wrapper around psutil -- easy to mock in tests
# ---------------------------------------------------------------------------


def _psutil_net_io_counters(pernic: bool = True) -> dict:
    """Thin wrapper around psutil.net_io_counters for mockability."""
    return psutil.net_io_counters(pernic=pernic)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_interface_stats(
    *,
    _counters_fn: Callable | None = None,
) -> list[InterfaceStats]:
    """Return current cumulative I/O counters for all network interfaces.

    Args:
        _counters_fn: Injectable replacement for psutil.net_io_counters
                      (for testing). Must return a dict mapping interface
                      names to named tuples with bytes_sent, bytes_recv,
                      packets_sent, packets_recv.

    Returns:
        List of InterfaceStats, one per interface.
    """
    counters_fn = _counters_fn or _psutil_net_io_counters
    counters = counters_fn(pernic=True)
    now = datetime.now()
    results: list[InterfaceStats] = []
    for iface, stats in counters.items():
        results.append(
            InterfaceStats(
                interface=iface,
                bytes_sent=stats.bytes_sent,
                bytes_recv=stats.bytes_recv,
                packets_sent=stats.packets_sent,
                packets_recv=stats.packets_recv,
                timestamp=now,
            )
        )
    return results


def sample_bandwidth(
    interface: str,
    interval: float = 1.0,
    *,
    _counters_fn: Callable | None = None,
    _sleep_fn: Callable | None = None,
) -> BandwidthSample:
    """Take two snapshots separated by *interval* seconds and compute rates.

    Args:
        interface: Name of the network interface to sample (e.g. "en0").
        interval: Seconds between snapshots.
        _counters_fn: Injectable replacement for psutil.net_io_counters.
        _sleep_fn: Injectable replacement for time.sleep (for testing).

    Returns:
        BandwidthSample with tx/rx bytes-per-second rates.

    Raises:
        KeyError: If *interface* is not found in the system counters.
    """
    counters_fn = _counters_fn or _psutil_net_io_counters
    sleep_fn = _sleep_fn or time.sleep

    snap1 = counters_fn(pernic=True)
    if interface not in snap1:
        raise KeyError(f"Interface {interface!r} not found. Available: {list(snap1)}")

    sleep_fn(interval)

    snap2 = counters_fn(pernic=True)
    if interface not in snap2:
        raise KeyError(f"Interface {interface!r} disappeared during sampling")

    s1 = snap1[interface]
    s2 = snap2[interface]

    elapsed = interval if interval > 0 else 1.0
    tx_rate = (s2.bytes_sent - s1.bytes_sent) / elapsed
    rx_rate = (s2.bytes_recv - s1.bytes_recv) / elapsed

    return BandwidthSample(
        interface=interface,
        tx_bytes_per_sec=tx_rate,
        rx_bytes_per_sec=rx_rate,
    )


def format_bytes(bytes_per_sec: float) -> str:
    """Format a bytes-per-second value with auto-scaled units.

    Returns human-readable string like "1.23 MB/s", "456 B/s", etc.
    """
    if bytes_per_sec < 0:
        bytes_per_sec = 0.0

    units = [
        (1024**3, "GB/s"),
        (1024**2, "MB/s"),
        (1024, "KB/s"),
    ]
    for threshold, label in units:
        if bytes_per_sec >= threshold:
            return f"{bytes_per_sec / threshold:.2f} {label}"
    return f"{bytes_per_sec:.0f} B/s"


def live_monitor(
    interface: str,
    callback: Callable[[BandwidthSample], None],
    interval: float = 1.0,
    *,
    _counters_fn: Callable | None = None,
    _sleep_fn: Callable | None = None,
    _should_stop: Callable[[], bool] | None = None,
) -> None:
    """Continuously sample bandwidth and invoke *callback* with each sample.

    This function blocks until interrupted or *_should_stop* returns True.

    Args:
        interface: Network interface name.
        callback: Called with each BandwidthSample.
        interval: Seconds between samples.
        _counters_fn: Injectable replacement for psutil.net_io_counters.
        _sleep_fn: Injectable replacement for time.sleep.
        _should_stop: Callable returning True to break the loop (for testing).
    """
    counters_fn = _counters_fn or _psutil_net_io_counters
    sleep_fn = _sleep_fn or time.sleep
    should_stop = _should_stop or (lambda: False)

    prev = counters_fn(pernic=True)
    if interface not in prev:
        raise KeyError(f"Interface {interface!r} not found. Available: {list(prev)}")

    while not should_stop():
        sleep_fn(interval)
        curr = counters_fn(pernic=True)
        if interface not in curr:
            break

        s1 = prev[interface]
        s2 = curr[interface]

        elapsed = interval if interval > 0 else 1.0
        sample = BandwidthSample(
            interface=interface,
            tx_bytes_per_sec=(s2.bytes_sent - s1.bytes_sent) / elapsed,
            rx_bytes_per_sec=(s2.bytes_recv - s1.bytes_recv) / elapsed,
        )
        callback(sample)
        prev = curr
