"""Tests for the ping module - all ICMP traffic is mocked."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli.main import app
from netglance.modules.ping import (
    check_gateway,
    check_internet,
    get_default_gateway,
    latency_color,
    ping_host,
    ping_sweep,
)
from netglance.store.models import PingResult


# ---------------------------------------------------------------------------
# Helpers: fake icmplib.Host objects
# ---------------------------------------------------------------------------

@dataclass
class FakeHost:
    """Mimics icmplib.Host with the fields our code reads."""

    address: str
    is_alive: bool
    avg_rtt: float = 0.0
    min_rtt: float = 0.0
    max_rtt: float = 0.0
    packet_loss: float = 0.0


def make_alive_host(address: str, avg: float = 5.0, mn: float = 3.0, mx: float = 8.0) -> FakeHost:
    return FakeHost(
        address=address,
        is_alive=True,
        avg_rtt=avg,
        min_rtt=mn,
        max_rtt=mx,
        packet_loss=0.0,
    )


def make_dead_host(address: str) -> FakeHost:
    return FakeHost(
        address=address,
        is_alive=False,
        avg_rtt=0.0,
        min_rtt=0.0,
        max_rtt=0.0,
        packet_loss=1.0,
    )


# ---------------------------------------------------------------------------
# Unit tests: ping_host
# ---------------------------------------------------------------------------

class TestPingHost:
    def test_alive_host(self) -> None:
        fake = make_alive_host("10.0.0.1", avg=12.5, mn=10.0, mx=15.0)
        fake_ping = MagicMock(return_value=fake)

        result = ping_host("10.0.0.1", count=4, timeout=2.0, _ping_fn=fake_ping)

        assert isinstance(result, PingResult)
        assert result.host == "10.0.0.1"
        assert result.is_alive is True
        assert result.avg_latency_ms == 12.5
        assert result.min_latency_ms == 10.0
        assert result.max_latency_ms == 15.0
        assert result.packet_loss == 0.0
        fake_ping.assert_called_once_with("10.0.0.1", count=4, timeout=2.0, privileged=False)

    def test_dead_host(self) -> None:
        fake = make_dead_host("10.0.0.99")
        fake_ping = MagicMock(return_value=fake)

        result = ping_host("10.0.0.99", _ping_fn=fake_ping)

        assert result.is_alive is False
        assert result.avg_latency_ms is None
        assert result.min_latency_ms is None
        assert result.max_latency_ms is None
        assert result.packet_loss == 1.0

    def test_custom_count_and_timeout(self) -> None:
        fake = make_alive_host("10.0.0.2")
        fake_ping = MagicMock(return_value=fake)

        ping_host("10.0.0.2", count=10, timeout=5.0, _ping_fn=fake_ping)

        fake_ping.assert_called_once_with("10.0.0.2", count=10, timeout=5.0, privileged=False)


# ---------------------------------------------------------------------------
# Unit tests: ping_sweep
# ---------------------------------------------------------------------------

class TestPingSweep:
    def test_sweep_small_subnet(self) -> None:
        """Sweep a /30 subnet: 2 host addresses, one alive, one dead."""
        responses = [
            make_alive_host("192.168.1.1", avg=2.0, mn=1.0, mx=3.0),
            make_dead_host("192.168.1.2"),
        ]
        fake_multiping = MagicMock(return_value=responses)

        results = ping_sweep("192.168.1.0/30", timeout=1.0, _multiping_fn=fake_multiping)

        assert len(results) == 2
        assert results[0].host == "192.168.1.1"
        assert results[0].is_alive is True
        assert results[1].host == "192.168.1.2"
        assert results[1].is_alive is False

        # Verify multiping was called with the right addresses
        call_args = fake_multiping.call_args
        assert call_args[0][0] == ["192.168.1.1", "192.168.1.2"]
        assert call_args[1]["count"] == 1
        assert call_args[1]["timeout"] == 1.0
        assert call_args[1]["privileged"] is False

    def test_sweep_all_alive(self) -> None:
        """All hosts in subnet respond."""
        responses = [
            make_alive_host("10.0.0.1"),
            make_alive_host("10.0.0.2"),
        ]
        fake_multiping = MagicMock(return_value=responses)

        results = ping_sweep("10.0.0.0/30", _multiping_fn=fake_multiping)

        alive = [r for r in results if r.is_alive]
        assert len(alive) == 2

    def test_sweep_all_dead(self) -> None:
        """No hosts respond in subnet."""
        responses = [
            make_dead_host("10.0.0.1"),
            make_dead_host("10.0.0.2"),
        ]
        fake_multiping = MagicMock(return_value=responses)

        results = ping_sweep("10.0.0.0/30", _multiping_fn=fake_multiping)

        alive = [r for r in results if r.is_alive]
        assert len(alive) == 0


# ---------------------------------------------------------------------------
# Unit tests: check_internet
# ---------------------------------------------------------------------------

class TestCheckInternet:
    def test_all_endpoints_up(self) -> None:
        fake_ping = MagicMock(
            side_effect=[
                make_alive_host("1.1.1.1", avg=5.0, mn=4.0, mx=6.0),
                make_alive_host("8.8.8.8", avg=10.0, mn=8.0, mx=12.0),
                make_alive_host("9.9.9.9", avg=7.0, mn=6.0, mx=8.0),
            ]
        )

        results = check_internet(_ping_fn=fake_ping)

        assert len(results) == 3
        assert all(r.is_alive for r in results)
        assert results[0].host == "1.1.1.1"
        assert results[1].host == "8.8.8.8"
        assert results[2].host == "9.9.9.9"

    def test_partial_failure(self) -> None:
        """One endpoint is down, others are up."""
        fake_ping = MagicMock(
            side_effect=[
                make_alive_host("1.1.1.1", avg=5.0, mn=4.0, mx=6.0),
                make_dead_host("8.8.8.8"),
                make_alive_host("9.9.9.9", avg=7.0, mn=6.0, mx=8.0),
            ]
        )

        results = check_internet(_ping_fn=fake_ping)

        assert len(results) == 3
        assert results[0].is_alive is True
        assert results[1].is_alive is False
        assert results[2].is_alive is True

    def test_all_down(self) -> None:
        fake_ping = MagicMock(
            side_effect=[
                make_dead_host("1.1.1.1"),
                make_dead_host("8.8.8.8"),
                make_dead_host("9.9.9.9"),
            ]
        )

        results = check_internet(_ping_fn=fake_ping)

        assert all(not r.is_alive for r in results)

    def test_custom_endpoints(self) -> None:
        fake_ping = MagicMock(return_value=make_alive_host("4.4.4.4"))

        results = check_internet(endpoints=["4.4.4.4"], _ping_fn=fake_ping)

        assert len(results) == 1
        assert results[0].host == "4.4.4.4"


# ---------------------------------------------------------------------------
# Unit tests: check_gateway
# ---------------------------------------------------------------------------

class TestCheckGateway:
    def test_gateway_alive(self) -> None:
        fake_ping = MagicMock(return_value=make_alive_host("192.168.1.1", avg=1.0, mn=0.5, mx=1.5))

        result = check_gateway(
            _ping_fn=fake_ping,
            _gateway_fn=lambda: "192.168.1.1",
        )

        assert result.is_alive is True
        assert result.host == "192.168.1.1"
        assert result.avg_latency_ms == 1.0

    def test_gateway_dead(self) -> None:
        fake_ping = MagicMock(return_value=make_dead_host("192.168.1.1"))

        result = check_gateway(
            _ping_fn=fake_ping,
            _gateway_fn=lambda: "192.168.1.1",
        )

        assert result.is_alive is False

    def test_gateway_not_detected(self) -> None:
        with pytest.raises(RuntimeError, match="Could not detect default gateway"):
            check_gateway(_gateway_fn=lambda: None)


# ---------------------------------------------------------------------------
# Unit tests: get_default_gateway
# ---------------------------------------------------------------------------

class TestGetDefaultGateway:
    def test_injectable_fn(self) -> None:
        gw = get_default_gateway(_netifaces_fn=lambda: "10.0.0.1")
        assert gw == "10.0.0.1"

    def test_injectable_fn_returns_none(self) -> None:
        gw = get_default_gateway(_netifaces_fn=lambda: None)
        assert gw is None


# ---------------------------------------------------------------------------
# Unit tests: latency_color
# ---------------------------------------------------------------------------

class TestLatencyColor:
    def test_none_returns_red(self) -> None:
        assert latency_color(None) == "red"

    def test_low_latency_green(self) -> None:
        assert latency_color(0.0) == "green"
        assert latency_color(5.0) == "green"
        assert latency_color(19.9) == "green"

    def test_boundary_20ms_is_yellow(self) -> None:
        assert latency_color(20.0) == "yellow"

    def test_medium_latency_yellow(self) -> None:
        assert latency_color(50.0) == "yellow"
        assert latency_color(99.9) == "yellow"

    def test_boundary_100ms_is_red(self) -> None:
        assert latency_color(100.0) == "red"

    def test_high_latency_red(self) -> None:
        assert latency_color(200.0) == "red"
        assert latency_color(1000.0) == "red"


# ---------------------------------------------------------------------------
# CLI integration tests via CliRunner
# ---------------------------------------------------------------------------

runner = CliRunner()


class TestCLIPingHost:
    def test_ping_host_alive(self) -> None:
        fake = make_alive_host("10.0.0.1", avg=12.5, mn=10.0, mx=15.0)
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake):
            result = runner.invoke(app, ["ping", "host", "10.0.0.1"])

        assert result.exit_code == 0
        assert "10.0.0.1" in result.output
        assert "UP" in result.output
        assert "12.5" in result.output

    def test_ping_host_dead(self) -> None:
        fake = make_dead_host("10.0.0.99")
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake):
            result = runner.invoke(app, ["ping", "host", "10.0.0.99"])

        assert result.exit_code == 0
        assert "DOWN" in result.output

    def test_ping_host_custom_count(self) -> None:
        fake = make_alive_host("10.0.0.1")
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake) as mock_ping:
            result = runner.invoke(app, ["ping", "host", "10.0.0.1", "--count", "10"])

        assert result.exit_code == 0
        mock_ping.assert_called_once_with("10.0.0.1", count=10, timeout=2.0, privileged=False)


class TestCLIPingSweep:
    def test_sweep_with_results(self) -> None:
        responses = [
            make_alive_host("192.168.1.1", avg=2.0, mn=1.0, mx=3.0),
            make_dead_host("192.168.1.2"),
        ]
        with patch("netglance.modules.ping.icmplib.multiping", return_value=responses):
            result = runner.invoke(app, ["ping", "sweep", "192.168.1.0/30"])

        assert result.exit_code == 0
        # Only alive hosts shown in sweep output
        assert "192.168.1.1" in result.output
        assert "1 alive" in result.output

    def test_sweep_no_subnet(self) -> None:
        result = runner.invoke(app, ["ping", "sweep"])
        assert result.exit_code == 1
        assert "Please provide a subnet" in result.output


class TestCLIPingInternet:
    def test_internet_all_up(self) -> None:
        fakes = [
            make_alive_host("1.1.1.1", avg=5.0, mn=4.0, mx=6.0),
            make_alive_host("8.8.8.8", avg=10.0, mn=8.0, mx=12.0),
            make_alive_host("9.9.9.9", avg=7.0, mn=6.0, mx=8.0),
        ]
        with patch("netglance.modules.ping.icmplib.ping", side_effect=fakes):
            result = runner.invoke(app, ["ping", "internet"])

        assert result.exit_code == 0
        assert "1.1.1.1" in result.output
        assert "8.8.8.8" in result.output
        assert "9.9.9.9" in result.output


class TestCLIPingGateway:
    def test_gateway_found_and_alive(self) -> None:
        fake = make_alive_host("192.168.1.1", avg=1.0, mn=0.5, mx=1.5)
        with (
            patch("netglance.modules.ping.icmplib.ping", return_value=fake),
            patch("netglance.modules.ping.get_default_gateway", return_value="192.168.1.1"),
        ):
            result = runner.invoke(app, ["ping", "gateway"])

        assert result.exit_code == 0
        assert "192.168.1.1" in result.output
        assert "UP" in result.output

    def test_gateway_not_found(self) -> None:
        with patch("netglance.modules.ping.get_default_gateway", return_value=None):
            result = runner.invoke(app, ["ping", "gateway"])

        assert result.exit_code == 1
        assert "Could not detect default gateway" in result.output


class TestCLILatencyColors:
    """Verify that the CLI output contains correct color markup for different latencies."""

    def test_green_latency(self) -> None:
        fake = make_alive_host("10.0.0.1", avg=5.0, mn=3.0, mx=8.0)
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake):
            result = runner.invoke(app, ["ping", "host", "10.0.0.1"])

        assert result.exit_code == 0
        # The latency value should appear in the output
        assert "5.0" in result.output

    def test_yellow_latency(self) -> None:
        fake = make_alive_host("10.0.0.1", avg=50.0, mn=40.0, mx=60.0)
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake):
            result = runner.invoke(app, ["ping", "host", "10.0.0.1"])

        assert result.exit_code == 0
        assert "50.0" in result.output

    def test_red_latency(self) -> None:
        fake = make_alive_host("10.0.0.1", avg=150.0, mn=120.0, mx=180.0)
        with patch("netglance.modules.ping.icmplib.ping", return_value=fake):
            result = runner.invoke(app, ["ping", "host", "10.0.0.1"])

        assert result.exit_code == 0
        assert "150.0" in result.output
