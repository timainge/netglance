"""Tests for the speed module."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.speed import app
from netglance.modules.speed import (
    run_speedtest,
    run_speedtest_iperf3,
    run_speedtest_ookla,
    test_download as speed_test_download,
    test_latency as speed_test_latency,
    test_upload as speed_test_upload,
)
from netglance.store.models import SpeedTestResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers / mock factories
# ---------------------------------------------------------------------------

def make_http_fn(elapsed: float = 0.5, size: int = 5_000_000):
    """Return a fake _http_fn that returns (elapsed_s, size_bytes)."""
    def _fn(method: str, url: str, **kwargs: Any) -> tuple[float, int]:
        content = kwargs.get("content", b"")
        if method == "POST":
            return elapsed, len(content)
        return elapsed, size
    return _fn


def make_latency_http_fn(elapsed: float = 0.030):
    """Return a fake _http_fn that simulates latency probes."""
    def _fn(method: str, url: str, **kwargs: Any) -> tuple[float, int]:
        return elapsed, 1
    return _fn


def make_ookla_result(
    dl_bandwidth: int = 12_500_000,  # bytes/s → 100 Mbps
    ul_bandwidth: int = 6_250_000,   # bytes/s → 50 Mbps
    latency: float = 10.0,
    jitter: float = 2.0,
) -> dict:
    return {
        "download": {"bandwidth": dl_bandwidth, "bytes": dl_bandwidth * 10},
        "upload": {"bandwidth": ul_bandwidth, "bytes": ul_bandwidth * 10},
        "ping": {"latency": latency, "jitter": jitter},
        "server": {"host": "speedtest.example.com", "location": "New York", "country": "US"},
    }


def make_iperf3_result(
    bits_per_second: float = 1_000_000_000,  # 1 Gbps
    rtt_us: int = 500,
    total_bytes: int = 10_000_000,
) -> dict:
    return {
        "end": {
            "sum_received": {"bits_per_second": bits_per_second, "bytes": total_bytes},
            "sum_sent": {"bits_per_second": bits_per_second, "bytes": total_bytes},
            "streams": [{"sender": {"mean_rtt": rtt_us}}],
        }
    }


class FakeProcess:
    """Simulates a subprocess.CompletedProcess result."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ---------------------------------------------------------------------------
# test_download
# ---------------------------------------------------------------------------

def test_download_returns_mbps_and_bytes():
    http_fn = make_http_fn(elapsed=1.0, size=10_000_000)
    mbps, total_bytes = speed_test_download(_http_fn=http_fn)
    assert total_bytes > 0
    # 10 MB in 1s = 80 Mbps
    assert mbps == pytest.approx(80.0, rel=0.01)


def test_download_custom_server():
    called_urls = []

    def _fn(method, url, **kwargs):
        called_urls.append(url)
        return 1.0, 1_000_000

    speed_test_download(server="custom.example.com", _http_fn=_fn)
    assert all("custom.example.com" in u for u in called_urls)


def test_download_zero_time_guard():
    """If http_fn returns 0 elapsed, result should be 0 with no crash."""

    def _fn(method, url, **kwargs):
        return 0.0, 0

    mbps, total = speed_test_download(_http_fn=_fn)
    assert mbps == 0.0
    assert total == 0


