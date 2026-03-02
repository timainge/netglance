"""Tests for the trending module (netglance/modules/trending.py) and metrics CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.main import app
from netglance.modules.trending import (
    emit_ping_metrics,
    emit_speed_metrics,
    emit_traffic_metrics,
    emit_wifi_metrics,
    parse_period,
    render_chart,
    sparkline,
)
from netglance.store.db import Store
from netglance.store.models import BandwidthSample, PingResult, SpeedTestResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    """Create a real Store in a temp directory and initialise the schema."""
    db_path = tmp_path / "test.db"
    store = Store(db_path=db_path)
    store.init_db()
    return store


# ---------------------------------------------------------------------------
# parse_period tests
# ---------------------------------------------------------------------------


class TestParsePeriod:
    def test_1h(self) -> None:
        before = datetime.now(timezone.utc) - timedelta(hours=1, seconds=1)
        result = parse_period("1h")
        after = datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(seconds=1)
        assert before < result < after

    def test_6h(self) -> None:
        result = parse_period("6h")
        expected = datetime.now(timezone.utc) - timedelta(hours=6)
        assert abs((result - expected).total_seconds()) < 2

    def test_24h(self) -> None:
        result = parse_period("24h")
        expected = datetime.now(timezone.utc) - timedelta(hours=24)
        assert abs((result - expected).total_seconds()) < 2

    def test_7d(self) -> None:
        result = parse_period("7d")
        expected = datetime.now(timezone.utc) - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 2

    def test_30d(self) -> None:
        result = parse_period("30d")
        expected = datetime.now(timezone.utc) - timedelta(days=30)
        assert abs((result - expected).total_seconds()) < 2

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized period"):
            parse_period("invalid")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_period("")

    def test_unknown_unit_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_period("5m")

    def test_returns_utc_aware(self) -> None:
        result = parse_period("1h")
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# sparkline tests
# ---------------------------------------------------------------------------


class TestSparkline:
    def test_empty_returns_spaces(self) -> None:
        result = sparkline([], width=10)
        assert result == " " * 10

    def test_output_length_matches_width(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = sparkline(values, width=10)
        assert len(result) == 10

    def test_single_value_middle_block(self) -> None:
        result = sparkline([5.0], width=5)
        assert len(result) == 5
        # All non-space chars should be the same (middle block for equal values)
        chars = result.strip()
        assert len(set(chars)) == 1

    def test_all_same_values_same_block(self) -> None:
        result = sparkline([3.0, 3.0, 3.0], width=5)
        chars = result.strip()
        assert len(set(chars)) == 1

    def test_uses_only_block_chars(self) -> None:
        blocks = set("▁▂▃▄▅▆▇█")
        result = sparkline([1.0, 2.0, 3.0, 4.0], width=4)
        for ch in result:
            assert ch in blocks, f"Unexpected char: {ch!r}"

    def test_ascending_values_ascending_blocks(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        result = sparkline(values, width=8)
        # Each character should be >= the previous in block rank
        blocks = "▁▂▃▄▅▆▇█"
        ranks = [blocks.index(ch) for ch in result]
        for i in range(1, len(ranks)):
            assert ranks[i] >= ranks[i - 1]

    def test_uses_last_width_values(self) -> None:
        # First 5 zeros, last 5 ones — sparkline of width 5 should show all high blocks
        values = [0.0] * 5 + [1.0] * 5
        result = sparkline(values, width=5)
        # All chars should be the highest block (last 5 are all 1.0 = same → middle)
        chars = result.strip()
        assert len(set(chars)) == 1


# ---------------------------------------------------------------------------
# render_chart tests
# ---------------------------------------------------------------------------


class TestRenderChart:
    def _make_mock_plotext(self, build_return: str = "CHART_OUTPUT") -> MagicMock:
        plt = MagicMock()
        plt.build.return_value = build_return
        return plt

    def test_returns_string(self) -> None:
        plt = self._make_mock_plotext("some chart")
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 42.0}]
        result = render_chart(series, title="Test", _plotext=plt)
        assert isinstance(result, str)

    def test_non_empty_output(self) -> None:
        plt = self._make_mock_plotext("chart content here")
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 10.0}]
        result = render_chart(series, title="Test", _plotext=plt)
        assert len(result) > 0

    def test_empty_series(self) -> None:
        plt = self._make_mock_plotext("empty chart")
        result = render_chart([], title="Empty", _plotext=plt)
        assert isinstance(result, str)

    def test_sets_title(self) -> None:
        plt = self._make_mock_plotext()
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 5.0}]
        render_chart(series, title="My Title", _plotext=plt)
        plt.title.assert_called_once_with("My Title")

    def test_sets_plot_size(self) -> None:
        plt = self._make_mock_plotext()
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 5.0}]
        render_chart(series, title="T", width=100, height=25, _plotext=plt)
        plt.plot_size.assert_called_once_with(100, 25)

    def test_calls_build(self) -> None:
        plt = self._make_mock_plotext()
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 1.0}]
        render_chart(series, title="T", _plotext=plt)
        plt.build.assert_called()

    def test_ylabel_set_when_provided(self) -> None:
        plt = self._make_mock_plotext()
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 1.0}]
        render_chart(series, title="T", ylabel="ms", _plotext=plt)
        plt.ylabel.assert_called_once_with("ms")

    def test_ylabel_not_set_when_empty(self) -> None:
        plt = self._make_mock_plotext()
        series = [{"ts": "2024-01-01T00:00:00Z", "value": 1.0}]
        render_chart(series, title="T", ylabel="", _plotext=plt)
        plt.ylabel.assert_not_called()


# ---------------------------------------------------------------------------
# emit_* function tests
# ---------------------------------------------------------------------------


class TestEmitPingMetrics:
    def test_saves_latency_and_packet_loss(self, tmp_store: Store) -> None:
        result = PingResult(
            host="8.8.8.8",
            is_alive=True,
            avg_latency_ms=12.5,
            packet_loss=0.0,
        )
        emit_ping_metrics(result, tmp_store)
        metrics = tmp_store.list_metrics()
        assert "ping.8_8_8_8.latency_ms" in metrics
        assert "ping.8_8_8_8.packet_loss" in metrics

    def test_latency_value_correct(self, tmp_store: Store) -> None:
        result = PingResult(host="1.1.1.1", is_alive=True, avg_latency_ms=25.0, packet_loss=0.1)
        emit_ping_metrics(result, tmp_store)
        series = tmp_store.get_metric_series("ping.1_1_1_1.latency_ms")
        assert len(series) == 1
        assert series[0]["value"] == pytest.approx(25.0)

    def test_packet_loss_value_correct(self, tmp_store: Store) -> None:
        result = PingResult(host="1.1.1.1", is_alive=True, avg_latency_ms=10.0, packet_loss=0.25)
        emit_ping_metrics(result, tmp_store)
        series = tmp_store.get_metric_series("ping.1_1_1_1.packet_loss")
        assert len(series) == 1
        assert series[0]["value"] == pytest.approx(0.25)

    def test_no_latency_metric_when_none(self, tmp_store: Store) -> None:
        result = PingResult(host="192.168.1.1", is_alive=False, avg_latency_ms=None, packet_loss=1.0)
        emit_ping_metrics(result, tmp_store)
        series = tmp_store.get_metric_series("ping.192_168_1_1.latency_ms")
        assert series == []

    def test_dots_replaced_with_underscores(self, tmp_store: Store) -> None:
        result = PingResult(host="10.0.0.1", is_alive=True, avg_latency_ms=5.0, packet_loss=0.0)
        emit_ping_metrics(result, tmp_store)
        metrics = tmp_store.list_metrics()
        assert "ping.10_0_0_1.latency_ms" in metrics
        assert not any("ping.10.0.0.1" in m for m in metrics)


class TestEmitSpeedMetrics:
    def test_saves_three_metrics(self, tmp_store: Store) -> None:
        result = SpeedTestResult(
            download_mbps=100.0, upload_mbps=50.0, latency_ms=12.0
        )
        emit_speed_metrics(result, tmp_store)
        metrics = tmp_store.list_metrics()
        assert "speed.download_mbps" in metrics
        assert "speed.upload_mbps" in metrics
        assert "speed.latency_ms" in metrics

    def test_values_correct(self, tmp_store: Store) -> None:
        result = SpeedTestResult(download_mbps=200.5, upload_mbps=80.3, latency_ms=8.7)
        emit_speed_metrics(result, tmp_store)
        dl = tmp_store.get_metric_series("speed.download_mbps")
        assert dl[0]["value"] == pytest.approx(200.5)
        ul = tmp_store.get_metric_series("speed.upload_mbps")
        assert ul[0]["value"] == pytest.approx(80.3)
        lat = tmp_store.get_metric_series("speed.latency_ms")
        assert lat[0]["value"] == pytest.approx(8.7)


class TestEmitTrafficMetrics:
    def test_saves_rx_and_tx(self, tmp_store: Store) -> None:
        sample = BandwidthSample(interface="eth0", tx_bytes_per_sec=1024.0, rx_bytes_per_sec=2048.0)
        emit_traffic_metrics(sample, tmp_store)
        metrics = tmp_store.list_metrics()
        assert "traffic.eth0.rx_bytes_per_sec" in metrics
        assert "traffic.eth0.tx_bytes_per_sec" in metrics

    def test_values_correct(self, tmp_store: Store) -> None:
        sample = BandwidthSample(interface="wlan0", tx_bytes_per_sec=512.5, rx_bytes_per_sec=1234.0)
        emit_traffic_metrics(sample, tmp_store)
        rx = tmp_store.get_metric_series("traffic.wlan0.rx_bytes_per_sec")
        assert rx[0]["value"] == pytest.approx(1234.0)
        tx = tmp_store.get_metric_series("traffic.wlan0.tx_bytes_per_sec")
        assert tx[0]["value"] == pytest.approx(512.5)


class TestEmitWifiMetrics:
    def test_saves_signal_dbm(self, tmp_store: Store) -> None:
        emit_wifi_metrics(-65, "MyNetwork", tmp_store)
        metrics = tmp_store.list_metrics()
        assert "wifi.signal_dbm" in metrics

    def test_value_correct(self, tmp_store: Store) -> None:
        emit_wifi_metrics(-72, "TestSSID", tmp_store)
        series = tmp_store.get_metric_series("wifi.signal_dbm")
        assert series[0]["value"] == pytest.approx(-72.0)

    def test_tags_contain_ssid(self, tmp_store: Store) -> None:
        emit_wifi_metrics(-55, "HomeNet", tmp_store)
        series = tmp_store.get_metric_series("wifi.signal_dbm")
        assert series[0]["tags"] == {"ssid": "HomeNet"}


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestMetricsListCmd:
    def test_empty_database(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["metrics", "list", "--db", str(db)])
        assert result.exit_code == 0
        assert "No metrics" in result.output

    def test_lists_metrics(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("ping.test.latency_ms", 10.0)
        store.save_metric("speed.download_mbps", 100.0)
        result = runner.invoke(app, ["metrics", "list", "--db", str(db)])
        assert result.exit_code == 0
        assert "ping.test.latency_ms" in result.output
        assert "speed.download_mbps" in result.output

    def test_json_output(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("test.metric", 1.0)
        result = runner.invoke(app, ["metrics", "list", "--db", str(db), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "test.metric" in data


class TestMetricsShowCmd:
    def test_no_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["metrics", "show", "nonexistent", "--db", str(db)])
        assert result.exit_code == 0
        assert "No data" in result.output

    @patch("netglance.cli.metrics.render_chart", return_value="MOCK_CHART")
    def test_shows_sparkline(self, _mock_chart, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        for v in [10.0, 20.0, 15.0]:
            store.save_metric("test.metric", v)
        result = runner.invoke(app, ["metrics", "show", "test.metric", "--db", str(db)])
        assert result.exit_code == 0

    def test_invalid_period(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        result = runner.invoke(app, ["metrics", "show", "x", "--period", "bad", "--db", str(db)])
        assert result.exit_code == 1

    def test_json_output(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("m", 5.0)
        result = runner.invoke(app, ["metrics", "show", "m", "--db", str(db), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


class TestMetricsStatsCmd:
    def test_no_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["metrics", "stats", "nonexistent", "--db", str(db)])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_shows_stats(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        for v in [10.0, 20.0, 30.0]:
            store.save_metric("ping.latency", v)
        result = runner.invoke(app, ["metrics", "stats", "ping.latency", "--db", str(db)])
        assert result.exit_code == 0
        assert "10" in result.output or "30" in result.output

    def test_invalid_period(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        result = runner.invoke(app, ["metrics", "stats", "x", "--period", "xyz", "--db", str(db)])
        assert result.exit_code == 1

    def test_json_output(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("m", 42.0)
        result = runner.invoke(app, ["metrics", "stats", "m", "--db", str(db), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "count" in data
        assert "avg" in data
        assert "min" in data
        assert "max" in data


class TestMetricsExportCmd:
    def test_no_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        result = runner.invoke(app, ["metrics", "export", "--db", str(db)])
        assert result.exit_code == 0
        assert "No metrics" in result.output

    def test_exports_csv(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        out_csv = tmp_path / "out.csv"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("speed.download_mbps", 100.0)
        store.save_metric("speed.upload_mbps", 50.0)
        result = runner.invoke(
            app, ["metrics", "export", "--db", str(db), "--output", str(out_csv)]
        )
        assert result.exit_code == 0
        assert out_csv.exists()
        content = out_csv.read_text()
        assert "speed.download_mbps" in content
        assert "speed.upload_mbps" in content

    def test_csv_has_correct_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        out_csv = tmp_path / "out.csv"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("m", 1.0)
        runner.invoke(app, ["metrics", "export", "--db", str(db), "--output", str(out_csv)])
        import csv
        with out_csv.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) >= 1
        assert set(rows[0].keys()) == {"ts", "metric", "value", "tags"}

    def test_invalid_period(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        result = runner.invoke(app, ["metrics", "export", "--since", "bad", "--db", str(db)])
        assert result.exit_code == 1

    def test_json_output(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        store = Store(db_path=db)
        store.init_db()
        store.save_metric("x", 99.0)
        result = runner.invoke(app, ["metrics", "export", "--db", str(db), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
