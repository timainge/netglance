"""Topology CLI subcommands."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from netglance.cli._shared import maybe_warn_db_size
from netglance.modules.topology import (
    diff_topologies,
    discover_topology,
    topology_to_ascii,
    topology_to_dot,
    topology_to_json,
)
from netglance.store.models import NetworkTopology, TopologyEdge, TopologyNode

app = typer.Typer(help="Network topology visualization.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)

_TOPO_MODULE = "topology"


@app.command("show")
def show_cmd(
    subnet: str = typer.Option(
        "192.168.1.0/24",
        "--subnet",
        "-s",
        help="Subnet to scan (CIDR notation).",
    ),
    format: str = typer.Option(
        "ascii",
        "--format",
        "-f",
        help="Output format: ascii, dot, json.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file instead of printing.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output topology as JSON (shorthand for --format json).",
    ),
    save: bool = typer.Option(
        True,
        "--save/--no-save",
        help="Save topology snapshot to DB for later diff.",
    ),
    db: Optional[Path] = typer.Option(
        None,
        "--db",
        hidden=True,
        help="Override database path (for testing).",
    ),
) -> None:
    """Discover and display the network topology."""
    if as_json:
        format = "json"

    try:
        topology = discover_topology(subnet=subnet)
    except Exception as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    if format == "dot":
        result_text = topology_to_dot(topology)
    elif format == "json":
        result_text = json.dumps(topology_to_json(topology), indent=2)
    else:
        # ascii is default
        result_text = topology_to_ascii(topology)

    if output is not None:
        output.write_text(result_text)
        console.print(f"[green]Topology saved to[/green] {output}")
    else:
        if format == "ascii":
            console.print(result_text, end="")
        else:
            console.print(result_text)

    # Persist topology snapshot for future diff (non-fatal on error)
    if save:
        try:
            from netglance.store.db import Store

            db_path = str(db) if db else None
            store = Store(db_path=db_path) if db_path else Store()
            store.init_db()
            store.save_result(_TOPO_MODULE, topology_to_json(topology))
            console.print("[dim]✓ Saved to local database.[/dim]")
            maybe_warn_db_size(store, console)
        except Exception:
            pass


@app.command("diff")
def diff_cmd(
    subnet: str = typer.Option(
        "192.168.1.0/24",
        "--subnet",
        "-s",
        help="Subnet to scan for current state.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output diff as JSON.",
    ),
    db: Optional[Path] = typer.Option(
        None,
        "--db",
        hidden=True,
        help="Override database path (for testing).",
    ),
) -> None:
    """Compare current topology to the last saved snapshot."""
    from netglance.store.db import Store

    db_path = str(db) if db else None
    store = Store(db_path=db_path) if db_path else Store()
    store.init_db()

    # Load previous topology from store
    saved = store.get_results(_TOPO_MODULE, limit=1)
    if not saved:
        err_console.print(
            "[yellow]No saved topology found.[/yellow] "
            "Run [bold]topo show[/bold] first to create a baseline."
        )
        raise typer.Exit(code=1)

    prev_data = saved[0]

    # Reconstruct previous NetworkTopology from stored JSON
    prev_nodes = [
        TopologyNode(
            id=n["id"],
            label=n["label"],
            node_type=n["type"],
            ip=n.get("ip"),
            mac=n.get("mac"),
            vendor=n.get("vendor"),
        )
        for n in prev_data.get("nodes", [])
    ]
    prev_edges = [
        TopologyEdge(
            source=e["source"],
            target=e["target"],
            edge_type=e["type"],
            latency_ms=e.get("latency_ms"),
            label=e.get("label", ""),
        )
        for e in prev_data.get("links", [])
    ]
    previous = NetworkTopology(
        nodes=prev_nodes,
        edges=prev_edges,
        timestamp=datetime.fromisoformat(
            prev_data.get("timestamp", datetime.now().isoformat())
        ),
    )

    # Discover current topology
    try:
        current = discover_topology(subnet=subnet)
    except Exception as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    diff = diff_topologies(current, previous)

    if as_json:
        console.print_json(json.dumps(diff))
        return

    # Pretty print diff
    new_nodes = diff["new_nodes"]
    removed_nodes = diff["removed_nodes"]
    new_edges = diff["new_edges"]
    removed_edges = diff["removed_edges"]

    if not any([new_nodes, removed_nodes, new_edges, removed_edges]):
        console.print("[green]No topology changes detected.[/green]")
        return

    if new_nodes:
        console.print(f"[green]New nodes ({len(new_nodes)}):[/green]")
        for node in new_nodes:
            console.print(f"  + {node['label']} ({node['type']})")

    if removed_nodes:
        console.print(f"[red]Removed nodes ({len(removed_nodes)}):[/red]")
        for node in removed_nodes:
            console.print(f"  - {node['label']} ({node['type']})")

    if new_edges:
        console.print(f"[green]New connections ({len(new_edges)}):[/green]")
        for edge in new_edges:
            console.print(f"  + {edge['source']} -> {edge['target']}")

    if removed_edges:
        console.print(f"[red]Removed connections ({len(removed_edges)}):[/red]")
        for edge in removed_edges:
            console.print(f"  - {edge['source']} -> {edge['target']}")