def test_download_short_duration_stops_early():
    """With duration_s=0, the loop exits immediately after first chunk."""
    call_count = 0

    def _fn(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return 5.0, 10_000_000  # 5s per chunk, already over any small budget

    speed_test_download(duration_s=2.0, _http_fn=_fn)
    # Should stop after 1 chunk because 5s > 2*0.5
    assert call_count == 1


# ---------------------------------------------------------------------------
# test_upload
# ---------------------------------------------------------------------------

def test_upload_returns_mbps_and_bytes():
    elapsed_per_call = 0.5
    payload_size = 1_000_000

    calls = [0]

    def _fn(method, url, **kwargs):
        calls[0] += 1
        if calls[0] >= 3:
            # Simulate time passing so the loop exits
            return 100.0, len(kwargs.get("content", b""))
        return elapsed_per_call, len(kwargs.get("content", b""))

    mbps, total_bytes = speed_test_upload(duration_s=0.5, payload_size=payload_size, _http_fn=_fn)
    assert total_bytes >= payload_size
    assert mbps > 0


def test_upload_custom_server():
    called_urls = []

    def _fn(method, url, **kwargs):
        called_urls.append(url)
        return 100.0, len(kwargs.get("content", b""))  # long elapsed to exit loop

    speed_test_upload(server="myserver.local", duration_s=0.1, _http_fn=_fn)
    assert all("myserver.local" in u for u in called_urls)


def test_upload_zero_time_guard():
    call_count = [0]

    def _fn(method, url, **kwargs):
        call_count[0] += 1
        return 100.0, 0  # 0 bytes, long time

    mbps, total = speed_test_upload(duration_s=0.01, _http_fn=_fn)
    assert mbps == 0.0 or total == 0


# ---------------------------------------------------------------------------
# test_latency
# ---------------------------------------------------------------------------

def test_latency_returns_median_and_jitter():
    times = [0.020, 0.025, 0.022, 0.018, 0.030]
    idx = [0]

    def _fn(method, url, **kwargs):
        t = times[idx[0] % len(times)]
        idx[0] += 1
        return t, 1

    median_ms, jitter_ms = speed_test_latency(count=5, _http_fn=_fn)
    assert 18.0 <= median_ms <= 30.0
    assert jitter_ms is not None
    assert jitter_ms >= 0.0


def test_latency_single_sample_no_jitter():
    def _fn(method, url, **kwargs):
        return 0.015, 1

    median_ms, jitter_ms = speed_test_latency(count=1, _http_fn=_fn)
    assert median_ms == pytest.approx(15.0, abs=1.0)
    assert jitter_ms is None


def test_latency_handles_http_errors_gracefully():
    calls = [0]

    def _fn(method, url, **kwargs):
        calls[0] += 1
        if calls[0] % 2 == 0:
            raise ConnectionError("network error")
        return 0.020, 1

    # Should not raise; should return results from the successful calls
    median_ms, jitter_ms = speed_test_latency(count=4, _http_fn=_fn)
    assert median_ms > 0


def test_latency_all_failures_returns_zero():
    def _fn(method, url, **kwargs):
        raise ConnectionError("always fails")

    median_ms, jitter_ms = speed_test_latency(count=5, _http_fn=_fn)
    assert median_ms == 0.0
    assert jitter_ms is None


# ---------------------------------------------------------------------------
# run_speedtest (Cloudflare full)
# ---------------------------------------------------------------------------

def test_run_speedtest_returns_speed_test_result():
    http_fn = make_http_fn(elapsed=1.0, size=10_000_000)
    result = run_speedtest(_http_fn=http_fn)
    assert isinstance(result, SpeedTestResult)
    assert result.provider == "cloudflare"


def test_run_speedtest_custom_server():
    http_fn = make_http_fn(elapsed=0.5, size=5_000_000)
    result = run_speedtest(server="myspeed.test", _http_fn=http_fn)
    assert result.server == "myspeed.test"


def test_run_speedtest_custom_provider_label():
    http_fn = make_http_fn(elapsed=0.5, size=5_000_000)
    result = run_speedtest(provider="custom", _http_fn=http_fn)
    assert result.provider == "custom"


def test_run_speedtest_has_all_fields():
    http_fn = make_http_fn(elapsed=0.5, size=5_000_000)
    result = run_speedtest(_http_fn=http_fn)
    assert result.download_mbps > 0
    assert result.upload_mbps > 0
    assert result.latency_ms >= 0
    assert result.download_bytes > 0
    assert result.upload_bytes > 0
    assert isinstance(result.timestamp, datetime)


# ---------------------------------------------------------------------------
# run_speedtest_ookla
# ---------------------------------------------------------------------------

def test_ookla_parses_json_output():
    output = json.dumps(make_ookla_result())

    def _subprocess_fn(cmd, **kwargs):
        return FakeProcess(stdout=output)

    result = run_speedtest_ookla(_subprocess_fn=_subprocess_fn)
    assert isinstance(result, SpeedTestResult)
    assert result.provider == "ookla"
    assert result.download_mbps == pytest.approx(100.0, rel=0.01)
    assert result.upload_mbps == pytest.approx(50.0, rel=0.01)
    assert result.latency_ms == pytest.approx(10.0)
    assert result.jitter_ms == pytest.approx(2.0)


def test_ookla_raises_file_not_found():
    def _subprocess_fn(cmd, **kwargs):
        raise FileNotFoundError("speedtest not found")

    with pytest.raises(FileNotFoundError, match="Ookla speedtest CLI not found"):
        run_speedtest_ookla(_subprocess_fn=_subprocess_fn)


def test_ookla_raises_runtime_error_on_nonzero_exit():
    def _subprocess_fn(cmd, **kwargs):
        return FakeProcess(returncode=1, stderr="license not accepted")

    with pytest.raises(RuntimeError, match="Ookla speedtest failed"):
        run_speedtest_ookla(_subprocess_fn=_subprocess_fn)


def test_ookla_raises_runtime_error_on_invalid_json():
    def _subprocess_fn(cmd, **kwargs):
        return FakeProcess(stdout="not valid json")

    with pytest.raises(RuntimeError, match="Could not parse Ookla output"):
        run_speedtest_ookla(_subprocess_fn=_subprocess_fn)


def test_ookla_server_location_formatted():
    output = json.dumps(make_ookla_result())

    def _subprocess_fn(cmd, **kwargs):
        return FakeProcess(stdout=output)

    result = run_speedtest_ookla(_subprocess_fn=_subprocess_fn)
    assert result.server == "speedtest.example.com"
    # Location should contain city and country info
    assert "New York" in result.server_location


# ---------------------------------------------------------------------------
# run_speedtest_iperf3
# ---------------------------------------------------------------------------

def test_iperf3_parses_json_output():
    output = json.dumps(make_iperf3_result(bits_per_second=1_000_000_000))

    def _client_fn(cmd, **kwargs):
        return FakeProcess(stdout=output)

    result = run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)
    assert isinstance(result, SpeedTestResult)
    assert result.provider == "iperf3"
    assert result.download_mbps == pytest.approx(1000.0, rel=0.01)
    assert result.upload_mbps == pytest.approx(1000.0, rel=0.01)


