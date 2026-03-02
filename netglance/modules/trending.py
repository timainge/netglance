"""Shared charting and metric query helpers for time-series data."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from netglance.store.db import Store
    from netglance.store.models import BandwidthSample, PingResult, SpeedTestResult

# Unicode block characters for sparklines (8 levels)
_BLOCKS = "▁▂▃▄▅▆▇█"


def parse_period(period: str) -> datetime:
    """Convert '1h', '6h', '24h', '7d', '30d' to a since-datetime.

    Returns datetime.now(UTC) minus the specified duration.

    Raises:
        ValueError: If the period string is not recognized.
    """
    match = re.fullmatch(r"(\d+)([hd])", period.strip())
    if not match:
        raise ValueError(
            f"Unrecognized period format: {period!r}. "
            "Expected format like '1h', '6h', '24h', '7d', '30d'."
        )
    amount = int(match.group(1))
    unit = match.group(2)
    now = datetime.now(timezone.utc)
    if unit == "h":
        return now - timedelta(hours=amount)
    else:  # unit == "d"
        return now - timedelta(days=amount)


def render_chart(
    series: list[dict],
    title: str,
    ylabel: str = "",
    width: int = 80,
    height: int = 20,
    *,
    _plotext=None,
) -> str:
    """Render a plotext line chart from metric series data.

    Args:
        series: List of {"ts": str, "value": float} dicts.
        title: Chart title.
        ylabel: Y-axis label.
        width: Chart width in characters.
        height: Chart height in characters.
        _plotext: Injectable plotext module for testing.

    Returns:
        The chart as a string.
    """
    try:
        plt = _plotext
        if plt is None:
            import plotext as _plt
            plt = _plt
    except ImportError:
        # Graceful fallback if plotext not installed
        lines = [f"[{title}]"]
        if not series:
            lines.append("(no data)")
        else:
            values = [p["value"] for p in series]
            lines.append(f"min={min(values):.2f}  max={max(values):.2f}  n={len(values)}")
        return "\n".join(lines)

    plt.clf()
    plt.plot_size(width, height)
    plt.title(title)
    if ylabel:
        plt.ylabel(ylabel)

    if series:
        xs = list(range(len(series)))
        ys = [p["value"] for p in series]
        plt.plot(xs, ys)
    else:
        plt.plot([], [])

    return plt.build()


def sparkline(values: list[float], width: int = 40) -> str:
    """Mini inline sparkline using Unicode block characters (▁▂▃▄▅▆▇█).

    Maps values to 8 block levels. Returns a string of `width` characters
    using the last `width` values.

    Args:
        values: List of numeric values.
        width: Number of characters in the output sparkline.

    Returns:
        A string of Unicode block characters.
    """
    if not values:
        return " " * width

    # Use the last `width` values
    subset = values[-width:] if len(values) > width else values

    min_val = min(subset)
    max_val = max(subset)
    val_range = max_val - min_val

    chars = []
    for v in subset:
        if val_range == 0:
            idx = 4  # middle block when all values are equal
        else:
            idx = int((v - min_val) / val_range * 7)
            idx = max(0, min(7, idx))
        chars.append(_BLOCKS[idx])

    # Pad to width if we have fewer than width values
    result = "".join(chars)
    if len(result) < width:
        result = result.rjust(width)

    return result


def emit_ping_metrics(result: "PingResult", store: "Store") -> None:
    """Save ping result as metrics to the store.

    Saves ping.{host}.latency_ms and ping.{host}.packet_loss.
    Host dots are replaced with underscores in the metric name.

    Args:
        result: PingResult to emit.
        store: Store instance to save to.
    """
    safe_host = result.host.replace(".", "_")
    samples: list[tuple[str, float, dict | None]] = []

    if result.avg_latency_ms is not None:
        samples.append((f"ping.{safe_host}.latency_ms", result.avg_latency_ms, None))

    samples.append((f"ping.{safe_host}.packet_loss", result.packet_loss, None))

    store.save_metrics_batch(samples)


def emit_speed_metrics(result: "SpeedTestResult", store: "Store") -> None:
    """Save speed test result as metrics to the store.

    Saves speed.download_mbps, speed.upload_mbps, speed.latency_ms.

    Args:
        result: SpeedTestResult to emit.
        store: Store instance to save to.
    """
    samples: list[tuple[str, float, dict | None]] = [
        ("speed.download_mbps", result.download_mbps, None),
        ("speed.upload_mbps", result.upload_mbps, None),
        ("speed.latency_ms", result.latency_ms, None),
    ]
    store.save_metrics_batch(samples)


def emit_traffic_metrics(sample: "BandwidthSample", store: "Store") -> None:
    """Save bandwidth sample as metrics to the store.

    Saves traffic.{interface}.rx_bytes_per_sec and traffic.{interface}.tx_bytes_per_sec.

    Args:
        sample: BandwidthSample to emit.
        store: Store instance to save to.
    """
    iface = sample.interface
    samples: list[tuple[str, float, dict | None]] = [
        (f"traffic.{iface}.rx_bytes_per_sec", sample.rx_bytes_per_sec, None),
        (f"traffic.{iface}.tx_bytes_per_sec", sample.tx_bytes_per_sec, None),
    ]
    store.save_metrics_batch(samples)


def emit_wifi_metrics(signal_dbm: int, ssid: str, store: "Store") -> None:
    """Save wifi signal strength as a metric to the store.

    Saves wifi.signal_dbm with tags {"ssid": ssid}.

    Args:
        signal_dbm: Signal strength in dBm.
        ssid: Network SSID name.
        store: Store instance to save to.
    """
    store.save_metric("wifi.signal_dbm", float(signal_dbm), tags={"ssid": ssid})
