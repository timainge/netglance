"""Tests for the traffic & bandwidth monitoring module."""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.traffic import (
    BandwidthSample,
    InterfaceStats,
    format_bytes,
    get_interface_stats,
    live_monitor,
    sample_bandwidth,
)

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers to build fake psutil counter data
# ---------------------------------------------------------------------------

# psutil.net_io_counters returns named tuples with these fields (among others)
_NetIO = namedtuple(
    "snetio",
    ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv",
     "errin", "errout", "dropin", "dropout"],
)


def _make_counters(
    sent: int = 0, recv: int = 0, psent: int = 0, precv: int = 0
) -> _NetIO:
    return _NetIO(
        bytes_sent=sent,
        bytes_recv=recv,
        packets_sent=psent,
        packets_recv=precv,
        errin=0,
        errout=0,
        dropin=0,
        dropout=0,
    )


# ---------------------------------------------------------------------------
# get_interface_stats
# ---------------------------------------------------------------------------


class TestGetInterfaceStats:
    def test_returns_correct_structure(self) -> None:
        fake_data = {
            "en0": _make_counters(sent=1000, recv=2000, psent=10, precv=20),
            "lo0": _make_counters(sent=500, recv=500, psent=5, precv=5),
        }

        def fake_counters(pernic: bool = True) -> dict:
            return fake_data

        stats = get_interface_stats(_counters_fn=fake_counters)

        assert len(stats) == 2
        names = {s.interface for s in stats}
        assert names == {"en0", "lo0"}

        for s in stats:
            assert isinstance(s, InterfaceStats)
            assert isinstance(s.timestamp, datetime)

    def test_values_match_input(self) -> None:
        fake_data = {
            "eth0": _make_counters(sent=123456, recv=654321, psent=100, precv=200),
        }

        stats = get_interface_stats(_counters_fn=lambda pernic=True: fake_data)

        assert len(stats) == 1
        s = stats[0]
        assert s.interface == "eth0"
        assert s.bytes_sent == 123456
        assert s.bytes_recv == 654321
        assert s.packets_sent == 100
        assert s.packets_recv == 200

    def test_empty_interfaces(self) -> None:
        stats = get_interface_stats(_counters_fn=lambda pernic=True: {})
        assert stats == []


# ---------------------------------------------------------------------------
# sample_bandwidth
# ---------------------------------------------------------------------------


class TestSampleBandwidth:
    def test_calculates_rate_from_two_snapshots(self) -> None:
        """With a 1-second interval and 1024-byte delta, rate should be 1024 B/s."""
        snap1 = {
            "en0": _make_counters(sent=1000, recv=2000, psent=10, precv=20),
        }
        snap2 = {
            "en0": _make_counters(sent=2024, recv=3024, psent=20, precv=30),
        }
        call_count = 0

        def fake_counters(pernic: bool = True) -> dict:
            nonlocal call_count
            call_count += 1
            return snap1 if call_count == 1 else snap2

        result = sample_bandwidth(
            "en0",
            interval=1.0,
            _counters_fn=fake_counters,
            _sleep_fn=lambda _: None,
        )

        assert isinstance(result, BandwidthSample)
        assert result.interface == "en0"
        assert result.tx_bytes_per_sec == pytest.approx(1024.0)
        assert result.rx_bytes_per_sec == pytest.approx(1024.0)

    def test_scales_with_interval(self) -> None:
        """With a 2-second interval, rates should be half the byte delta."""
        snap1 = {"en0": _make_counters(sent=0, recv=0)}
        snap2 = {"en0": _make_counters(sent=2000, recv=4000)}
        call_count = 0

        def fake_counters(pernic: bool = True) -> dict:
            nonlocal call_count
            call_count += 1
            return snap1 if call_count == 1 else snap2

        result = sample_bandwidth(
            "en0",
            interval=2.0,
            _counters_fn=fake_counters,
            _sleep_fn=lambda _: None,
        )

        assert result.tx_bytes_per_sec == pytest.approx(1000.0)
        assert result.rx_bytes_per_sec == pytest.approx(2000.0)

    def test_unknown_interface_raises(self) -> None:
        def fake_counters(pernic: bool = True) -> dict:
            return {"lo0": _make_counters()}

        with pytest.raises(KeyError, match="en0"):
            sample_bandwidth(
                "en0",
                _counters_fn=fake_counters,
                _sleep_fn=lambda _: None,
            )

    def test_zero_delta_gives_zero_rate(self) -> None:
        snap = {"en0": _make_counters(sent=500, recv=500)}

        def fake_counters(pernic: bool = True) -> dict:
            return snap

        result = sample_bandwidth(
            "en0",
            interval=1.0,
            _counters_fn=fake_counters,
            _sleep_fn=lambda _: None,
        )

        assert result.tx_bytes_per_sec == pytest.approx(0.0)
        assert result.rx_bytes_per_sec == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


