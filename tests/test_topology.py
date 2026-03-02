"""Tests for the topology module and CLI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.modules.topology import (
    ID_INTERNET,
    NODE_GATEWAY,
    NODE_HOST,
    NODE_INTERNET,
    build_topology,
    diff_topologies,
    discover_topology,
    topology_to_ascii,
    topology_to_dot,
    topology_to_json,
)
from netglance.store.models import (
    ArpEntry,
    Device,
    Hop,
    NetworkTopology,
    TopologyEdge,
    TopologyNode,
    TraceResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_device(
    ip: str,
    mac: str = "aa:bb:cc:dd:ee:ff",
    hostname: str | None = None,
    vendor: str | None = None,
) -> Device:
    return Device(
        ip=ip,
        mac=mac,
        hostname=hostname,
        vendor=vendor,
        first_seen=datetime.now(),
        last_seen=datetime.now(),
    )


def make_arp_entry(ip: str, mac: str, interface: str = "en0") -> ArpEntry:
    return ArpEntry(ip=ip, mac=mac, interface=interface)


def make_hop(ttl: int, ip: str | None, rtt_ms: float | None = None) -> Hop:
    return Hop(ttl=ttl, ip=ip, rtt_ms=rtt_ms)


def make_trace(destination: str, hops: list[Hop], reached: bool = True) -> TraceResult:
    return TraceResult(destination=destination, hops=hops, reached=reached)


def make_node(
    id: str,
    label: str,
    node_type: str = NODE_HOST,
    ip: str | None = None,
    mac: str | None = None,
    vendor: str | None = None,
) -> TopologyNode:
    return TopologyNode(id=id, label=label, node_type=node_type, ip=ip, mac=mac, vendor=vendor)


def make_edge(source: str, target: str, edge_type: str = "direct") -> TopologyEdge:
    return TopologyEdge(source=source, target=target, edge_type=edge_type)


# ---------------------------------------------------------------------------
# build_topology tests
# ---------------------------------------------------------------------------


class TestBuildTopology:
    def test_empty_topology_has_internet_node(self):
        topo = build_topology([], [], [], gateway_ip=None)
        assert len(topo.nodes) == 1
        assert topo.nodes[0].id == ID_INTERNET
        assert topo.nodes[0].node_type == NODE_INTERNET

    def test_gateway_creates_node(self):
        topo = build_topology([], [], [], gateway_ip="192.168.1.1")
        node_ids = [n.id for n in topo.nodes]
        assert "node_192_168_1_1" in node_ids
        gw = next(n for n in topo.nodes if n.id == "node_192_168_1_1")
        assert gw.node_type == NODE_GATEWAY
        assert gw.ip == "192.168.1.1"

    def test_gateway_includes_vendor_from_device(self):
        gw_device = make_device("192.168.1.1", vendor="Netgear")
        topo = build_topology([gw_device], [], [], gateway_ip="192.168.1.1")
        gw = next(n for n in topo.nodes if n.node_type == NODE_GATEWAY)
        assert "Netgear" in gw.label
        assert gw.vendor == "Netgear"

    def test_gateway_mac_from_arp(self):
        arp_entries = [make_arp_entry("192.168.1.1", "aa:bb:cc:11:22:33")]
        topo = build_topology([], arp_entries, [], gateway_ip="192.168.1.1")
        gw = next(n for n in topo.nodes if n.node_type == NODE_GATEWAY)
        assert gw.mac == "aa:bb:cc:11:22:33"

    def test_local_devices_become_host_nodes(self):
        devices = [
            make_device("192.168.1.10", hostname="macbook"),
            make_device("192.168.1.20", hostname="iphone"),
        ]
        topo = build_topology(devices, [], [], gateway_ip="192.168.1.1")
        host_nodes = [n for n in topo.nodes if n.node_type == NODE_HOST]
        assert len(host_nodes) == 2
        ips = {n.ip for n in host_nodes}
        assert "192.168.1.10" in ips
        assert "192.168.1.20" in ips

    def test_gateway_device_not_duplicated_as_host(self):
        gw_device = make_device("192.168.1.1", hostname="router")
        topo = build_topology([gw_device], [], [], gateway_ip="192.168.1.1")
        # Only internet + gateway — no extra host
        assert len(topo.nodes) == 2
        assert not any(n.node_type == NODE_HOST for n in topo.nodes)

    def test_edges_connect_gateway_to_internet(self):
        topo = build_topology([], [], [], gateway_ip="192.168.1.1")
        edge_pairs = {(e.source, e.target) for e in topo.edges}
        assert (ID_INTERNET, "node_192_168_1_1") in edge_pairs

    def test_edges_connect_hosts_to_gateway(self):
        devices = [make_device("192.168.1.10")]
        topo = build_topology(devices, [], [], gateway_ip="192.168.1.1")
        edge_pairs = {(e.source, e.target) for e in topo.edges}
        assert ("node_192_168_1_1", "node_192_168_1_10") in edge_pairs

    def test_no_gateway_connects_hosts_to_internet(self):
        devices = [make_device("192.168.1.10")]
        topo = build_topology(devices, [], [], gateway_ip=None)
        edge_pairs = {(e.source, e.target) for e in topo.edges}
        assert (ID_INTERNET, "node_192_168_1_10") in edge_pairs

    def test_traceroute_isp_hops_added(self):
        hops = [
            make_hop(1, "10.0.0.1", 1.0),  # ISP hop 1
            make_hop(2, "10.0.0.2", 5.0),  # ISP hop 2
        ]
        trace = make_trace("8.8.8.8", hops)
        topo = build_topology([], [], [trace], gateway_ip="192.168.1.1")
        isp_ids = {"node_10_0_0_1", "node_10_0_0_2"}
        actual_ids = {n.id for n in topo.nodes}
        assert isp_ids.issubset(actual_ids)

    def test_local_ips_not_added_as_isp_hops(self):
        devices = [make_device("192.168.1.10")]
        hops = [
            make_hop(1, "192.168.1.1", 1.0),  # gateway — local
            make_hop(2, "192.168.1.10", 2.0),  # local device
        ]
        trace = make_trace("8.8.8.8", hops)
        topo = build_topology(devices, [], [trace], gateway_ip="192.168.1.1")
        # No extra nodes beyond internet + gateway + device
        assert len(topo.nodes) == 3

    def test_topology_timestamp_set(self):
        topo = build_topology([], [], [], gateway_ip=None)
        assert isinstance(topo.timestamp, datetime)

    def test_device_label_includes_hostname_and_ip(self):
        devices = [make_device("192.168.1.10", hostname="macbook")]
        topo = build_topology(devices, [], [], gateway_ip=None)
        host = next(n for n in topo.nodes if n.node_type == NODE_HOST)
        assert "macbook" in host.label
        assert "192.168.1.10" in host.label

    def test_device_label_vendor_included(self):
        devices = [make_device("192.168.1.42", hostname="nas", vendor="Synology")]
        topo = build_topology(devices, [], [], gateway_ip=None)
        host = next(n for n in topo.nodes if n.node_type == NODE_HOST)
        assert "Synology" in host.label

    def test_multiple_trace_results_used(self):
        hops1 = [make_hop(1, "10.0.0.1", 1.0)]
        hops2 = [make_hop(1, "10.1.0.1", 2.0)]
        traces = [make_trace("8.8.8.8", hops1), make_trace("1.1.1.1", hops2)]
        topo = build_topology([], [], traces, gateway_ip="192.168.1.1")
        isp_ids = {n.id for n in topo.nodes if n.id not in {ID_INTERNET, "node_192_168_1_1"}}
        assert len(isp_ids) == 2

    def test_hop_with_none_ip_skipped(self):
        hops = [make_hop(1, None), make_hop(2, "10.0.0.1")]
        trace = make_trace("8.8.8.8", hops)
        topo = build_topology([], [], [trace], gateway_ip="192.168.1.1")
        # Only node_10_0_0_1 from the trace (not a None-IP node)
        assert "node_None" not in {n.id for n in topo.nodes}

    def test_gateway_latency_in_edge_from_traceroute(self):
        hops = [make_hop(1, "192.168.1.1", 3.5)]
        trace = make_trace("8.8.8.8", hops)
        topo = build_topology([], [], [trace], gateway_ip="192.168.1.1")
        gw_edge = next(
            (e for e in topo.edges if e.target == "node_192_168_1_1"), None
        )
        assert gw_edge is not None
        assert gw_edge.latency_ms == 3.5


# ---------------------------------------------------------------------------
# discover_topology tests
# ---------------------------------------------------------------------------


class TestDiscoverTopology:
    def test_calls_all_injected_functions(self):
        mock_devices = [make_device("192.168.1.10")]
        mock_arp = [make_arp_entry("192.168.1.1", "aa:bb:cc:00:11:22")]
        mock_trace = make_trace("8.8.8.8", [make_hop(1, "10.0.0.1")])

        discover_fn = MagicMock(return_value=mock_devices)
        arp_fn = MagicMock(return_value=mock_arp)
        trace_fn = MagicMock(return_value=mock_trace)
        gateway_fn = MagicMock(return_value="192.168.1.1")

        topo = discover_topology(
            subnet="192.168.1.0/24",
            trace_targets=["8.8.8.8"],
            _discover_fn=discover_fn,
            _arp_fn=arp_fn,
            _trace_fn=trace_fn,
            _gateway_fn=gateway_fn,
        )

        discover_fn.assert_called_once()
        arp_fn.assert_called_once()
        trace_fn.assert_called_once_with("8.8.8.8")
        gateway_fn.assert_called_once()
        assert isinstance(topo, NetworkTopology)

    def test_default_trace_target_is_google_dns(self):
        discover_fn = MagicMock(return_value=[])
        arp_fn = MagicMock(return_value=[])
        trace_fn = MagicMock(return_value=make_trace("8.8.8.8", []))
        gateway_fn = MagicMock(return_value=None)

        discover_topology(
            _discover_fn=discover_fn,
            _arp_fn=arp_fn,
            _trace_fn=trace_fn,
            _gateway_fn=gateway_fn,
        )
        trace_fn.assert_called_once_with("8.8.8.8")

    def test_multiple_trace_targets(self):
        discover_fn = MagicMock(return_value=[])
        arp_fn = MagicMock(return_value=[])
        trace_fn = MagicMock(return_value=make_trace("x", []))
        gateway_fn = MagicMock(return_value=None)

        discover_topology(
            trace_targets=["8.8.8.8", "1.1.1.1"],
            _discover_fn=discover_fn,
            _arp_fn=arp_fn,
            _trace_fn=trace_fn,
            _gateway_fn=gateway_fn,
        )
        assert trace_fn.call_count == 2


# ---------------------------------------------------------------------------
# topology_to_dot tests
# ---------------------------------------------------------------------------


class TestTopologyToDot:
    def _simple_topology(self) -> NetworkTopology:
        nodes = [
            make_node(ID_INTERNET, "Internet", NODE_INTERNET),
            make_node("node_192_168_1_1", "Gateway (192.168.1.1)", NODE_GATEWAY, ip="192.168.1.1"),
            make_node("node_192_168_1_10", "macbook (192.168.1.10)", NODE_HOST, ip="192.168.1.10"),
        ]
        edges = [
            make_edge(ID_INTERNET, "node_192_168_1_1", "routed"),
            make_edge("node_192_168_1_1", "node_192_168_1_10", "direct"),
        ]
        return NetworkTopology(nodes=nodes, edges=edges)

    def test_starts_with_digraph(self):
        dot = topology_to_dot(self._simple_topology())
        assert dot.startswith("digraph network_topology {")

    def test_ends_with_closing_brace(self):
        dot = topology_to_dot(self._simple_topology())
        assert dot.strip().endswith("}")

    def test_all_nodes_present(self):
        dot = topology_to_dot(self._simple_topology())
        assert '"internet"' in dot
        assert '"node_192_168_1_1"' in dot
        assert '"node_192_168_1_10"' in dot

    def test_internet_node_is_ellipse(self):
        dot = topology_to_dot(self._simple_topology())
        # internet node must have shape=ellipse
        assert "shape=ellipse" in dot

    def test_gateway_node_is_diamond(self):
        dot = topology_to_dot(self._simple_topology())
        assert "shape=diamond" in dot

    def test_host_node_is_box(self):
        dot = topology_to_dot(self._simple_topology())
        assert "shape=box" in dot

    def test_edges_present(self):
        dot = topology_to_dot(self._simple_topology())
        assert '"internet" -> "node_192_168_1_1"' in dot
        assert '"node_192_168_1_1" -> "node_192_168_1_10"' in dot

    def test_edge_with_latency_label(self):
        nodes = [
            make_node(ID_INTERNET, "Internet", NODE_INTERNET),
            make_node("node_192_168_1_1", "Gateway", NODE_GATEWAY),
        ]
        edges = [TopologyEdge(source=ID_INTERNET, target="node_192_168_1_1", edge_type="routed", latency_ms=5.3, label="5.3ms")]
        topo = NetworkTopology(nodes=nodes, edges=edges)
        dot = topology_to_dot(topo)
        assert "5.3ms" in dot

    def test_empty_topology(self):
        topo = NetworkTopology(nodes=[], edges=[])
        dot = topology_to_dot(topo)
        assert "digraph" in dot
        assert "}" in dot

    def test_label_quotes_escaped(self):
        nodes = [make_node("n1", 'Test "quoted" label', NODE_HOST)]
        topo = NetworkTopology(nodes=nodes, edges=[])
        dot = topology_to_dot(topo)
        assert '\\"quoted\\"' in dot


# ---------------------------------------------------------------------------
# topology_to_json tests
# ---------------------------------------------------------------------------


class TestTopologyToJson:
    def _simple_topology(self) -> NetworkTopology:
        nodes = [
            make_node(ID_INTERNET, "Internet", NODE_INTERNET),
            make_node("node_192_168_1_1", "Gateway", NODE_GATEWAY, ip="192.168.1.1"),
        ]
        edges = [make_edge(ID_INTERNET, "node_192_168_1_1", "routed")]
        return NetworkTopology(nodes=nodes, edges=edges)

    def test_returns_dict(self):
        result = topology_to_json(self._simple_topology())
        assert isinstance(result, dict)

    def test_has_nodes_key(self):
        result = topology_to_json(self._simple_topology())
        assert "nodes" in result
        assert isinstance(result["nodes"], list)

    def test_has_links_key(self):
        result = topology_to_json(self._simple_topology())
        assert "links" in result
        assert isinstance(result["links"], list)

    def test_has_timestamp_key(self):
        result = topology_to_json(self._simple_topology())
        assert "timestamp" in result

    def test_node_fields_present(self):
        result = topology_to_json(self._simple_topology())
        node = result["nodes"][0]
        assert "id" in node
        assert "label" in node
        assert "type" in node
        assert "ip" in node
        assert "mac" in node
        assert "vendor" in node

    def test_link_fields_present(self):
        result = topology_to_json(self._simple_topology())
        link = result["links"][0]
        assert "source" in link
        assert "target" in link
        assert "type" in link
        assert "latency_ms" in link
        assert "label" in link

    def test_json_serializable(self):
        result = topology_to_json(self._simple_topology())
        serialized = json.dumps(result)
        assert isinstance(serialized, str)

    def test_node_count_matches(self):
        result = topology_to_json(self._simple_topology())
        assert len(result["nodes"]) == 2

    def test_link_count_matches(self):
        result = topology_to_json(self._simple_topology())
        assert len(result["links"]) == 1


# ---------------------------------------------------------------------------
# topology_to_ascii tests
# ---------------------------------------------------------------------------


class TestTopologyToAscii:
    def _simple_topology(self) -> NetworkTopology:
        nodes = [
            make_node(ID_INTERNET, "Internet", NODE_INTERNET),
            make_node("node_192_168_1_1", "Gateway (192.168.1.1)", NODE_GATEWAY, ip="192.168.1.1"),
            make_node("node_192_168_1_10", "macbook (192.168.1.10)", NODE_HOST, ip="192.168.1.10"),
        ]
        edges = [
            make_edge(ID_INTERNET, "node_192_168_1_1", "routed"),
            make_edge("node_192_168_1_1", "node_192_168_1_10", "direct"),
        ]
        return NetworkTopology(nodes=nodes, edges=edges)

    def test_returns_string(self):
        result = topology_to_ascii(self._simple_topology())
        assert isinstance(result, str)

    def test_contains_internet(self):
        result = topology_to_ascii(self._simple_topology())
        assert "Internet" in result

    def test_contains_gateway(self):
        result = topology_to_ascii(self._simple_topology())
        assert "Gateway" in result

    def test_contains_host(self):
        result = topology_to_ascii(self._simple_topology())
        assert "macbook" in result

    def test_empty_topology_returns_string(self):
        topo = NetworkTopology(nodes=[], edges=[])
        result = topology_to_ascii(topo)
        assert isinstance(result, str)
        assert "(empty topology)" in result

    def test_single_node_topology(self):
        nodes = [make_node(ID_INTERNET, "Internet", NODE_INTERNET)]
        topo = NetworkTopology(nodes=nodes, edges=[])
        result = topology_to_ascii(topo)
        assert "Internet" in result


# ---------------------------------------------------------------------------
# diff_topologies tests
# ---------------------------------------------------------------------------


class TestDiffTopologies:
    def _topology_with(self, ips: list[str], gateway_ip: str = "192.168.1.1") -> NetworkTopology:
        nodes = [make_node(ID_INTERNET, "Internet", NODE_INTERNET)]
        edges: list[TopologyEdge] = []
        gw_id = f"node_{gateway_ip.replace('.', '_')}"
        nodes.append(make_node(gw_id, f"Gateway ({gateway_ip})", NODE_GATEWAY, ip=gateway_ip))
        edges.append(make_edge(ID_INTERNET, gw_id, "routed"))
        for ip in ips:
            node_id = f"node_{ip.replace('.', '_')}"
            nodes.append(make_node(node_id, f"host ({ip})", NODE_HOST, ip=ip))
            edges.append(make_edge(gw_id, node_id, "direct"))
        return NetworkTopology(nodes=nodes, edges=edges)

    def test_identical_topologies_no_diff(self):
        topo = self._topology_with(["192.168.1.10"])
        diff = diff_topologies(topo, topo)
        assert diff["new_nodes"] == []
        assert diff["removed_nodes"] == []
        assert diff["new_edges"] == []
        assert diff["removed_edges"] == []

    def test_new_node_detected(self):
        previous = self._topology_with(["192.168.1.10"])
        current = self._topology_with(["192.168.1.10", "192.168.1.20"])
        diff = diff_topologies(current, previous)
        new_node_ids = {n["id"] for n in diff["new_nodes"]}
        assert "node_192_168_1_20" in new_node_ids

    def test_removed_node_detected(self):
        previous = self._topology_with(["192.168.1.10", "192.168.1.20"])
        current = self._topology_with(["192.168.1.10"])
        diff = diff_topologies(current, previous)
        removed_ids = {n["id"] for n in diff["removed_nodes"]}
        assert "node_192_168_1_20" in removed_ids

    def test_new_edge_detected(self):
        previous = self._topology_with([])
        current = self._topology_with(["192.168.1.10"])
        diff = diff_topologies(current, previous)
        new_edge_pairs = {(e["source"], e["target"]) for e in diff["new_edges"]}
        assert ("node_192_168_1_1", "node_192_168_1_10") in new_edge_pairs

    def test_removed_edge_detected(self):
        previous = self._topology_with(["192.168.1.10"])
        current = self._topology_with([])
        diff = diff_topologies(current, previous)
        removed_edge_pairs = {(e["source"], e["target"]) for e in diff["removed_edges"]}
        assert ("node_192_168_1_1", "node_192_168_1_10") in removed_edge_pairs

    def test_diff_returns_dict_with_correct_keys(self):
        topo = self._topology_with([])
        diff = diff_topologies(topo, topo)
        assert set(diff.keys()) == {"new_nodes", "removed_nodes", "new_edges", "removed_edges"}

    def test_empty_vs_populated(self):
        previous = NetworkTopology(nodes=[], edges=[])
        current = self._topology_with(["192.168.1.10"])
        diff = diff_topologies(current, previous)
        assert len(diff["new_nodes"]) > 0


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestTopologyCLI:
    runner = CliRunner()

    def _make_topology(self) -> NetworkTopology:
        nodes = [
            make_node(ID_INTERNET, "Internet", NODE_INTERNET),
            make_node("node_192_168_1_1", "Gateway (192.168.1.1)", NODE_GATEWAY, ip="192.168.1.1"),
            make_node("node_192_168_1_10", "macbook (192.168.1.10)", NODE_HOST, ip="192.168.1.10"),
        ]
        edges = [
            make_edge(ID_INTERNET, "node_192_168_1_1", "routed"),
            make_edge("node_192_168_1_1", "node_192_168_1_10", "direct"),
        ]
        return NetworkTopology(nodes=nodes, edges=edges)

    def _cli_app(self):
        from netglance.cli.topology import app
        return app

    def test_show_ascii_default(self):
        topo = self._make_topology()
        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(self._cli_app(), ["show", "--no-save"])
        assert result.exit_code == 0
        assert "Internet" in result.output

    def test_show_dot_format(self):
        topo = self._make_topology()
        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(self._cli_app(), ["show", "--format", "dot", "--no-save"])
        assert result.exit_code == 0
        assert "digraph" in result.output

    def test_show_json_format(self):
        topo = self._make_topology()
        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(self._cli_app(), ["show", "--format", "json", "--no-save"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data
        assert "links" in data

    def test_show_json_flag(self):
        topo = self._make_topology()
        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(self._cli_app(), ["show", "--json", "--no-save"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data

    def test_show_output_to_file(self, tmp_path: Path):
        topo = self._make_topology()
        out_file = tmp_path / "topo.dot"
        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(
                self._cli_app(),
                ["show", "--format", "dot", "--output", str(out_file), "--no-save"],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "digraph" in content

    def test_show_error_on_discover_failure(self):
        with patch("netglance.cli.topology.discover_topology", side_effect=RuntimeError("network error")):
            result = self.runner.invoke(self._cli_app(), ["show", "--no-save"])
        assert result.exit_code == 1

    def test_diff_no_saved_topology_exits(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        with patch("netglance.cli.topology.discover_topology", return_value=self._make_topology()):
            result = self.runner.invoke(
                self._cli_app(), ["diff", "--db", str(db_path)]
            )
        assert result.exit_code == 1

    def test_diff_with_saved_topology(self, tmp_path: Path):
        from netglance.store.db import Store

        db_path = tmp_path / "test.db"
        store = Store(db_path=str(db_path))
        store.init_db()

        topo = self._make_topology()
        store.save_result("topology", topology_to_json(topo))

        # Current topology has one extra device
        current_topo = NetworkTopology(
            nodes=topo.nodes + [make_node("node_192_168_1_99", "new-host (192.168.1.99)", NODE_HOST, ip="192.168.1.99")],
            edges=topo.edges + [make_edge("node_192_168_1_1", "node_192_168_1_99")],
        )

        with patch("netglance.cli.topology.discover_topology", return_value=current_topo):
            result = self.runner.invoke(
                self._cli_app(), ["diff", "--db", str(db_path)]
            )
        assert result.exit_code == 0
        assert "new-host" in result.output

    def test_diff_json_flag(self, tmp_path: Path):
        from netglance.store.db import Store

        db_path = tmp_path / "test.db"
        store = Store(db_path=str(db_path))
        store.init_db()
        topo = self._make_topology()
        store.save_result("topology", topology_to_json(topo))

        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(
                self._cli_app(), ["diff", "--json", "--db", str(db_path)]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "new_nodes" in data

    def test_diff_no_changes_message(self, tmp_path: Path):
        from netglance.store.db import Store

        db_path = tmp_path / "test.db"
        store = Store(db_path=str(db_path))
        store.init_db()
        topo = self._make_topology()
        store.save_result("topology", topology_to_json(topo))

        with patch("netglance.cli.topology.discover_topology", return_value=topo):
            result = self.runner.invoke(
                self._cli_app(), ["diff", "--db", str(db_path)]
            )
        assert result.exit_code == 0
        assert "No topology changes" in result.output