def test_iperf3_rtt_converted_to_ms():
    output = json.dumps(make_iperf3_result(rtt_us=1000))  # 1000 µs = 1 ms

    def _client_fn(cmd, **kwargs):
        return FakeProcess(stdout=output)

    result = run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)
    assert result.latency_ms == pytest.approx(1.0)


def test_iperf3_raises_file_not_found():
    def _client_fn(cmd, **kwargs):
        raise FileNotFoundError("iperf3 not found")

    with pytest.raises(FileNotFoundError, match="iperf3 not found"):
        run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)


def test_iperf3_raises_runtime_error_on_nonzero_exit():
    def _client_fn(cmd, **kwargs):
        return FakeProcess(returncode=1, stderr="connection refused")

    with pytest.raises(RuntimeError, match="iperf3 failed"):
        run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)


def test_iperf3_raises_runtime_error_on_invalid_json():
    def _client_fn(cmd, **kwargs):
        return FakeProcess(stdout="bad json")

    with pytest.raises(RuntimeError, match="Could not parse iperf3 output"):
        run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)


def test_iperf3_custom_port_and_duration():
    called_cmds = []

    def _client_fn(cmd, **kwargs):
        called_cmds.append(cmd)
        return FakeProcess(stdout=json.dumps(make_iperf3_result()))

    run_speedtest_iperf3("10.0.0.1", port=9999, duration_s=30.0, _client_fn=_client_fn)
    # Both download and upload calls
    assert len(called_cmds) == 2
    assert "-p" in called_cmds[0]
    port_idx = called_cmds[0].index("-p")
    assert called_cmds[0][port_idx + 1] == "9999"


def test_iperf3_missing_rtt_field_uses_zero():
    """If iperf3 JSON lacks RTT data, latency should default to 0.0."""
    data = make_iperf3_result()
    # Remove the streams RTT info
    del data["end"]["streams"]
    output = json.dumps(data)

    def _client_fn(cmd, **kwargs):
        return FakeProcess(stdout=output)

    result = run_speedtest_iperf3("192.168.1.1", _client_fn=_client_fn)
    assert result.latency_ms == 0.0


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def _make_cli_http_fn(elapsed: float = 0.5, size: int = 5_000_000):
    """Return a patched http function suitable for CLI tests."""
    def _fn(method, url, **kwargs):
        content = kwargs.get("content", b"")
        if method == "POST":
            return elapsed, len(content)
        return elapsed, size
    return _fn


