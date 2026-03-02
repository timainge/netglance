"""Network topology inference and rendering.

Infers the network topology from device discovery, ARP table, and traceroute data.
Renders topology as ASCII tree, Graphviz DOT, or JSON for D3.js.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable

from netglance.store.models import (
    ArpEntry,
    Device,
    Hop,
    NetworkTopology,
    TopologyEdge,
    TopologyNode,
    TraceResult,
)

# Node type constants
NODE_INTERNET = "internet"
NODE_GATEWAY = "gateway"
NODE_HOST = "host"

# Special node IDs
ID_INTERNET = "internet"


def _device_label(device: Device) -> str:
    """Return a human-readable label for a device."""
    parts: list[str] = []
    if device.hostname:
        parts.append(device.hostname)
    parts.append(f"({device.ip})")
    if device.vendor:
        parts.append(f"[{device.vendor}]")
    return " ".join(parts)


def _node_id_for_ip(ip: str) -> str:
    """Return a stable node ID for an IP address."""
    return f"node_{ip.replace('.', '_')}"


def build_topology(
    devices: list[Device],
    arp_entries: list[ArpEntry],
    trace_results: list[TraceResult],
    gateway_ip: str | None,
    *,
    _discover_fn: Callable | None = None,
    _arp_fn: Callable | None = None,
    _route_fn: Callable | None = None,
) -> NetworkTopology:
    """Build a NetworkTopology from already-collected data.

    Infers topology: internet → ISP hops → gateway → local devices.

    Args:
        devices: Local devices from arp/mdns discovery.
        arp_entries: Current ARP table entries.
        trace_results: Traceroute results (typically to 8.8.8.8 or similar).
        gateway_ip: The default gateway IP, or None if unknown.
        _discover_fn: Unused DI param (reserved for live gather).
        _arp_fn: Unused DI param (reserved for live gather).
        _route_fn: Unused DI param (reserved for live gather).

    Returns:
        NetworkTopology with nodes and edges inferred from the data.
    """
    nodes: list[TopologyNode] = []
    edges: list[TopologyEdge] = []

    # Build ARP lookup: ip -> mac
    arp_by_ip: dict[str, str] = {e.ip: e.mac for e in arp_entries}

    # Build device lookup: ip -> Device
    device_by_ip: dict[str, Device] = {d.ip: d for d in devices}

    # --- Internet node (always present) ---
    internet_node = TopologyNode(
        id=ID_INTERNET,
        label="Internet",
        node_type=NODE_INTERNET,
    )
    nodes.append(internet_node)

    # --- Gateway node ---
    gateway_node_id: str | None = None
    if gateway_ip:
        gw_mac = arp_by_ip.get(gateway_ip)
        gw_device = device_by_ip.get(gateway_ip)
        gw_vendor = gw_device.vendor if gw_device else None
        gw_hostname = gw_device.hostname if gw_device else None

        gw_label_parts = [f"Gateway ({gateway_ip})"]
        if gw_vendor:
            gw_label_parts.append(f"[{gw_vendor}]")
        elif gw_hostname:
            gw_label_parts.append(f"[{gw_hostname}]")

        gateway_node_id = _node_id_for_ip(gateway_ip)
        gateway_node = TopologyNode(
            id=gateway_node_id,
            label=" ".join(gw_label_parts),
            node_type=NODE_GATEWAY,
            ip=gateway_ip,
            mac=gw_mac,
            vendor=gw_vendor,
        )
        nodes.append(gateway_node)

    # --- ISP hops from traceroute (external hops only) ---
    # Extract intermediate hops that are NOT on the local network
    local_ips = {d.ip for d in devices}
    if gateway_ip:
        local_ips.add(gateway_ip)

    isp_hop_node_ids: list[tuple[str, float | None]] = []  # (node_id, latency_ms)

    for trace in trace_results:
        prev_node_id = ID_INTERNET
        for hop in trace.hops:
            if hop.ip is None:
                continue
            # Skip local IPs (gateway and local devices)
            if hop.ip in local_ips:
                break
            node_id = _node_id_for_ip(hop.ip)
            # Add node if not already added
            if not any(n.id == node_id for n in nodes):
                hop_label_parts = [hop.ip]
                if hop.hostname:
                    hop_label_parts.append(f"({hop.hostname})")
                if hop.as_name:
                    hop_label_parts.append(f"[{hop.as_name}]")
                hop_node = TopologyNode(
                    id=node_id,
                    label=" ".join(hop_label_parts),
                    node_type="host",
                    ip=hop.ip,
                )
                nodes.append(hop_node)
                isp_hop_node_ids.append((node_id, hop.rtt_ms))

                edge = TopologyEdge(
                    source=prev_node_id,
                    target=node_id,
                    edge_type="routed",
                    latency_ms=hop.rtt_ms,
                    label=f"{hop.rtt_ms:.1f}ms" if hop.rtt_ms is not None else "",
                )
                edges.append(edge)
            prev_node_id = node_id

    # --- Connect internet to gateway ---
    if gateway_node_id:
        # Determine latency from first traceroute hop at/near the gateway
        gw_latency: float | None = None
        for trace in trace_results:
            for hop in trace.hops:
                if hop.ip == gateway_ip and hop.rtt_ms is not None:
                    gw_latency = hop.rtt_ms
                    break

        # If we have ISP hops, connect the last ISP hop to gateway
        # Otherwise connect internet directly to gateway
        last_external = isp_hop_node_ids[-1][0] if isp_hop_node_ids else ID_INTERNET
        if not any(
            e.source == last_external and e.target == gateway_node_id for e in edges
        ):
            edge = TopologyEdge(
                source=last_external,
                target=gateway_node_id,
                edge_type="routed",
                latency_ms=gw_latency,
                label=f"{gw_latency:.1f}ms" if gw_latency is not None else "",
            )
            edges.append(edge)

    # --- Local device nodes ---
    for device in devices:
        if device.ip == gateway_ip:
            continue  # Already added as gateway
        node_id = _node_id_for_ip(device.ip)
        mac = device.mac or arp_by_ip.get(device.ip)
        node = TopologyNode(
            id=node_id,
            label=_device_label(device),
            node_type=NODE_HOST,
            ip=device.ip,
            mac=mac,
            vendor=device.vendor,
        )
        nodes.append(node)

        # Connect to gateway (or internet if no gateway)
        parent_id = gateway_node_id if gateway_node_id else ID_INTERNET
        edge = TopologyEdge(
            source=parent_id,
            target=node_id,
            edge_type="direct",
        )
        edges.append(edge)

    return NetworkTopology(nodes=nodes, edges=edges, timestamp=datetime.now())


def discover_topology(
    subnet: str = "192.168.1.0/24",
    trace_targets: list[str] | None = None,
    *,
    _discover_fn: Callable | None = None,
    _arp_fn: Callable | None = None,
    _trace_fn: Callable | None = None,
    _gateway_fn: Callable | None = None,
) -> NetworkTopology:
    """High-level convenience: discover devices, trace routes, build topology.

    Args:
        subnet: CIDR subnet to scan for devices.
        trace_targets: IPs to trace to. Defaults to ["8.8.8.8"].
        _discover_fn: Injectable discover function (returns list[Device]).
        _arp_fn: Injectable ARP table function (returns list[ArpEntry]).
        _trace_fn: Injectable traceroute function (host -> TraceResult).
        _gateway_fn: Injectable gateway detection function (returns str | None).

    Returns:
        NetworkTopology built from live data.
    """
    from netglance.modules.discover import arp_scan
    from netglance.modules.arp import get_arp_table
    from netglance.modules.ping import get_default_gateway
    from netglance.modules.route import traceroute

    targets = trace_targets or ["8.8.8.8"]

    discover = _discover_fn or (lambda: arp_scan(subnet))
    arp = _arp_fn or get_arp_table
    trace = _trace_fn or traceroute
    gateway_fn = _gateway_fn or get_default_gateway

    devices = discover()
    arp_entries = arp()
    gateway_ip = gateway_fn()
    trace_results = [trace(t) for t in targets]

    return build_topology(
        devices=devices,
        arp_entries=arp_entries,
        trace_results=trace_results,
        gateway_ip=gateway_ip,
    )


def topology_to_dot(topology: NetworkTopology) -> str:
    """Render topology as Graphviz DOT format.

    Node shapes: internet=cloud (ellipse), gateway=diamond, host=box.
    Color coding: gateway=red fill, hosts=lightblue, internet=lightgray.

    Args:
        topology: The network topology to render.

    Returns:
        String containing valid Graphviz DOT notation.
    """
    lines: list[str] = ["digraph network_topology {", '    rankdir=TB;', '    node [fontname="Helvetica"];', ""]

    for node in topology.nodes:
        node_id = node.id
        label = node.label.replace('"', '\\"')

        if node.node_type == NODE_INTERNET:
            attrs = 'shape=ellipse, style=filled, fillcolor=lightgray, label="{label}"'.format(label=label)
        elif node.node_type == NODE_GATEWAY:
            attrs = 'shape=diamond, style=filled, fillcolor=lightsalmon, label="{label}"'.format(label=label)
        else:
            attrs = 'shape=box, style=filled, fillcolor=lightblue, label="{label}"'.format(label=label)

        lines.append(f'    "{node_id}" [{attrs}];')

    lines.append("")

    for edge in topology.edges:
        src = edge.source
        tgt = edge.target
        label = edge.label.replace('"', '\\"') if edge.label else ""
        if label:
            lines.append(f'    "{src}" -> "{tgt}" [label="{label}"];')
        else:
            lines.append(f'    "{src}" -> "{tgt}";')

    lines.append("}")
    return "\n".join(lines)


def topology_to_json(topology: NetworkTopology) -> dict[str, Any]:
    """Serialize topology to a JSON-compatible dict for D3.js force-directed graph.

    Args:
        topology: The network topology to serialize.

    Returns:
        Dict with "nodes" and "links" arrays suitable for D3.js.
    """
    nodes_out: list[dict[str, Any]] = []
    for node in topology.nodes:
        nodes_out.append({
            "id": node.id,
            "label": node.label,
            "type": node.node_type,
            "ip": node.ip,
            "mac": node.mac,
            "vendor": node.vendor,
        })

    links_out: list[dict[str, Any]] = []
    for edge in topology.edges:
        links_out.append({
            "source": edge.source,
            "target": edge.target,
            "type": edge.edge_type,
            "latency_ms": edge.latency_ms,
            "label": edge.label,
        })

    return {
        "nodes": nodes_out,
        "links": links_out,
        "timestamp": topology.timestamp.isoformat(),
    }


def topology_to_ascii(topology: NetworkTopology) -> str:
    """Render topology as a rich-formatted ASCII tree.

    Uses rich.tree.Tree for colored output. Internet is the root,
    gateway is the second level, local devices are leaves.

    Args:
        topology: The network topology to render.

    Returns:
        String with ANSI-colored tree representation (via rich).
    """
    from io import StringIO
    from rich.console import Console
    from rich.tree import Tree

    # Build adjacency: parent_id -> list of child node ids
    adjacency: dict[str, list[str]] = {}
    for edge in topology.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    # Build node lookup
    node_by_id: dict[str, TopologyNode] = {n.id: n for n in topology.nodes}

    def _node_label(node: TopologyNode) -> str:
        """Format label with color markup for rich."""
        if node.node_type == NODE_INTERNET:
            return f"[bold gray50]{node.label}[/bold gray50]"
        elif node.node_type == NODE_GATEWAY:
            return f"[bold red]{node.label}[/bold red]"
        else:
            return f"[blue]{node.label}[/blue]"

    def _add_children(tree_node: Tree, parent_id: str) -> None:
        for child_id in adjacency.get(parent_id, []):
            child = node_by_id.get(child_id)
            if child is None:
                continue
            branch = tree_node.add(_node_label(child))
            _add_children(branch, child_id)

    # Start from internet node (root)
    internet = node_by_id.get(ID_INTERNET)
    if internet is None:
        # Fall back: pick first node as root
        if not topology.nodes:
            return "(empty topology)"
        internet = topology.nodes[0]

    root_tree = Tree(_node_label(internet))
    _add_children(root_tree, internet.id)

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True)
    console.print(root_tree)
    return buf.getvalue()


def diff_topologies(
    current: NetworkTopology,
    previous: NetworkTopology,
) -> dict[str, Any]:
    """Compare two topologies and return a summary of changes.

    Args:
        current: The newer topology.
        previous: The older topology.

    Returns:
        Dict with keys:
            new_nodes: list of TopologyNode dicts added in current.
            removed_nodes: list of TopologyNode dicts removed from current.
            new_edges: list of TopologyEdge dicts added in current.
            removed_edges: list of TopologyEdge dicts removed from current.
    """
    current_node_ids = {n.id for n in current.nodes}
    previous_node_ids = {n.id for n in previous.nodes}

    current_by_id = {n.id: n for n in current.nodes}
    previous_by_id = {n.id: n for n in previous.nodes}

    new_ids = current_node_ids - previous_node_ids
    removed_ids = previous_node_ids - current_node_ids

    new_nodes = [_node_to_dict(current_by_id[nid]) for nid in sorted(new_ids)]
    removed_nodes = [_node_to_dict(previous_by_id[nid]) for nid in sorted(removed_ids)]

    # Edges: compare by (source, target) tuple
    current_edge_keys = {(e.source, e.target) for e in current.edges}
    previous_edge_keys = {(e.source, e.target) for e in previous.edges}

    current_edge_by_key = {(e.source, e.target): e for e in current.edges}
    previous_edge_by_key = {(e.source, e.target): e for e in previous.edges}

    new_edge_keys = current_edge_keys - previous_edge_keys
    removed_edge_keys = previous_edge_keys - current_edge_keys

    new_edges = [_edge_to_dict(current_edge_by_key[k]) for k in sorted(new_edge_keys)]
    removed_edges = [_edge_to_dict(previous_edge_by_key[k]) for k in sorted(removed_edge_keys)]

    return {
        "new_nodes": new_nodes,
        "removed_nodes": removed_nodes,
        "new_edges": new_edges,
        "removed_edges": removed_edges,
    }


def _node_to_dict(node: TopologyNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "label": node.label,
        "type": node.node_type,
        "ip": node.ip,
        "mac": node.mac,
        "vendor": node.vendor,
    }


def _edge_to_dict(edge: TopologyEdge) -> dict[str, Any]:
    return {
        "source": edge.source,
        "target": edge.target,
        "type": edge.edge_type,
        "latency_ms": edge.latency_ms,
        "label": edge.label,
    }