class TestFormatBytes:
    def test_zero(self) -> None:
        assert format_bytes(0) == "0 B/s"

    def test_small_bytes(self) -> None:
        assert format_bytes(512) == "512 B/s"

    def test_kilobytes(self) -> None:
        result = format_bytes(1024)
        assert result == "1.00 KB/s"

    def test_kilobytes_fractional(self) -> None:
        result = format_bytes(1536)
        assert result == "1.50 KB/s"

    def test_megabytes(self) -> None:
        result = format_bytes(1024 * 1024)
        assert result == "1.00 MB/s"

    def test_megabytes_fractional(self) -> None:
        result = format_bytes(1024 * 1024 * 2.5)
        assert result == "2.50 MB/s"

    def test_gigabytes(self) -> None:
        result = format_bytes(1024**3)
        assert result == "1.00 GB/s"

    def test_gigabytes_large(self) -> None:
        result = format_bytes(1024**3 * 10.75)
        assert result == "10.75 GB/s"

    def test_negative_clamped_to_zero(self) -> None:
        assert format_bytes(-100) == "0 B/s"

    def test_just_under_kb(self) -> None:
        result = format_bytes(1023)
        assert result == "1023 B/s"

    def test_just_at_mb(self) -> None:
        result = format_bytes(1024 * 1024)
        assert "MB/s" in result


# ---------------------------------------------------------------------------
# live_monitor
# ---------------------------------------------------------------------------


class TestLiveMonitor:
    def test_calls_callback_with_samples(self) -> None:
        """live_monitor should produce samples and call the callback."""
        snapshots = [
            {"en0": _make_counters(sent=0, recv=0)},
            {"en0": _make_counters(sent=1000, recv=2000)},
            {"en0": _make_counters(sent=3000, recv=5000)},
        ]
        call_idx = 0

        def fake_counters(pernic: bool = True) -> dict:
            nonlocal call_idx
            data = snapshots[min(call_idx, len(snapshots) - 1)]
            call_idx += 1
            return data

        iterations = 0

        def should_stop() -> bool:
            nonlocal iterations
            # The first counter call happens before the loop. Then each
            # iteration does sleep + counter + callback. We want 2 callbacks.
            return iterations >= 2

        samples: list[BandwidthSample] = []

        def on_sample(s: BandwidthSample) -> None:
            nonlocal iterations
            samples.append(s)
            iterations += 1

        live_monitor(
            "en0",
            callback=on_sample,
            interval=1.0,
            _counters_fn=fake_counters,
            _sleep_fn=lambda _: None,
            _should_stop=should_stop,
        )

        assert len(samples) == 2
        assert samples[0].interface == "en0"
        assert samples[0].tx_bytes_per_sec == pytest.approx(1000.0)
        assert samples[0].rx_bytes_per_sec == pytest.approx(2000.0)

    def test_unknown_interface_raises(self) -> None:
        def fake_counters(pernic: bool = True) -> dict:
            return {"lo0": _make_counters()}

        with pytest.raises(KeyError, match="wlan0"):
            live_monitor(
                "wlan0",
                callback=lambda s: None,
                _counters_fn=fake_counters,
                _sleep_fn=lambda _: None,
                _should_stop=lambda: True,
            )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestTrafficCLI:
    def test_stats_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'netglance traffic stats' should display a table."""
        fake_data = {
            "en0": _make_counters(sent=1_000_000, recv=2_000_000, psent=100, precv=200),
            "lo0": _make_counters(sent=500, recv=500, psent=5, precv=5),
        }
        monkeypatch.setattr(
            "netglance.modules.traffic._psutil_net_io_counters",
            lambda pernic=True: fake_data,
        )

        result = runner.invoke(app, ["traffic", "stats"])

        assert result.exit_code == 0
        assert "en0" in result.output
        assert "lo0" in result.output

    def test_stats_with_interface_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'netglance traffic stats --interface en0' should only show en0."""
        fake_data = {
            "en0": _make_counters(sent=1_000_000, recv=2_000_000, psent=100, precv=200),
            "lo0": _make_counters(sent=500, recv=500, psent=5, precv=5),
        }
        monkeypatch.setattr(
            "netglance.modules.traffic._psutil_net_io_counters",
            lambda pernic=True: fake_data,
        )

        result = runner.invoke(app, ["traffic", "stats", "--interface", "en0"])

        assert result.exit_code == 0
        assert "en0" in result.output
        assert "lo0" not in result.output

    def test_stats_unknown_interface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Filtering by a missing interface should error."""
        fake_data = {
            "en0": _make_counters(sent=100, recv=200),
        }
        monkeypatch.setattr(
            "netglance.modules.traffic._psutil_net_io_counters",
            lambda pernic=True: fake_data,
        )

        result = runner.invoke(app, ["traffic", "stats", "--interface", "wlan99"])

        assert result.exit_code != 0
        assert "wlan99" in result.output

    def test_traffic_help(self) -> None:
        result = runner.invoke(app, ["traffic", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "live" in result.output

    def test_stats_shows_table_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_data = {
            "eth0": _make_counters(sent=0, recv=0, psent=0, precv=0),
        }
        monkeypatch.setattr(
            "netglance.modules.traffic._psutil_net_io_counters",
            lambda pernic=True: fake_data,
        )

        result = runner.invoke(app, ["traffic", "stats"])

        assert result.exit_code == 0
        assert "Interface Traffic Stats" in result.output