def test_cli_default_speed_test(tmp_path):
    """CLI should run a full speed test and print results."""
    http_fn = _make_cli_http_fn()

    with patch("netglance.modules.speed._default_http_fn", http_fn), \
         patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.save_result.return_value = 1
        result = runner.invoke(app, ["--no-save"])

    assert result.exit_code == 0
    assert "Download" in result.output or "Speed" in result.output


def test_cli_json_output():
    """--json flag should produce parseable JSON."""
    http_fn = _make_cli_http_fn()

    with patch("netglance.modules.speed._default_http_fn", http_fn), \
         patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.save_result.return_value = 1
        result = runner.invoke(app, ["--json", "--no-save"])

    assert result.exit_code == 0
    # Should be parseable JSON
    data = json.loads(result.output)
    assert "download_mbps" in data


def test_cli_ookla_provider():
    ookla_output = json.dumps(make_ookla_result())

    def _subprocess_fn(cmd, **kwargs):
        return FakeProcess(stdout=ookla_output)

    with patch("netglance.modules.speed.subprocess.run", side_effect=_subprocess_fn), \
         patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.save_result.return_value = 1
        result = runner.invoke(app, ["--provider", "ookla", "--no-save"])

    assert result.exit_code == 0


def test_cli_iperf3_requires_server():
    """iperf3 provider without --server should exit with error."""
    result = runner.invoke(app, ["--provider", "iperf3"])
    assert result.exit_code != 0
    assert "required" in result.output.lower() or "server" in result.output.lower()


def test_cli_iperf3_provider_with_server():
    iperf_output = json.dumps(make_iperf3_result())

    def _client_fn(cmd, **kwargs):
        return FakeProcess(stdout=iperf_output)

    with patch("netglance.modules.speed.subprocess.run", side_effect=_client_fn), \
         patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.save_result.return_value = 1
        result = runner.invoke(app, ["--provider", "iperf3", "--server", "192.168.1.1", "--no-save"])

    assert result.exit_code == 0


def test_cli_history_empty(tmp_path):
    """history subcommand with no data should print empty message."""
    with patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.get_results.return_value = []
        result = runner.invoke(app, ["history"])

    assert result.exit_code == 0
    assert "No speed test" in result.output


def test_cli_history_shows_table():
    """history subcommand with data should render a table."""
    rows = [
        {
            "download_mbps": 95.5,
            "upload_mbps": 45.2,
            "latency_ms": 12.3,
            "jitter_ms": 1.5,
            "provider": "cloudflare",
            "server": "speed.cloudflare.com",
            "timestamp": "2026-02-18T10:00:00",
        }
    ]

    with patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.get_results.return_value = rows
        result = runner.invoke(app, ["history"])

    assert result.exit_code == 0
    assert "95.5" in result.output or "Download" in result.output


def test_cli_history_json():
    """history --json should produce parseable JSON."""
    rows = [
        {
            "download_mbps": 80.0,
            "upload_mbps": 30.0,
            "latency_ms": 15.0,
            "jitter_ms": None,
            "provider": "cloudflare",
            "server": "speed.cloudflare.com",
            "timestamp": "2026-02-18T10:00:00",
        }
    ]

    with patch("netglance.cli.speed.Store") as mock_store:
        mock_store.return_value.init_db.return_value = None
        mock_store.return_value.get_results.return_value = rows
        result = runner.invoke(app, ["history", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["download_mbps"] == 80.0


def test_cli_ookla_not_installed():
    """Missing ookla binary should show error and exit non-zero."""
    def _subprocess_fn(cmd, **kwargs):
        raise FileNotFoundError("not found")

    with patch("netglance.modules.speed.subprocess.run", side_effect=_subprocess_fn):
        result = runner.invoke(app, ["--provider", "ookla", "--no-save"])

    assert result.exit_code != 0
    assert "Error" in result.output
