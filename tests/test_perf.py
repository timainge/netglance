"""Tests for netglance.modules.perf and netglance.cli.perf."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.perf import app
from netglance.modules.perf import (
    detect_bufferbloat,
    discover_path_mtu,
    measure_jitter,
    run_performance_test,
)
from netglance.store.models import NetworkPerformanceResult, PingResult

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ping_result(host: str, latency_ms: float | None = 10.0) -> PingResult:
    """Build a synthetic PingResult."""
    return PingResult(
        host=host,
        is_alive=latency_ms is not None,
        avg_latency_ms=latency_ms,
        min_latency_ms=latency_ms,
        max_latency_ms=latency_ms,
        packet_loss=0.0 if latency_ms is not None else 1.0,
    )


def make_ping_fn(latencies: list[float | None]):
    """Return a _ping_fn that yields latencies in sequence (cycling)."""
    calls = [0]

    def ping_fn(host: str, count: int = 1, timeout: float = 2.0) -> PingResult:
        idx = calls[0] % len(latencies)
        calls[0] += 1
        return make_ping_result(host, latencies[idx])

    return ping_fn


# ---------------------------------------------------------------------------
# measure_jitter — constant latency
# ---------------------------------------------------------------------------


def test_measure_jitter_constant_latency():
    """Constant RTTs produce zero jitter."""
    ping_fn = make_ping_fn([20.0])
    jitter, p95, p99 = measure_jitter("1.1.1.1", count=10, _ping_fn=ping_fn)
    assert jitter == pytest.approx(0.0)
    assert p95 == pytest.approx(20.0)
    assert p99 == pytest.approx(20.0)


def test_measure_jitter_varying_latency():
    """Varying RTTs produce non-zero jitter."""
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
    ping_fn = make_ping_fn(latencies)
    jitter, p95, p99 = measure_jitter("1.1.1.1", count=5, _ping_fn=ping_fn)
    # Each consecutive diff is 10ms → mean = 10
    assert jitter == pytest.approx(10.0)


def test_measure_jitter_p95_accuracy():
    """P95 is calculated correctly."""
    # 20 identical values → p95 = that value
    ping_fn = make_ping_fn([15.0])
    _, p95, _ = measure_jitter("1.1.1.1", count=20, _ping_fn=ping_fn)
    assert p95 == pytest.approx(15.0)


def test_measure_jitter_p99_accuracy():
    """P99 with spread of values — p99 interpolates between sorted[98] and sorted[99]."""
    # 100 pings: 99 at 10ms, 1 at 100ms
    # p99 index = 0.99 * 99 = 98.01 → interpolates 10ms and 100ms → ~10.9
    latencies = [10.0] * 99 + [100.0]
    ping_fn = make_ping_fn(latencies)
    _, _, p99 = measure_jitter("1.1.1.1", count=100, _ping_fn=ping_fn)
    # Should be between 10 and 100 (interpolated at 99th percentile)
    assert p99 >= 10.0
    assert p99 <= 100.0
    # The max value (100ms) inflates p99 vs a flat distribution
    assert p99 > 10.0


def test_measure_jitter_all_packets_lost():
    """All lost packets return zeros gracefully."""
    ping_fn = make_ping_fn([None])
    jitter, p95, p99 = measure_jitter("1.1.1.1", count=5, _ping_fn=ping_fn)
    assert jitter == 0.0
    assert p95 == 0.0
    assert p99 == 0.0


def test_measure_jitter_single_reply():
    """Single successful reply returns jitter=0."""
    # First ping responds, rest are lost
    latencies = [10.0] + [None] * 9
    ping_fn = make_ping_fn(latencies)
    jitter, p95, p99 = measure_jitter("1.1.1.1", count=10, _ping_fn=ping_fn)
    assert jitter == 0.0
    assert p95 == pytest.approx(10.0)
    assert p99 == pytest.approx(10.0)


def test_measure_jitter_high_variance():
    """High-variance latencies produce large jitter."""
    latencies = [1.0, 100.0, 1.0, 100.0]
    ping_fn = make_ping_fn(latencies)
    jitter, _, _ = measure_jitter("1.1.1.1", count=4, _ping_fn=ping_fn)
    # Diffs: |100-1|=99, |1-100|=99, |100-1|=99 → mean=99
    assert jitter == pytest.approx(99.0)


# ---------------------------------------------------------------------------
# discover_path_mtu
# ---------------------------------------------------------------------------


def test_discover_path_mtu_all_pass():
    """All sizes pass → returns 1500."""
    send_fn = lambda host, size: True
    mtu = discover_path_mtu("1.1.1.1", _send_fn=send_fn)
    assert mtu == 1500


def test_discover_path_mtu_none_pass():
    """No sizes pass → returns minimum (68)."""
    send_fn = lambda host, size: False
    mtu = discover_path_mtu("1.1.1.1", _send_fn=send_fn)
    assert mtu == 68


def test_discover_path_mtu_boundary_1400():
    """MTU at 1400 — sizes <= 1400 pass, larger fail."""
    send_fn = lambda host, size: size <= 1400
    mtu = discover_path_mtu("1.1.1.1", _send_fn=send_fn)
    assert mtu == 1400


def test_discover_path_mtu_boundary_1000():
    """MTU at 1000."""
    send_fn = lambda host, size: size <= 1000
    mtu = discover_path_mtu("1.1.1.1", _send_fn=send_fn)
    assert mtu == 1000


def test_discover_path_mtu_boundary_576():
    """MTU at 576 — common PPPoE/tunnel scenario."""
    send_fn = lambda host, size: size <= 576
    mtu = discover_path_mtu("1.1.1.1", _send_fn=send_fn)
    assert mtu == 576


def test_discover_path_mtu_passes_host_to_send_fn():
    """send_fn receives the correct host."""
    received_hosts = []

    def send_fn(host, size):
        received_hosts.append(host)
        return True

    discover_path_mtu("8.8.8.8", _send_fn=send_fn)
    assert all(h == "8.8.8.8" for h in received_hosts)


# ---------------------------------------------------------------------------
# detect_bufferbloat
# ---------------------------------------------------------------------------


def test_detect_bufferbloat_none():
    """No significant latency increase → 'none'."""
    ping_fn = make_ping_fn([10.0])
    http_fn = MagicMock()
    rating, idle, loaded = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "none"
    assert idle == pytest.approx(10.0)
    assert loaded == pytest.approx(10.0)


def test_detect_bufferbloat_mild():
    """3x latency increase → 'mild'."""
    # First 10 pings are idle (10ms), next 10 are loaded (30ms = 3x)
    latencies = [10.0] * 10 + [30.0] * 10 + [10.0] * 100
    ping_fn = make_ping_fn(latencies)
    http_fn = MagicMock()
    rating, idle, loaded = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "mild"
    assert idle == pytest.approx(10.0)
    assert loaded == pytest.approx(30.0)


def test_detect_bufferbloat_severe():
    """5x latency increase → 'severe'."""
    latencies = [10.0] * 10 + [50.0] * 10 + [10.0] * 100
    ping_fn = make_ping_fn(latencies)
    http_fn = MagicMock()
    rating, idle, loaded = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "severe"
    assert idle == pytest.approx(10.0)
    assert loaded == pytest.approx(50.0)


def test_detect_bufferbloat_calls_http_fn():
    """http_fn is called to generate load."""
    ping_fn = make_ping_fn([10.0])
    http_fn = MagicMock()
    detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    http_fn.assert_called_once()


def test_detect_bufferbloat_exactly_4x_is_severe():
    """Exactly 4x idle → 'severe'."""
    latencies = [10.0] * 10 + [40.0] * 10
    ping_fn = make_ping_fn(latencies)
    http_fn = MagicMock()
    rating, _, _ = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "severe"


def test_detect_bufferbloat_exactly_2x_is_mild():
    """Exactly 2x idle → 'mild'."""
    latencies = [10.0] * 10 + [20.0] * 10
    ping_fn = make_ping_fn(latencies)
    http_fn = MagicMock()
    rating, _, _ = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "mild"


def test_detect_bufferbloat_just_under_2x_is_none():
    """Less than 2x idle → 'none'."""
    latencies = [10.0] * 10 + [19.0] * 10
    ping_fn = make_ping_fn(latencies)
    http_fn = MagicMock()
    rating, _, _ = detect_bufferbloat("1.1.1.1", _ping_fn=ping_fn, _http_fn=http_fn)
    assert rating == "none"


# ---------------------------------------------------------------------------
# run_performance_test — integration
# ---------------------------------------------------------------------------


def test_run_performance_test_returns_result():
    """run_performance_test returns a NetworkPerformanceResult."""
    ping_fn = make_ping_fn([15.0])
    send_fn = lambda host, size: True
    http_fn = MagicMock()
    result = run_performance_test(
        "1.1.1.1", _ping_fn=ping_fn, _send_fn=send_fn, _http_fn=http_fn
    )
    assert isinstance(result, NetworkPerformanceResult)
    assert result.target == "1.1.1.1"


def test_run_performance_test_mtu_in_result():
    """MTU is included in the result."""
    ping_fn = make_ping_fn([15.0])
    send_fn = lambda host, size: size <= 1400
    http_fn = MagicMock()
    result = run_performance_test(
        "1.1.1.1", _ping_fn=ping_fn, _send_fn=send_fn, _http_fn=http_fn
    )
    assert result.path_mtu == 1400


def test_run_performance_test_bufferbloat_in_result():
    """Bufferbloat rating is included in result."""
    ping_fn = make_ping_fn([10.0])
    send_fn = lambda host, size: True
    http_fn = MagicMock()
    result = run_performance_test(
        "1.1.1.1", _ping_fn=ping_fn, _send_fn=send_fn, _http_fn=http_fn
    )
    assert result.bufferbloat_rating in ("none", "mild", "severe")


def test_run_performance_test_timestamp():
    """Result has a timestamp."""
    ping_fn = make_ping_fn([10.0])
    send_fn = lambda host, size: True
    http_fn = MagicMock()
    result = run_performance_test(
        "1.1.1.1", _ping_fn=ping_fn, _send_fn=send_fn, _http_fn=http_fn
    )
    assert isinstance(result.timestamp, datetime)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "performance" in result.output.lower()


def test_cli_jitter_only():
    with patch("netglance.cli.perf.measure_jitter", return_value=(5.0, 20.0, 25.0)):
        result = runner.invoke(app, ["--jitter-only", "1.1.1.1"])
    assert result.exit_code == 0
    assert "Jitter" in result.output or "jitter" in result.output.lower()


def test_cli_mtu_only():
    with patch("netglance.cli.perf.discover_path_mtu", return_value=1500):
        result = runner.invoke(app, ["--mtu", "1.1.1.1"])
    assert result.exit_code == 0
    assert "1500" in result.output


def test_cli_bufferbloat_only():
    with patch("netglance.cli.perf.detect_bufferbloat", return_value=("none", 10.0, 10.0)):
        result = runner.invoke(app, ["--bufferbloat", "1.1.1.1"])
    assert result.exit_code == 0
    assert "NONE" in result.output.upper() or "MILD" in result.output.upper() or "SEVERE" in result.output.upper()


def test_cli_json_output():
    ping_fn = make_ping_fn([15.0])
    send_fn = lambda host, size: True
    http_fn = MagicMock()
    # Patch run_performance_test to avoid real network I/O
    fake_result = NetworkPerformanceResult(
        target="1.1.1.1",
        avg_latency_ms=15.0,
        jitter_ms=0.0,
        p95_latency_ms=15.0,
        p99_latency_ms=15.0,
        packet_loss_pct=0.0,
        path_mtu=1500,
        bufferbloat_rating="none",
        idle_latency_ms=15.0,
        loaded_latency_ms=15.0,
    )
    with patch("netglance.cli.perf.run_performance_test", return_value=fake_result):
        result = runner.invoke(app, ["--json", "1.1.1.1"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output.strip())
    assert "target" in data
    assert data["target"] == "1.1.1.1"


def test_cli_default_target():
    """No host arg uses 1.1.1.1 as default."""
    fake_result = NetworkPerformanceResult(
        target="1.1.1.1",
        avg_latency_ms=10.0,
        jitter_ms=0.0,
        p95_latency_ms=10.0,
        p99_latency_ms=10.0,
        packet_loss_pct=0.0,
        path_mtu=1500,
        bufferbloat_rating="none",
        idle_latency_ms=10.0,
        loaded_latency_ms=10.0,
    )
    with patch("netglance.cli.perf.run_performance_test", return_value=fake_result):
        result = runner.invoke(app, ["--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output.strip())
    assert data["target"] == "1.1.1.1"


def test_cli_jitter_json():
    with patch("netglance.cli.perf.measure_jitter", return_value=(5.0, 20.0, 25.0)):
        result = runner.invoke(app, ["--jitter-only", "--json", "1.1.1.1"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output.strip())
    assert "jitter_ms" in data
    assert "p95_ms" in data


def test_cli_mtu_json():
    with patch("netglance.cli.perf.discover_path_mtu", return_value=1500):
        result = runner.invoke(app, ["--mtu", "--json", "1.1.1.1"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output.strip())
    assert data["path_mtu"] == 1500


def test_cli_bufferbloat_json():
    with patch("netglance.cli.perf.detect_bufferbloat", return_value=("none", 10.0, 12.0)):
        result = runner.invoke(app, ["--bufferbloat", "--json", "1.1.1.1"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output.strip())
    assert "bufferbloat_rating" in data
    assert "idle_latency_ms" in data
    assert "loaded_latency_ms" in data
