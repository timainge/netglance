"""Tests for the route (traceroute & path analysis) module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.modules.route import (
    Hop,
    TraceResult,
    dict_to_trace,
    diff_routes,
    trace_to_dict,
    traceroute,
)
from netglance.store.db import Store

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_hops(specs: list[tuple]) -> list[dict]:
    """Build synthetic raw hop dicts from (ttl, ip, rtt_ms) tuples."""
    return [{"ttl": ttl, "ip": ip, "rtt_ms": rtt} for ttl, ip, rtt in specs]


def _mock_traceroute_fn(host: str, max_hops: int, timeout: float) -> list[dict]:
    """Simulated scapy traceroute returning 4 hops to 93.184.216.34."""
    return _make_hops([
        (1, "192.168.1.1", 1.2),
        (2, "10.0.0.1", 5.4),
        (3, None, None),          # non-responsive hop
        (4, "93.184.216.34", 15.3),
    ])


def _mock_hostname_fn(ip: str) -> str | None:
    """Simulated reverse DNS."""
    mapping = {
        "192.168.1.1": "gateway.local",
        "10.0.0.1": "isp-router.example.net",
        "93.184.216.34": "example.com",
    }
    return mapping.get(ip)


def _mock_asn_fn(ip: str) -> tuple[str | None, str | None]:
    """Simulated ASN lookup."""
    mapping = {
        "192.168.1.1": (None, None),  # private IP, no ASN
        "10.0.0.1": ("AS7922", "Comcast"),
        "93.184.216.34": ("AS15133", "Edgecast"),
    }
    return mapping.get(ip, (None, None))


def _mock_resolve_dest(host: str) -> str:
    """Simulated destination resolution."""
    mapping = {
        "example.com": "93.184.216.34",
        "unreachable.example.com": "203.0.113.1",
        "blackhole.example.com": "198.51.100.1",
    }
    return mapping.get(host, host)


# ---------------------------------------------------------------------------
# Module-level tests: traceroute()
# ---------------------------------------------------------------------------

class TestTraceroute:
    """Tests for the traceroute() function."""

    def test_basic_traceroute(self):
        """traceroute returns structured hops with hostname and ASN data."""
        result = traceroute(
            "example.com",
            max_hops=10,
            timeout=1.0,
            _traceroute_fn=_mock_traceroute_fn,
            _hostname_fn=_mock_hostname_fn,
            _asn_fn=_mock_asn_fn,
            _resolve_dest_fn=_mock_resolve_dest,
        )

        assert isinstance(result, TraceResult)
        assert result.destination == "example.com"
        assert result.reached is True
        assert len(result.hops) == 4

    def test_hop_details(self):
        """Each hop has the expected IP, hostname, RTT, and ASN fields."""
        result = traceroute(
            "example.com",
            _traceroute_fn=_mock_traceroute_fn,
            _hostname_fn=_mock_hostname_fn,
            _asn_fn=_mock_asn_fn,
            _resolve_dest_fn=_mock_resolve_dest,
        )

        hop1 = result.hops[0]
        assert hop1.ttl == 1
        assert hop1.ip == "192.168.1.1"
        assert hop1.hostname == "gateway.local"
        assert hop1.rtt_ms == 1.2
        assert hop1.asn is None  # private IP

        hop2 = result.hops[1]
        assert hop2.asn == "AS7922"
        assert hop2.as_name == "Comcast"

        hop4 = result.hops[3]
        assert hop4.ip == "93.184.216.34"
        assert hop4.asn == "AS15133"
        assert hop4.as_name == "Edgecast"

    def test_non_responsive_hop(self):
        """Non-responsive hops have ip=None and rtt_ms=None."""
        result = traceroute(
            "example.com",
            _traceroute_fn=_mock_traceroute_fn,
            _hostname_fn=_mock_hostname_fn,
            _asn_fn=_mock_asn_fn,
            _resolve_dest_fn=_mock_resolve_dest,
        )

        hop3 = result.hops[2]
        assert hop3.ttl == 3
        assert hop3.ip is None
        assert hop3.hostname is None
        assert hop3.rtt_ms is None
        assert hop3.asn is None

    def test_destination_not_reached(self):
        """When the destination IP is never seen, reached=False."""

        def unreachable_fn(host, max_hops, timeout):
            return _make_hops([
                (1, "192.168.1.1", 1.0),
                (2, None, None),
                (3, None, None),
            ])

        result = traceroute(
            "unreachable.example.com",
            _traceroute_fn=unreachable_fn,
            _hostname_fn=lambda ip: None,
            _asn_fn=lambda ip: (None, None),
            _resolve_dest_fn=_mock_resolve_dest,
        )

        assert result.reached is False
        # Trailing non-responsive hops after last responsive are trimmed
        assert len(result.hops) == 1
        assert result.hops[0].ip == "192.168.1.1"

    def test_all_hops_non_responsive(self):
        """When every hop times out, the result has no hops and reached=False."""

        def all_timeout(host, max_hops, timeout):
            return _make_hops([
                (1, None, None),
                (2, None, None),
                (3, None, None),
            ])

        result = traceroute(
            "blackhole.example.com",
            _traceroute_fn=all_timeout,
            _hostname_fn=lambda ip: None,
            _asn_fn=lambda ip: (None, None),
            _resolve_dest_fn=_mock_resolve_dest,
        )

        assert result.reached is False
        assert len(result.hops) == 0

    def test_timestamp_is_set(self):
        """TraceResult.timestamp is populated as a datetime."""
        result = traceroute(
            "example.com",
            _traceroute_fn=_mock_traceroute_fn,
            _hostname_fn=_mock_hostname_fn,
            _asn_fn=_mock_asn_fn,
            _resolve_dest_fn=_mock_resolve_dest,
        )
        assert isinstance(result.timestamp, datetime)


# ---------------------------------------------------------------------------
# Module-level tests: diff_routes()
# ---------------------------------------------------------------------------

class TestDiffRoutes:
    """Tests for the diff_routes() function."""

    def _make_trace(self, hops: list[Hop], destination: str = "example.com") -> TraceResult:
        return TraceResult(
            destination=destination,
            hops=hops,
            reached=True,
            timestamp=datetime.now(),
        )

    def test_identical_routes(self):
        """No changes when routes are identical."""
        hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0, asn="AS200"),
        ]
        current = self._make_trace(hops)
        previous = self._make_trace(hops)

        diff = diff_routes(current, previous)

        assert diff["changed_hops"] == []
        assert diff["new_asns"] == []
        assert diff["path_length_delta"] == 0

    def test_changed_hop(self):
        """Detects when an intermediate hop changes IP."""
        prev_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0, asn="AS200"),
        ]
        cur_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
            Hop(ttl=2, ip="10.0.0.99", rtt_ms=6.0, asn="AS300"),
        ]
        previous = self._make_trace(prev_hops)
        current = self._make_trace(cur_hops)

        diff = diff_routes(current, previous)

        assert len(diff["changed_hops"]) == 1
        assert diff["changed_hops"][0]["ttl"] == 2
        assert diff["changed_hops"][0]["old_ip"] == "10.0.0.1"
        assert diff["changed_hops"][0]["new_ip"] == "10.0.0.99"

    def test_new_asns_detected(self):
        """Detects ASNs present in current but not in previous."""
        prev_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
        ]
        cur_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0, asn="AS999"),
        ]
        previous = self._make_trace(prev_hops)
        current = self._make_trace(cur_hops)

        diff = diff_routes(current, previous)

        assert "AS999" in diff["new_asns"]

    def test_path_length_delta(self):
        """Reports the difference in hop count."""
        prev_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0),
        ]
        cur_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0),
            Hop(ttl=3, ip="10.0.0.2", rtt_ms=8.0),
            Hop(ttl=4, ip="93.184.216.34", rtt_ms=15.0),
        ]
        previous = self._make_trace(prev_hops)
        current = self._make_trace(cur_hops)

        diff = diff_routes(current, previous)

        assert diff["path_length_delta"] == 2

    def test_path_shorter(self):
        """Negative delta when current path is shorter."""
        prev_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0),
            Hop(ttl=3, ip="93.184.216.34", rtt_ms=15.0),
        ]
        cur_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
        ]
        previous = self._make_trace(prev_hops)
        current = self._make_trace(cur_hops)

        diff = diff_routes(current, previous)

        assert diff["path_length_delta"] == -2

    def test_non_responsive_hop_in_diff(self):
        """Handles None IPs correctly in diff comparison."""
        prev_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
            Hop(ttl=2, ip=None, rtt_ms=None),  # was non-responsive
        ]
        cur_hops = [
            Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
            Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0),  # now responsive
        ]
        previous = self._make_trace(prev_hops)
        current = self._make_trace(cur_hops)

        diff = diff_routes(current, previous)

        assert len(diff["changed_hops"]) == 1
        assert diff["changed_hops"][0]["old_ip"] is None
        assert diff["changed_hops"][0]["new_ip"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# Serialisation round-trip tests
# ---------------------------------------------------------------------------

class TestSerialisation:
    """Tests for trace_to_dict / dict_to_trace."""

    def test_round_trip(self):
        """TraceResult survives serialisation and deserialisation."""
        original = TraceResult(
            destination="example.com",
            hops=[
                Hop(ttl=1, ip="192.168.1.1", hostname="gw", rtt_ms=1.0, asn="AS100", as_name="ISP"),
                Hop(ttl=2, ip=None, hostname=None, rtt_ms=None, asn=None, as_name=None),
                Hop(ttl=3, ip="93.184.216.34", hostname="example.com", rtt_ms=15.0, asn="AS15133", as_name="Edgecast"),
            ],
            reached=True,
        )

        data = trace_to_dict(original)
        restored = dict_to_trace(data)

        assert restored.destination == original.destination
        assert restored.reached == original.reached
        assert len(restored.hops) == len(original.hops)

        for orig_hop, rest_hop in zip(original.hops, restored.hops):
            assert rest_hop.ttl == orig_hop.ttl
            assert rest_hop.ip == orig_hop.ip
            assert rest_hop.hostname == orig_hop.hostname
            assert rest_hop.rtt_ms == orig_hop.rtt_ms
            assert rest_hop.asn == orig_hop.asn
            assert rest_hop.as_name == orig_hop.as_name

    def test_store_round_trip(self, tmp_db: Store):
        """TraceResult can be saved and retrieved from the Store."""
        result = TraceResult(
            destination="example.com",
            hops=[
                Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
                Hop(ttl=2, ip="93.184.216.34", rtt_ms=15.0, asn="AS15133"),
            ],
            reached=True,
        )

        data = trace_to_dict(result)
        tmp_db.save_result("route", data)
        rows = tmp_db.get_results("route", limit=1)

        assert len(rows) == 1
        restored = dict_to_trace(rows[0])
        assert restored.destination == "example.com"
        assert restored.reached is True
        assert len(restored.hops) == 2
        assert restored.hops[0].asn == "AS100"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestRouteCLI:
    """Tests for the 'netglance route' CLI subcommands."""

    def test_route_help(self):
        """'netglance route --help' succeeds and shows usage."""
        result = runner.invoke(app, ["route", "--help"])
        assert result.exit_code == 0
        assert "traceroute" in result.output.lower() or "path" in result.output.lower()

    def test_route_trace_basic(self):
        """'netglance route trace <host>' displays a traceroute table."""
        with patch("netglance.cli.route.traceroute") as mock_tr:
            mock_tr.return_value = TraceResult(
                destination="example.com",
                hops=[
                    Hop(ttl=1, ip="192.168.1.1", hostname="gw", rtt_ms=1.2, asn=None, as_name=None),
                    Hop(ttl=2, ip=None, hostname=None, rtt_ms=None, asn=None, as_name=None),
                    Hop(ttl=3, ip="93.184.216.34", hostname="example.com", rtt_ms=15.3, asn="AS15133", as_name="Edgecast"),
                ],
                reached=True,
            )

            result = runner.invoke(app, ["route", "trace", "example.com"])

            assert result.exit_code == 0
            assert "192.168.1.1" in result.output
            assert "93.184.216.34" in result.output
            assert "AS15133" in result.output
            assert "Edgecast" in result.output

    def test_route_trace_non_responsive_display(self):
        """Non-responsive hops show '* * *' in CLI output."""
        with patch("netglance.cli.route.traceroute") as mock_tr:
            mock_tr.return_value = TraceResult(
                destination="example.com",
                hops=[
                    Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
                    Hop(ttl=2, ip=None, rtt_ms=None),
                    Hop(ttl=3, ip="93.184.216.34", rtt_ms=15.0),
                ],
                reached=True,
            )

            result = runner.invoke(app, ["route", "trace", "example.com"])

            assert result.exit_code == 0
            assert "* * *" in result.output

    def test_route_trace_save(self, tmp_db: Store):
        """'--save' persists the result to the store."""
        with patch("netglance.cli.route.traceroute") as mock_tr:
            mock_tr.return_value = TraceResult(
                destination="example.com",
                hops=[
                    Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
                ],
                reached=False,
            )

            result = runner.invoke(
                app, ["route", "trace", "example.com", "--save", "--db", str(tmp_db.db_path)]
            )

            assert result.exit_code == 0
            assert "Saved to local database" in result.output

            rows = tmp_db.get_results("route", limit=1)
            assert len(rows) == 1
            assert rows[0]["destination"] == "example.com"

    def test_route_trace_diff(self, tmp_db: Store):
        """'--diff' compares current route against saved previous route."""
        # Save a previous route
        previous = TraceResult(
            destination="example.com",
            hops=[
                Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
                Hop(ttl=2, ip="10.0.0.1", rtt_ms=5.0, asn="AS200"),
            ],
            reached=True,
        )
        tmp_db.save_result("route", trace_to_dict(previous))

        with patch("netglance.cli.route.traceroute") as mock_tr:
            mock_tr.return_value = TraceResult(
                destination="example.com",
                hops=[
                    Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0, asn="AS100"),
                    Hop(ttl=2, ip="10.0.0.99", rtt_ms=6.0, asn="AS300"),
                    Hop(ttl=3, ip="93.184.216.34", rtt_ms=15.0, asn="AS15133"),
                ],
                reached=True,
            )

            result = runner.invoke(
                app, ["route", "trace", "example.com", "--diff", "--db", str(tmp_db.db_path)]
            )

            assert result.exit_code == 0
            # Should show route changes
            assert "Route Changes" in result.output or "10.0.0.99" in result.output

    def test_route_trace_diff_no_previous(self, tmp_db: Store):
        """'--diff' with no previous route saved still succeeds."""
        with patch("netglance.cli.route.traceroute") as mock_tr:
            mock_tr.return_value = TraceResult(
                destination="example.com",
                hops=[
                    Hop(ttl=1, ip="192.168.1.1", rtt_ms=1.0),
                ],
                reached=False,
            )

            result = runner.invoke(
                app, ["route", "trace", "example.com", "--diff", "--db", str(tmp_db.db_path)]
            )

            # Should succeed even without previous data to diff against
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

class TestHopDataclass:
    """Tests for the Hop and TraceResult dataclasses."""

    def test_hop_defaults(self):
        """Hop has sensible defaults for optional fields."""
        hop = Hop(ttl=1)
        assert hop.ttl == 1
        assert hop.ip is None
        assert hop.hostname is None
        assert hop.rtt_ms is None
        assert hop.asn is None
        assert hop.as_name is None

    def test_trace_result_defaults(self):
        """TraceResult has sensible defaults."""
        tr = TraceResult(destination="example.com")
        assert tr.destination == "example.com"
        assert tr.hops == []
        assert tr.reached is False
        assert isinstance(tr.timestamp, datetime)
